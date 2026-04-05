# -*- coding: utf-8 -*-
"""
Geometry utilities for EasyFillet sub-plugin in PlanX.
Provides functions to compute a fillet arc between two line geometries and to trim lines to tangent points.
"""
import math
from qgis.core import QgsGeometry, QgsPointXY


def line_intersection(p1, p2, p3, p4):
    """
    Return intersection point of two lines (p1-p2) and (p3-p4), or None if parallel.
    """
    x1, y1 = p1.x(), p1.y()
    x2, y2 = p2.x(), p2.y()
    x3, y3 = p3.x(), p3.y()
    x4, y4 = p4.x(), p4.y()
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-12:
        return None
    px = ((x1*y2 - y1*x2) * (x3 - x4) - (x1 - x2) * (x3*y4 - y3*x4)) / denom
    py = ((x1*y2 - y1*x2) * (y3 - y4) - (y1 - y2) * (x3*y4 - y3*x4)) / denom
    return QgsPointXY(px, py)


def create_fillet_and_trims(geom1, geom2, radius):
    """
    Compute a fillet arc between two QgsGeometry line segments.
    Returns dict with keys:
      'arc' : QgsGeometry (polyline of the circular arc),
      'tp1' : QgsPointXY (tangent point on line1),
      'tp2' : QgsPointXY (tangent point on line2)
    or None if fillet cannot be created.
    """
    # Extract point lists
    if geom1.isMultipart():
        pts1 = geom1.asMultiPolyline()[0]
    else:
        pts1 = geom1.asPolyline()
    if geom2.isMultipart():
        pts2 = geom2.asMultiPolyline()[0]
    else:
        pts2 = geom2.asPolyline()
    if len(pts1) < 2 or len(pts2) < 2:
        return None

    # Find intersection or estimate
    inter = geom1.intersection(geom2)
    if not inter.isEmpty():
        inter_pt = inter.asPoint()
    else:
        inter_pt = line_intersection(pts1[0], pts1[-1], pts2[0], pts2[-1])
        if inter_pt is None:
            return None

    # Unit direction vectors from intersection
    def unit_vec(a, b):
        dx, dy = b.x() - a.x(), b.y() - a.y()
        d = math.hypot(dx, dy)
        return (dx/d, dy/d) if d > 1e-12 else (0.0, 0.0)

    # Choose segment directions toward intersection
    i1 = 0 if QgsPointXY(pts1[0]).distance(inter_pt) < QgsPointXY(pts1[-1]).distance(inter_pt) else -1
    i2 = 0 if QgsPointXY(pts2[0]).distance(inter_pt) < QgsPointXY(pts2[-1]).distance(inter_pt) else -1
    v1 = unit_vec(inter_pt, pts1[i1])
    v2 = unit_vec(inter_pt, pts2[i2])

    # Check for parallel lines
    dot = v1[0]*v2[0] + v1[1]*v2[1]
    if abs(abs(dot) - 1.0) < 1e-6:
        return None

    # Angle between vectors
    angle = math.acos(max(-1.0, min(1.0, dot)))
    if abs(angle) < 1e-6:
        return None

    # Tangent length from intersection
    tan_len = radius / math.tan(angle/2)
    tp1 = QgsPointXY(inter_pt.x() + v1[0]*tan_len, inter_pt.y() + v1[1]*tan_len)
    tp2 = QgsPointXY(inter_pt.x() + v2[0]*tan_len, inter_pt.y() + v2[1]*tan_len)

    # Compute circle center
    bisec = math.atan2(v1[1] + v2[1], v1[0] + v2[0])
    center_dist = radius / math.sin(angle/2)
    center = QgsPointXY(inter_pt.x() + math.cos(bisec)*center_dist,
                        inter_pt.y() + math.sin(bisec)*center_dist)

    # Generate arc points
    def angle_of(p):
        return math.atan2(p.y() - center.y(), p.x() - center.x())
    a1 = angle_of(tp1)
    a2 = angle_of(tp2)
    if a2 < a1:
        a2 += 2*math.pi
    segments = 20
    arc_pts = [QgsPointXY(center.x() + radius*math.cos(a1 + (a2-a1)*i/segments),
                          center.y() + radius*math.sin(a1 + (a2-a1)*i/segments))
               for i in range(segments+1)]
    # Ensure arc endpoints are exactly tp1 and tp2
    arc_pts[0] = tp1
    arc_pts[-1] = tp2
    return {
        'arc': QgsGeometry.fromPolylineXY(arc_pts),
        'tp1': tp1,
        'tp2': tp2
    }


def trim_line_to_point(geom, pt):
    """
    Trim QgsGeometry line to the specified QgsPointXY on its endpoint.
    Returns a new QgsGeometry.
    """
    if geom.isMultipart():
        pts = geom.asMultiPolyline()[0]
    else:
        pts = geom.asPolyline()
    if len(pts) < 2:
        return geom

    d0 = QgsGeometry.fromPointXY(pts[0]).distance(QgsGeometry.fromPointXY(pt))
    d1 = QgsGeometry.fromPointXY(pts[-1]).distance(QgsGeometry.fromPointXY(pt))
    if d0 < d1:
        new_pts = [pt] + pts[1:]
        new_pts[0] = pt  # Ensure exact
    else:
        new_pts = pts[:-1] + [pt]
        new_pts[-1] = pt  # Ensure exact

    return QgsGeometry.fromPolylineXY(new_pts)
