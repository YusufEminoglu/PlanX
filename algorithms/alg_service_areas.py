# -*- coding: utf-8 -*-
"""Service Areas (Isochrones): exact network catchments vs straight-line radii."""
from __future__ import annotations

import numpy as np

from qgis.core import (
    QgsFeature,
    QgsFeatureSink,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingException,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFeatureSink,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsSpatialIndex,
    QgsWkbTypes,
)

from .base import DOUBLE, GROUP_NETWORK, INT, STRING, PlanXAlgorithm
from ..engine import graphs, isochrone, paths

ALL_LABEL = "ALL"


def parse_breaks(text: str):
    vals = sorted({float(t) for t in text.replace(";", ",").split(",") if t.strip()})
    if not vals or any(v <= 0 for v in vals):
        raise QgsProcessingException(
            "Breaks must be a comma-separated list of positive numbers, e.g. 250, 500, 1000")
    return vals


class ServiceAreasAlgorithm(PlanXAlgorithm):
    GROUP = GROUP_NETWORK
    ICON = "tool_serviceareas.png"
    NETWORK = "NETWORK"
    FACILITIES = "FACILITIES"
    FACILITY_ID = "FACILITY_ID"
    COST_FIELD = "COST_FIELD"
    BREAKS = "BREAKS"
    COMBINE = "COMBINE"
    METHOD = "METHOD"
    BUFFER = "BUFFER"
    HULL_DETAIL = "HULL_DETAIL"
    RINGS = "RINGS"
    EDGES = "EDGES"
    AREAS = "AREAS"
    CIRCLES = "CIRCLES"
    SUMMARY = "SUMMARY"

    def name(self):
        return "serviceareas"

    def displayName(self):
        return self.tr("Service Areas (Isochrones)")

    def shortHelpString(self):
        return self.tr(
            "True network catchments around facilities, computed by the "
            "embedded Dijkstra engine with EXACT partial-edge reach: walking "
            "budgets end mid-street, so streets are trimmed at the precise "
            "point where the budget runs out (older buffer-only service "
            "areas keep or drop whole segments and overshoot by up to a "
            "full block). Facilities enter the network at the nearest point "
            "of the nearest street - not the nearest junction - and, when "
            "cost is length, the straight-line approach distance is added "
            "to the budget.\n\n"
            "For every break the tool also draws the straight-line circle "
            "of the same distance (the 'desired reach' radius that "
            "regulations and standards prescribe, e.g. a 500 m school "
            "catchment) and reports the PEDSHED RATIO = network catchment "
            "area / circle area - the classic measure of how much the "
            "street layout shrinks the reach promised by the radius.\n\n"
            "Polygon methods: Street buffer hugs the trimmed streets "
            "(cartographic, precise); Concave hull gives the familiar "
            "isochrone blob; Convex hull is the fastest, most generous "
            "envelope. 'Per facility + merged' adds one catchment, circle "
            "and summary row per facility (facility label from the "
            "optional ID field); the merged scope (label ALL) always uses "
            "the nearest facility for every street. Cost defaults to "
            "length in map units; pass a numeric field (e.g. minutes) to "
            "use travel time and express breaks in that unit (circles then "
            "read breaks as map units and pedshed loses meaning).\n\n"
            "How to read the results\n"
            "- Areas: the real service coverage. Gaps between the circle "
            "and the catchment are streets that LOOK close but are not "
            "reachable - severance by rivers, highways, superblocks or "
            "missing links.\n"
            "- pedshed (summary): >= 0.6 is a well-connected, walkable "
            "grid; 0.4-0.6 average; < 0.4 poor - the network delivers "
            "less than half of the promised radius. Compare facilities to "
            "rank retrofit priorities.\n"
            "- Edges: streets classified by cost band - style line colour "
            "by 'band' for a served-street map; len_m sums to the reached "
            "street length in the summary.\n"
            "- Circles vs areas overlay: the strongest single exhibit for "
            "a standards review - it shows exactly where the paper radius "
            "of a school, park or clinic fails on the ground.\n\n"
            "Using the results: site new facilities where catchments leave "
            "gaps; justify pedestrian bridges / street connections by the "
            "pedshed gain they produce (rerun with the proposed link and "
            "compare); use Rings for clean band cartography. Run 'Prepare "
            "Network' first so crossing lines share junctions."
        )

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.NETWORK, self.tr("Street network (lines)"), [QgsProcessing.SourceType.TypeVectorLine]))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.FACILITIES, self.tr("Facilities"), [QgsProcessing.SourceType.TypeVectorAnyGeometry]))
        self.addParameter(QgsProcessingParameterField(
            self.FACILITY_ID, self.tr("Facility label field (optional)"),
            parentLayerParameterName=self.FACILITIES, optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.COST_FIELD, self.tr("Cost field on network (empty = length)"),
            parentLayerParameterName=self.NETWORK, optional=True,
            type=QgsProcessingParameterField.DataType.Numeric))
        self.addParameter(QgsProcessingParameterString(
            self.BREAKS,
            self.tr("Catchment distances / cost breaks (comma separated)"),
            "250, 500, 1000"))
        self.addParameter(QgsProcessingParameterEnum(
            self.COMBINE, self.tr("Catchments"),
            options=[self.tr("Merged only (nearest facility wins)"),
                     self.tr("Per facility + merged")],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterEnum(
            self.METHOD, self.tr("Polygon method"),
            options=[self.tr("Street buffer (hug the network)"),
                     self.tr("Concave hull (isochrone blob)"),
                     self.tr("Convex hull (generous envelope)")],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.BUFFER, self.tr("Street buffer width (map units)"),
            QgsProcessingParameterNumber.Type.Double, 30.0, minValue=0.1))
        self.addParameter(QgsProcessingParameterNumber(
            self.HULL_DETAIL,
            self.tr("Concave hull detail (0 = tight, 1 = convex)"),
            QgsProcessingParameterNumber.Type.Double, 0.3,
            minValue=0.01, maxValue=1.0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.RINGS, self.tr("Output bands as rings (differences)"), False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.EDGES, self.tr("Reached streets (trimmed, by band)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.AREAS, self.tr("Service area polygons (isochrones)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.CIRCLES, self.tr("Straight-line catchments (circles)")))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SUMMARY, self.tr("Catchment summary (pedshed)"),
            type=QgsProcessing.SourceType.TypeVector))

    # ------------------------------------------------------------------ #
    @staticmethod
    def _snap_to_edge(pt_xy, polylines, edge_geoms, index):
        """Nearest point on the nearest edge: (edge, t, snap_dist)."""
        pt = QgsPointXY(float(pt_xy[0]), float(pt_xy[1]))
        cand = index.nearestNeighbor(pt, 5)
        if not cand:
            cand = range(len(edge_geoms))
        best = (None, 0.0, float("inf"))
        for e in cand:
            sqr_d, min_pt, after, _ = edge_geoms[e].closestSegmentWithContext(pt)
            if sqr_d < best[2]:
                coords = polylines[e]
                seg = np.diff(coords, axis=0)
                cum = np.concatenate([[0.0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
                total = cum[-1]
                arc = cum[max(after - 1, 0)] + float(
                    np.hypot(min_pt.x() - coords[max(after - 1, 0)][0],
                             min_pt.y() - coords[max(after - 1, 0)][1]))
                t = 0.0 if total <= 0 else min(max(arc / total, 0.0), 1.0)
                best = (int(e), float(t), float(sqr_d))
        return best[0], best[1], float(np.sqrt(best[2]))

    @staticmethod
    def _hull(points_xy, method, detail):
        """Concave/convex hull polygon of a point cloud (QgsPointXY list)."""
        if len(points_xy) < 3:
            return None
        mp = QgsGeometry.fromMultiPointXY(points_xy)
        if method == 1:
            try:
                hull = mp.concaveHull(float(detail), False)
                if hull is not None and not hull.isNull() and not hull.isEmpty():
                    return hull
            except (AttributeError, TypeError):
                pass
        hull = mp.convexHull()
        return None if hull is None or hull.isNull() or hull.isEmpty() else hull

    def processAlgorithm(self, parameters, context, feedback):
        network = self.parameterAsSource(parameters, self.NETWORK, context)
        facilities = self.parameterAsSource(parameters, self.FACILITIES, context)
        fac_id = self.parameterAsString(parameters, self.FACILITY_ID, context)
        cost_field = self.parameterAsString(parameters, self.COST_FIELD, context)
        breaks = parse_breaks(self.parameterAsString(parameters, self.BREAKS, context))
        per_facility = self.parameterAsEnum(parameters, self.COMBINE, context) == 1
        method = self.parameterAsEnum(parameters, self.METHOD, context)
        buffer_w = self.parameterAsDouble(parameters, self.BUFFER, context)
        hull_detail = self.parameterAsDouble(parameters, self.HULL_DETAIL, context)
        rings = self.parameterAsBoolean(parameters, self.RINGS, context)
        self.require_projected(network, "Street network")

        polylines, line_feats = self.source_polylines(network)
        costs = None
        if cost_field:
            idx = network.fields().lookupField(cost_field)
            costs = [float(f.attributes()[idx] or 0.0) for f in line_feats]
        cost_is_length = not cost_field
        graph = graphs.build_node_graph(polylines, costs=costs)
        crs = network.sourceCrs()
        f_xy, f_feats = self.source_points(facilities, crs, context.transformContext())
        n_fac = len(f_xy)
        labels = []
        seen = {}
        id_idx = facilities.fields().lookupField(fac_id) if fac_id else -1
        for i, f in enumerate(f_feats):
            if id_idx >= 0:
                v = f.attributes()[id_idx]
                lab = str(v) if v is not None else str(i)
            else:
                lab = str(i)
            if lab in seen or lab == ALL_LABEL:
                seen[lab] = seen.get(lab, 1) + 1
                lab = f"{lab} ({seen[lab]})"
            seen.setdefault(lab, 1)
            labels.append(lab)

        # --- snap every facility to the nearest point of the nearest edge
        edge_geoms = []
        sp_index = QgsSpatialIndex()
        for e, arr in enumerate(polylines):
            g = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in arr])
            edge_geoms.append(g)
            qf = QgsFeature(e)
            qf.setGeometry(g)
            sp_index.addFeature(qf)

        max_break = breaks[-1]
        entries = []       # per facility: (edge, t, snap_cost_for_budget)
        node_src = []      # 2 node entries per facility
        node_off = []
        snaps = []
        far = 0
        for i in range(n_fac):
            e, t, snap = self._snap_to_edge(f_xy[i], polylines, edge_geoms, sp_index)
            if e is None:
                raise QgsProcessingException("Could not snap facilities to the network.")
            snap_cost = snap if cost_is_length else 0.0
            entries.append((e, t, snap_cost))
            snaps.append(snap)
            c = float(graph.edge_cost[e])
            node_src.extend([int(graph.edge_from[e]), int(graph.edge_to[e])])
            node_off.extend([snap_cost + t * c, snap_cost + (1.0 - t) * c])
            if snap_cost >= max_break:
                far += 1
        if far:
            feedback.pushWarning(self.tr(
                f"{far} facilities lie farther from the network than the "
                f"largest break - their catchments are empty."))
        feedback.pushInfo(self.tr(
            f"Graph: {graph.num_nodes} nodes / {graph.num_edges} edges; "
            f"{n_fac} facilities snapped onto the nearest street "
            f"(max snap distance {max(snaps):.1f} map units)."))

        # --- scopes: merged always; per-facility when requested
        node_src_a = np.asarray(node_src, dtype=np.int64)
        node_off_a = np.asarray(node_off, dtype=np.float64)
        dist_all, label_all = paths.multi_source_offset(
            graph.indptr, graph.adj_node, graph.adj_cost, graph.num_nodes,
            node_src_a, node_off_a, cutoff=max_break)
        scopes = [(ALL_LABEL, dist_all, entries, None)]
        if per_facility:
            for i in range(n_fac):
                if feedback.isCanceled():
                    break
                d_i, _ = paths.multi_source_offset(
                    graph.indptr, graph.adj_node, graph.adj_cost, graph.num_nodes,
                    node_src_a[2 * i:2 * i + 2], node_off_a[2 * i:2 * i + 2],
                    cutoff=max_break)
                scopes.append((labels[i], d_i, [entries[i]], i))
                feedback.setProgress(int(30.0 * (i + 1) / n_fac))

        # --- reach intervals per scope per break (cumulative)
        reach = {}  # (scope_label, break) -> {edge: intervals}
        for si, (lab, dist, ent, _fi) in enumerate(scopes):
            for brk in breaks:
                if feedback.isCanceled():
                    break
                reach[(lab, brk)] = isochrone.reach_intervals(
                    dist, graph.edge_from, graph.edge_to, graph.edge_cost,
                    brk, entries=ent)
            feedback.setProgress(30 + int(30.0 * (si + 1) / len(scopes)))

        def pieces_geoms(lab, brk):
            out = []
            for e, iv in reach.get((lab, brk), {}).items():
                for lo, hi in iv:
                    arr = isochrone.cut_polyline(polylines[e], lo, hi)
                    if arr is not None:
                        out.append(QgsGeometry.fromPolylineXY(
                            [QgsPointXY(x, y) for x, y in arr]))
            return out

        def street_len(lab, brk):
            return float(sum(
                isochrone.interval_length(iv) * float(graph.edge_len[e])
                for e, iv in reach.get((lab, brk), {}).items()))

        # --- EDGES: merged scope, split into cost bands
        edge_fields = self.make_fields(
            ("facility", STRING), ("band", DOUBLE), ("cost_from", DOUBLE),
            ("len_m", DOUBLE), base=network.fields())
        edge_sink, edges_dest = self.parameterAsSink(
            parameters, self.EDGES, context, edge_fields,
            QgsWkbTypes.Type.LineString, crs)
        n_src_fields = len(network.fields())
        n_pieces = 0
        for bi, brk in enumerate(breaks):
            prev = breaks[bi - 1] if bi else None
            cur = reach.get((ALL_LABEL, brk), {})
            for e, iv in cur.items():
                band_iv = iv if prev is None else isochrone.subtract_intervals(
                    iv, reach[(ALL_LABEL, prev)].get(e, []))
                for lo, hi in band_iv:
                    arr = isochrone.cut_polyline(polylines[e], lo, hi)
                    if arr is None:
                        continue
                    da = float(dist_all[graph.edge_from[e]])
                    db = float(dist_all[graph.edge_to[e]])
                    win = label_all[graph.edge_from[e] if da <= db else graph.edge_to[e]]
                    fac_lab = labels[int(win) // 2] if win >= 0 else ""
                    piece_len = float(graph.edge_len[e]) * (hi - lo)
                    out = QgsFeature(edge_fields)
                    out.setGeometry(QgsGeometry.fromPolylineXY(
                        [QgsPointXY(x, y) for x, y in arr]))
                    out.setAttributes(
                        list(line_feats[e].attributes())[:n_src_fields]
                        + [fac_lab, float(brk), float(prev or 0.0), piece_len])
                    edge_sink.addFeature(out, QgsFeatureSink.Flag.FastInsert)
                    n_pieces += 1
        feedback.pushInfo(self.tr(f"Reached street pieces: {n_pieces}."))
        feedback.setProgress(70)

        # --- AREAS per scope per break
        area_fields = self.make_fields(
            ("facility", STRING), ("break", DOUBLE), ("rank", INT),
            ("area", DOUBLE))
        area_sink, areas_dest = self.parameterAsSink(
            parameters, self.AREAS, context, area_fields,
            QgsWkbTypes.Type.MultiPolygon, crs)
        warned_concave = False
        cum_area = {}  # (label, break) -> cumulative catchment area
        for lab, dist, ent, fi in scopes:
            prev_geom = None
            fac_pts = ([QgsPointXY(*f_xy[i]) for i in range(n_fac)]
                       if fi is None else [QgsPointXY(*f_xy[fi])])
            for bi, brk in enumerate(breaks):
                if feedback.isCanceled():
                    break
                pieces = pieces_geoms(lab, brk)
                geom = None
                if pieces:
                    if method == 0:
                        geom = QgsGeometry.unaryUnion(
                            [g.buffer(buffer_w, 8) for g in pieces])
                    else:
                        pts = list(fac_pts)
                        step = max(brk / 32.0, 1.0)
                        for g in pieces:
                            dense = g.densifyByDistance(step)
                            pts.extend(QgsPointXY(v.x(), v.y())
                                       for v in dense.vertices())
                        if method == 1 and not hasattr(QgsGeometry, "concaveHull") \
                                and not warned_concave:
                            feedback.pushWarning(self.tr(
                                "Concave hull is not available in this QGIS "
                                "build - falling back to convex hull."))
                            warned_concave = True
                        geom = self._hull(pts, method, hull_detail)
                if geom is None or geom.isEmpty():
                    cum_area[(lab, brk)] = 0.0
                    prev_geom = None
                    continue
                cum_area[(lab, brk)] = float(geom.area())
                out_geom = geom
                if rings and prev_geom is not None:
                    diff = geom.difference(prev_geom)
                    if diff is not None and not diff.isEmpty():
                        out_geom = diff
                f = QgsFeature(area_fields)
                f.setGeometry(out_geom)
                f.setAttributes([lab, float(brk), bi + 1, float(out_geom.area())])
                area_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
                prev_geom = geom
        feedback.setProgress(85)

        # --- CIRCLES: the straight-line 'desired reach' radii
        circle_fields = self.make_fields(
            ("facility", STRING), ("break", DOUBLE), ("area", DOUBLE))
        circle_sink, circles_dest = self.parameterAsSink(
            parameters, self.CIRCLES, context, circle_fields,
            QgsWkbTypes.Type.MultiPolygon, crs)
        circle_area = {}  # (label, break) -> area
        for brk in breaks:
            discs = []
            for i in range(n_fac):
                disc = QgsGeometry.fromPointXY(
                    QgsPointXY(*f_xy[i])).buffer(brk, 64)
                discs.append(disc)
                circle_area[(labels[i], brk)] = float(disc.area())
                if per_facility:
                    f = QgsFeature(circle_fields)
                    f.setGeometry(disc)
                    f.setAttributes([labels[i], float(brk), float(disc.area())])
                    circle_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
            merged = QgsGeometry.unaryUnion(discs)
            circle_area[(ALL_LABEL, brk)] = float(merged.area())
            f = QgsFeature(circle_fields)
            f.setGeometry(merged)
            f.setAttributes([ALL_LABEL, float(brk), float(merged.area())])
            circle_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
        if not cost_is_length:
            feedback.pushInfo(self.tr(
                "Cost field in use: circles read the breaks as map-unit "
                "radii, so the pedshed ratio mixes units - interpret with "
                "care (or leave the cost field empty for distances)."))

        # --- SUMMARY: pedshed per scope per break
        sum_fields = self.make_fields(
            ("facility", STRING), ("break", DOUBLE), ("circle_area", DOUBLE),
            ("net_area", DOUBLE), ("pedshed", DOUBLE), ("street_len", DOUBLE))
        sum_sink, summary_dest = self.parameterAsSink(
            parameters, self.SUMMARY, context, sum_fields,
            QgsWkbTypes.Type.NoGeometry, crs)
        scope_labels = [lab for lab, _, _, _ in scopes]
        for lab in scope_labels:
            for brk in breaks:
                c_area = circle_area.get((lab, brk), 0.0)
                n_area = cum_area.get((lab, brk), 0.0)
                ratio = n_area / c_area if c_area > 0 else 0.0
                f = QgsFeature(sum_fields)
                f.setAttributes([lab, float(brk), c_area, n_area,
                                 float(ratio), street_len(lab, brk)])
                sum_sink.addFeature(f, QgsFeatureSink.Flag.FastInsert)
                if lab == ALL_LABEL:
                    feedback.pushInfo(self.tr(
                        f"Break {brk:g}: {street_len(lab, brk):.0f} map "
                        f"units of street reached, catchment "
                        f"{n_area:.0f}, pedshed {ratio:.2f}"))
        feedback.setProgress(100)

        return {self.EDGES: edges_dest, self.AREAS: areas_dest,
                self.CIRCLES: circles_dest, self.SUMMARY: summary_dest}

    def createInstance(self):
        return ServiceAreasAlgorithm()
