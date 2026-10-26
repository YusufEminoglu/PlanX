# -*- coding: utf-8 -*-
"""Jobs-Housing Balance: local and commute-shed ratios, Duncan dissimilarity."""
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
)

from . import _units
from .base import DOUBLE, GROUP_DEMAND, PlanXAlgorithm
from ..engine import graphs, jobshousing, paths


def _r(value, digits=4):
    return None if value is None or not np.isfinite(value) else round(float(value), digits)


class JobsHousingBalanceAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_DEMAND
    ICON = "tool_jobshousing.png"
    RENDER_FIELD = "bal_shed"

    ZONES = "ZONES"
    JOBS_FIELD = "JOBS_FIELD"
    WORKERS_FIELD = "WORKERS_FIELD"
    WORKER_RATIO = "WORKER_RATIO"
    NETWORK = "NETWORK"
    COST_FIELD = "COST_FIELD"
    SPEED = "SPEED"
    BUDGET = "BUDGET"
    OUTPUT = "OUTPUT"

    def name(self):
        return "jobshousing"

    def displayName(self):
        return self.tr("Jobs-Housing Balance")

    def shortHelpString(self):
        return self.tr(
            "Whether jobs and the workers who could fill them are in the same "
            "places - the land-use side of commuting (Cervero 1989).\n\n"
            "For every zone: the local ratio of jobs to resident workers, and "
            "the commute-shed ratio - jobs over workers in every zone within a "
            "network travel budget, which is the balance a resident actually "
            "experiences and depends far less on where zone boundaries fall. "
            "Both come with a balance index 1 - |J - W| / (J + W): 1 when the "
            "two match, 0 when one side is absent. The log adds the area-wide "
            "ratio and Duncan's index of dissimilarity between the two "
            "distributions - the share of jobs that would have to move for "
            "jobs and workers to be spread alike.\n\n"
            "The workers field may hold workers, residents or dwellings; the "
            "worker ratio converts it (e.g. 0.45 workers per resident, 1.2 per "
            "dwelling). Travel time is a cost field in minutes, or ground "
            "length over the speed.\n\n"
            "How to read the results\n"
            "- jhr_shed near 1 (bal_shed near 1) is a balanced commute shed; "
            "well above 1 is a job centre importing workers, well below 1 a "
            "dormitory area exporting them. Published 'balanced' ranges differ "
            "with what is counted as a worker, so read the ratio against the "
            "area-wide ratio the log prints.\n"
            "- A zone unbalanced locally but balanced within its shed is fine "
            "at the commute scale; a zone unbalanced at both is where mixed-use "
            "rezoning or new jobs would shorten commutes.\n"
            "- Dissimilarity is the one-number summary for comparing plans: a "
            "plan that lowers it brings jobs and homes together.\n"
            "- Balance is a necessary, not a sufficient, condition: workers "
            "take jobs that match their skills, not the nearest ones.\n\n"
            "Using the results: compare base and plan zone tables; map bal_shed "
            "with Gravity Accessibility's job access to separate places that "
            "lack jobs from places that cannot reach them."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ZONES, self.tr("Zones (points or polygons)"),
            [QgsProcessing.SourceType.TypeVectorPolygon, QgsProcessing.SourceType.TypeVectorPoint]))
        self.addParameter(QgsProcessingParameterField(
            self.JOBS_FIELD, self.tr("Jobs field"), parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterField(
            self.WORKERS_FIELD, self.tr("Workers (or residents, dwellings) field"),
            parentLayerParameterName=self.ZONES,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.WORKER_RATIO, self.tr("Workers per unit of that field"),
            QgsProcessingParameterNumber.Type.Double, 1.0, minValue=1e-6))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"),
            [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Travel-time field on network, minutes (empty = length / speed)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterNumber(
            self.SPEED, self.tr("Commute speed when no time field is given (km/h)"),
            QgsProcessingParameterNumber.Type.Double, 20.0, minValue=1.0, maxValue=150.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUDGET, self.tr("Commute-shed travel budget (minutes)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=1.0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, self.tr("Zones with jobs-housing balance")))

    def processAlgorithm(self, parameters, context, feedback):
        zones = self.parameterAsSource(parameters, self.ZONES, context)
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        jobs_f = self.parameterAsString(parameters, self.JOBS_FIELD, context)
        workers_f = self.parameterAsString(parameters, self.WORKERS_FIELD, context)
        worker_ratio = self.parameterAsDouble(parameters, self.WORKER_RATIO, context)
        cost_f = self.parameterAsString(parameters, self.COST_FIELD, context)
        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        budget = self.parameterAsDouble(parameters, self.BUDGET, context)
        self.require_projected(network, "Street network")
        crs = network.sourceCrs()

        graph, _polylines, _feats = self.network_graph(network, cost_f, use_prepared_costs=False)
        if cost_f:
            minutes = graph.adj_cost.copy()
        else:
            per_unit = _units.GroundUnits(crs, context.transformContext()).scale(network.sourceExtent())
            minutes = graph.adj_cost / per_unit / (speed * 1000.0 / 60.0)

        z_xy, z_feats = self.source_points(zones, crs, context.transformContext())
        z_nodes = graphs.nearest_nodes(graph, z_xy)
        ji = zones.fields().lookupField(jobs_f)
        wi = zones.fields().lookupField(workers_f)

        def value(feature, index):
            try:
                out = float(feature.attributes()[index])
            except (TypeError, ValueError):
                return 0.0
            return out if np.isfinite(out) and out > 0 else 0.0

        jobs = np.asarray([value(f, ji) for f in z_feats])
        workers = np.asarray([value(f, wi) for f in z_feats]) * worker_ratio
        if jobs.sum() <= 0 or workers.sum() <= 0:
            raise QgsProcessingException(
                "The zones carry no jobs or no workers - there is no balance to measure.")

        uniq, inverse = np.unique(z_nodes, return_inverse=True)
        dist = paths.many_to_many(graph.indptr, graph.adj_node, minutes, graph.num_nodes,
                                  uniq, cutoff=budget)
        # Zone i reaches zone j when j's node is within the budget of i's node.
        reach = np.isfinite(dist[inverse][:, z_nodes]) & (dist[inverse][:, z_nodes] <= budget)
        np.fill_diagonal(reach, True)
        jobs_shed, workers_shed = jobshousing.commute_shed(reach, jobs, workers)
        local_ratio = jobshousing.ratio(jobs, workers)
        local_bal = jobshousing.balance_index(jobs, workers)
        shed_ratio = jobshousing.ratio(jobs_shed, workers_shed)
        shed_bal = jobshousing.balance_index(jobs_shed, workers_shed)

        fields = self.make_fields(
            ("jh_jobs", DOUBLE), ("jh_workers", DOUBLE), ("jhr_local", DOUBLE),
            ("bal_local", DOUBLE), ("jobs_shed", DOUBLE), ("workers_shed", DOUBLE),
            ("jhr_shed", DOUBLE), ("bal_shed", DOUBLE), base=zones.fields())
        sink, dest = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, zones.wkbType(), zones.sourceCrs())
        nb = len(zones.fields())
        for i, feat in enumerate(z_feats):
            out = QgsFeature(fields)
            out.setGeometry(feat.geometry())
            out.setAttributes(list(feat.attributes())[:nb] + [
                _r(jobs[i], 3), _r(workers[i], 3), _r(local_ratio[i]), _r(local_bal[i]),
                _r(jobs_shed[i], 3), _r(workers_shed[i], 3), _r(shed_ratio[i]), _r(shed_bal[i])])
            sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)

        area_ratio = float(jobs.sum() / workers.sum())
        d = jobshousing.dissimilarity(jobs, workers)
        weights = workers / workers.sum()
        mean_bal = float(np.nansum(np.nan_to_num(shed_bal) * weights))
        feedback.pushInfo(self.tr(
            f"Area-wide: {jobs.sum():,.0f} jobs for {workers.sum():,.0f} workers "
            f"(ratio {area_ratio:.3f}); index of dissimilarity {d:.3f}; worker-weighted "
            f"mean commute-shed balance {mean_bal:.3f} within {budget:g} minutes; "
            f"mean shed reaches {reach.sum(axis=1).mean():.1f} of {len(z_feats)} zones."))
        return {self.OUTPUT: dest}

    def createInstance(self):
        return JobsHousingBalanceAlgorithm()
