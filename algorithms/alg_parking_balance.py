# -*- coding: utf-8 -*-
"""Parking Supply-Demand Balance algorithm wrapper."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_DEMAND, STRING, PlanXAlgorithm
from ..engine import graphs, parking, paths

#: Zones per pass of the cost matrix. The full matrix is zones x inventory
#: features; at 10k zones and 5k facilities that is 400 MB of float64, so the
#: distances are accumulated in bounded blocks instead.
ZONE_BLOCK = 512


class ParkingSupplyBalanceAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_parkingbalance.png"
    ZONES = "ZONES"
    DEMAND_FIELD = "DEMAND_FIELD"
    SUPPLY = "SUPPLY"
    SUPPLY_FIELD = "SUPPLY_FIELD"
    RADIUS = "RADIUS"
    NETWORK = "NETWORK"
    OUTPUT = "OUTPUT"

    def name(self):
        return "parkingsupplybalance"

    def displayName(self):
        return self.tr("Parking Supply-Demand Balance")

    def shortHelpString(self):
        return self.tr(
            "Compares the parking each zone demands with the parking it "
            "actually has within reach, and reports the surplus or deficit.\n\n"
            "Zones carry the demand figure the Parking Demand Estimator "
            "produced (its parking_demand column, joined back onto your zone "
            "polygons by zone id). Supply is counted from a real parking "
            "inventory - a point or polygon layer of parking facilities with "
            "a field holding the number of spaces each one provides. This "
            "tool invents no supply figures of its own: with no inventory "
            "there is nothing to balance against.\n\n"
            "Reach is measured by the radius you set, in map units. Supply a "
            "street network and reach follows the streets; leave it out and "
            "reach is straight-line distance. The radius_method column "
            "records which was used, so a figure can always be traced back "
            "to the assumption behind it. In network mode a facility and a "
            "zone are each attached to their nearest network node, so the "
            "measured distance is that to the nodes, not to the exact point: "
            "on a coarse network this overstates distance by up to about a "
            "node spacing.\n\n"
            "How to read the results\n"
            "- balance_spaces is supply_spaces minus demand_spaces: negative "
            "is a deficit, positive a surplus. It is NULL wherever the "
            "supply is unknown, so summing the column never reports "
            "unsurveyed ground as a shortfall.\n"
            "- supply_status says which case each zone is, and the three "
            "cases are genuinely different findings. 'counted' means "
            "inventory was found in range. 'zero supply found' means the "
            "inventory reaches this zone and holds nothing in range - a real "
            "deficit. 'supply data absent' means no inventory is in range "
            "and the inventory layer does not reach this zone at all - a "
            "coverage gap in your data, which is not evidence of a parking "
            "problem.\n"
            "- Read the two counts before the totals. A large 'supply data "
            "absent' share means the inventory covers only part of the study "
            "area, and the surplus or deficit is computed over the surveyed "
            "zones alone.\n"
            "- nearest_supply_dist is the distance to the closest inventory "
            "feature however far away it is. It separates the two ways a "
            "zone can have nothing in range: a facility slightly beyond a "
            "tight radius, or no facility anywhere near.\n\n"
            "Using the results: sort by balance_spaces ascending to rank the "
            "worst-served zones first, reading supply_status as you go so a "
            "coverage gap is not mistaken for a shortfall; compare two "
            "radius values to see how sensitive the deficits are to how far "
            "you assume people will walk; re-run with a scenario's demand "
            "layer to test whether a land-use change creates a parking "
            "problem, and with a proposed inventory to test whether it "
            "solves one."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zone layer (carries the demand field)"),
            [QgsProcessing.SourceType.TypeVectorPolygon,
             QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.DEMAND_FIELD, self.tr("Parking demand field (spaces per zone, "
                                       "from the Parking Demand Estimator)"),
            parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.DataType.Numeric,
            defaultValue="parking_demand"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SUPPLY, self.tr("Parking inventory (facilities with a space "
                                 "count)"),
            [QgsProcessing.SourceType.TypeVectorPoint,
             QgsProcessing.SourceType.TypeVectorPolygon]))
        self.addParameter(QgsProcessingParameterField(
            self.SUPPLY_FIELD, self.tr("Spaces per facility"),
            parentLayerParameterName=self.SUPPLY,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.RADIUS, self.tr("Access radius (map units; use a projected "
                                 "CRS to read this as metres)"),
            QgsProcessingParameterNumber.Type.Double, 300.0, minValue=0.0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (optional; reach follows "
                                  "the streets instead of a straight line)"),
            [QgsProcessing.SourceType.TypeVectorLine], optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Parking balance table")))

    def _cost_block(self, graph, zone_nodes, zone_snap, supply_nodes,
                    supply_snap, start, stop):
        """(stop-start, features) access costs for one block of zones.

        Deliberately uncut. Pruning the search at the radius would be sound for
        the in-range sums - a facility beyond the radius is out of range with
        or without its snapping offset - but it would leave every unreached
        node at infinity, and nearest_supply_dist promises the distance to the
        closest facility *however far away it is*. A cut radius would make that
        column report only distances already inside the radius, which is the
        opposite of the two-cases-it-separates job the help text gives it.
        """
        n_supply = len(supply_nodes)
        block = np.full((stop - start, n_supply), np.inf)
        for row, zone_index in enumerate(range(start, stop)):
            dist, _ = paths.multi_source_offset(
                graph.indptr, graph.adj_node, graph.adj_cost, graph.num_nodes,
                [int(zone_nodes[zone_index])], [float(zone_snap[zone_index])])
            block[row] = dist[supply_nodes] + supply_snap
        return block

    def processAlgorithm(self, parameters, context, feedback):
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        supply = self.parameterAsSource(parameters, self.SUPPLY, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        demand_field = self.parameterAsString(
            parameters, self.DEMAND_FIELD, context)
        supply_field = self.parameterAsString(
            parameters, self.SUPPLY_FIELD, context)
        radius = self.parameterAsDouble(parameters, self.RADIUS, context)
        xform_ctx = context.transformContext()

        # Everything is measured in one CRS. With a network that is the
        # network's own CRS, since network_graph reads its geometry as-is.
        target_crs = (network.sourceCrs() if network is not None
                      else zones.sourceCrs())
        feedback.pushInfo(self.tr(
            f"Measuring access in {target_crs.authid() or 'the zone CRS'}."))

        zone_xy, zone_feats = self.source_points(zones, target_crs, xform_ctx)
        demand_idx = zones.fields().lookupField(demand_field)
        if demand_idx < 0:
            raise QgsProcessingException(
                f"Zone layer has no field '{demand_field}'.")
        demand = np.array([
            self._number_or_zero(feature.attributes()[demand_idx])
            for feature in zone_feats], dtype=np.float64)

        spaces_idx = supply.fields().lookupField(supply_field)
        if spaces_idx < 0:
            raise QgsProcessingException(
                f"Parking inventory has no field '{supply_field}'.")

        if supply.featureCount() == 0:
            # An empty inventory is a data state, not a failure: every zone
            # is unsurveyed, and the output says so rather than reporting a
            # city-wide deficit.
            feedback.pushWarning(self.tr(
                "The parking inventory has no features. Every zone is "
                "reported as 'supply data absent'; no balance is computed."))
            supply_xy = np.empty((0, 2), dtype=np.float64)
            spaces = np.empty(0, dtype=np.float64)
        else:
            supply_xy, supply_feats = self.source_points(
                supply, target_crs, xform_ctx)
            spaces = np.array([
                self._number_or_zero(feature.attributes()[spaces_idx])
                for feature in supply_feats], dtype=np.float64)

        # A zone is surveyed when the inventory's footprint reaches it. The
        # footprint is the inventory's extent: a proxy, and the honest one
        # available without a separate coverage layer.
        if len(supply_xy):
            covered = ((zone_xy[:, 0] >= supply_xy[:, 0].min())
                       & (zone_xy[:, 0] <= supply_xy[:, 0].max())
                       & (zone_xy[:, 1] >= supply_xy[:, 1].min())
                       & (zone_xy[:, 1] <= supply_xy[:, 1].max()))
        else:
            covered = np.zeros(len(zone_xy), dtype=bool)

        n_zones = len(zone_xy)
        spaces_found = np.zeros(n_zones)
        features_found = np.zeros(n_zones, dtype=np.int64)
        nearest = np.full(n_zones, np.inf)

        if network is not None:
            method = "network"
            graph, polylines, _ = self.network_graph(network, "", feedback)
            feedback.pushInfo(self.tr(
                f"Network reach: {len(polylines)} street segments, "
                f"{graph.num_nodes} nodes, radius {radius:g}."))
            zone_nodes = graphs.nearest_nodes(graph, zone_xy)
            zone_snap = np.hypot(
                zone_xy[:, 0] - graph.node_xy[zone_nodes][:, 0],
                zone_xy[:, 1] - graph.node_xy[zone_nodes][:, 1])
            if len(supply_xy):
                supply_nodes = graphs.nearest_nodes(graph, supply_xy)
                supply_snap = np.hypot(
                    supply_xy[:, 0] - graph.node_xy[supply_nodes][:, 0],
                    supply_xy[:, 1] - graph.node_xy[supply_nodes][:, 1])
            else:
                supply_nodes = np.empty(0, dtype=np.int32)
                supply_snap = np.empty(0, dtype=np.float64)

            for start in range(0, n_zones, ZONE_BLOCK):
                if feedback.isCanceled():
                    break
                stop = min(start + ZONE_BLOCK, n_zones)
                costs = self._cost_block(
                    graph, zone_nodes, zone_snap, supply_nodes, supply_snap,
                    start, stop)
                found, count = parking.supply_within(costs, spaces, radius)
                spaces_found[start:stop] = found
                features_found[start:stop] = count
                nearest[start:stop] = parking.nearest_supply_cost(costs)
                feedback.setProgress(int(70.0 * stop / max(n_zones, 1)))
        else:
            method = "straight_line"
            feedback.pushInfo(self.tr(
                f"Straight-line reach (no network supplied), radius "
                f"{radius:g}."))
            for start in range(0, n_zones, ZONE_BLOCK):
                if feedback.isCanceled():
                    break
                stop = min(start + ZONE_BLOCK, n_zones)
                costs = parking.straight_line_costs(
                    zone_xy[start:stop], supply_xy)
                found, count = parking.supply_within(costs, spaces, radius)
                spaces_found[start:stop] = found
                features_found[start:stop] = count
                nearest[start:stop] = parking.nearest_supply_cost(costs)
                feedback.setProgress(int(70.0 * stop / max(n_zones, 1)))

        status = parking.classify_supply(features_found, covered)
        balance = parking.balance(demand, spaces_found, status)

        out_fields = self.make_fields(
            ("demand_spaces", DOUBLE),
            ("supply_spaces", DOUBLE),
            ("balance_spaces", DOUBLE),
            ("supply_status", STRING),
            ("nearest_supply_dist", DOUBLE),
            ("radius_method", STRING),
            base=zones.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, out_fields,
            QgsWkbTypes.Type.NoGeometry)

        n_base = len(zones.fields())
        for i, feature in enumerate(zone_feats):
            if feedback.isCanceled():
                break
            near = nearest[i]
            out_feat = QgsFeature(out_fields)
            out_feat.setAttributes(
                list(feature.attributes())[:n_base] + [
                    round(float(demand[i]), 2),
                    round(float(spaces_found[i]), 2),
                    (None if balance[i] is None
                     else round(float(balance[i]), 2)),
                    status[i],
                    (None if not np.isfinite(near) else round(float(near), 2)),
                    method])
            sink.addFeature(out_feat, QgsFeatureSink.Flag.FastInsert)

        for label, value in parking.balance_summary(
                demand, spaces_found, status):
            # Zone counts are counts; spaces are quantities. A count printed as
            # "18.00 zones" reads as a measurement, so leave integral values
            # undecorated.
            shown = (f"{value:,.0f}" if float(value).is_integer()
                     else f"{value:,.2f}")
            feedback.pushInfo(f"  {label}: {shown}")
        absent = sum(1 for state in status if state == parking.SUPPLY_ABSENT)
        if absent:
            feedback.pushInfo(self.tr(
                f"  {absent} zone(s) outside the parking inventory's extent "
                f"are reported 'supply data absent' with no balance. The "
                f"inventory covers only part of the study area."))

        return {self.OUTPUT: dest}

    @staticmethod
    def _number_or_zero(value) -> float:
        """A NULL or non-numeric cell counts as zero, and is never a crash."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        return 0.0 if not np.isfinite(number) else number

    def createInstance(self):
        return ParkingSupplyBalanceAlgorithm()
