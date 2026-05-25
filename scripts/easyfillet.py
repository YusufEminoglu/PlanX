# -*- coding: utf-8 -*-
"""
EasyFillet script for PlanX
Runs a fillet operation between two selected line features using a radius dialog and map tool.
"""
import os
import math
from qgis.PyQt.QtCore import Qt, QPointF
from qgis.PyQt.QtGui import QCursor, QPixmap, QColor, QPainter, QPen, QBrush
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (
    QgsFeature, QgsGeometry, QgsPointXY, QgsWkbTypes, Qgis
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand
from qgis.utils import iface

# Import the dialog
from .easyfillet_dialog import EasyFilletDialog

# Menu label that PlanX loader uses
MENU_LABEL = "Easy Fillet"

class FilletMapTool(QgsMapToolEmitPoint):
    def __init__(self, iface, tool):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.tool = tool
        self.selected_feature = None
        self.selected_node = None  # (QgsPointXY, feature)
        self.selected_node_index = None  # 0 or -1
        self.target_node = None    # (QgsPointXY, feature or None)
        self.preview_band = None
        self.first_band = None
        self.node_marker = None
        self.target_marker = None
        self.radius = tool.radius
        self.snapping_utils = self.canvas.snappingUtils()
        self.mode = 'fillet'
        self._set_cursor('fillet')

    def _set_cursor(self, mode):
        size = 32
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        if mode == 'extend':
            pen = QPen(QColor('#876582'))
            brush = QColor('#876582')
            brush.setAlphaF(0.1)
        else:
            pen = QPen(QColor('#3ad6a1'))
            brush = QColor('#f0c2d3')
            brush.setAlphaF(0.1)
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(brush)
        painter.drawEllipse(4, 4, size-8, size-8)
        painter.end()
        self.setCursor(QCursor(pixmap))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            from .easyfillet_dialog import EasyFilletDialog
            dlg = EasyFilletDialog(self.iface.mainWindow())
            dlg.radiusLineEdit.setText(str(self.radius))
            if dlg.exec():
                try:
                    val = float(dlg.radiusLineEdit.text())
                    if val > 0:
                        self.radius = val
                        self.tool.radius = val
                except Exception:
                    pass  # Ignore invalid input
        else:
            super().keyPressEvent(event)

    def reset(self):
        self.selected_feature = None
        self.selected_node = None
        self.selected_node_index = None
        self.target_node = None
        if self.preview_band:
            self.canvas.scene().removeItem(self.preview_band)
        if self.first_band:
            self.canvas.scene().removeItem(self.first_band)
        if self.node_marker:
            self.canvas.scene().removeItem(self.node_marker)
        if self.target_marker:
            self.canvas.scene().removeItem(self.target_marker)
        self.preview_band = None
        self.first_band = None
        self.node_marker = None
        self.target_marker = None
        self.canvas.setFocus()

    def canvasPressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            if self.mode == 'extend':
                self.mode = 'fillet'
                self._set_cursor('fillet')
                iface.messageBar().pushMessage('Fillet Mode', '', Qgis.Info, 2)
                self.reset()
                return
            else:
                self.mode = 'extend'
                self._set_cursor('extend')
                iface.messageBar().pushMessage('Extend Mode', '', Qgis.Info, 2)
                self.reset()
                return
        elif event.button() == Qt.MouseButton.LeftButton and self.mode == 'extend':
            layer = self.iface.activeLayer()
            if not layer or layer.geometryType() != QgsWkbTypes.LineGeometry:
                return
            pt = self.toMapCoordinates(event.pos())
            snap = self.snapping_utils.snapToMap(event.pos())
            if snap.isValid():
                pt = snap.point()
            if not self.selected_node:
                # First click: select the nearest endpoint of the nearest line
                feat = self.tool.find_nearest_line_feature(layer, pt)
                if not feat:
                    return
                geom = self.tool.get_single_line_geometry(feat.geometry())
                if not geom:
                    return
                d0 = QgsPointXY(geom[0]).distance(pt)
                d1 = QgsPointXY(geom[-1]).distance(pt)
                tol = self.canvas.mapUnitsPerPixel() * 10
                if d0 < d1 and d0 < tol:
                    node = QgsPointXY(geom[0])
                    node_index = 0
                elif d1 < tol:
                    node = QgsPointXY(geom[-1])
                    node_index = -1
                else:
                    return  # Only allow endpoint selection
                self.selected_feature = feat
                self.selected_node = (node, feat)
                self.selected_node_index = node_index
                # Highlight selected node
                if self.node_marker:
                    self.canvas.scene().removeItem(self.node_marker)
                self.node_marker = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
                self.node_marker.setToGeometry(QgsGeometry.fromPointXY(node), layer)
                self.node_marker.setColor(Qt.GlobalColor.green)
                self.node_marker.setWidth(10)
                # Highlight the line
                if self.first_band:
                    self.canvas.scene().removeItem(self.first_band)
                self.first_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
                self.first_band.setToGeometry(QgsGeometry.fromPolylineXY(geom), layer)
                self.first_band.setColor(Qt.GlobalColor.blue)
                self.first_band.setWidth(3)
            else:
                # Second click: select target node or location
                target_feat = self.tool.find_nearest_line_feature(layer, pt, exclude_fid=self.selected_feature.id())
                target_node = None
                tol = self.canvas.mapUnitsPerPixel() * 30
                if target_feat:
                    geom = self.tool.get_single_line_geometry(target_feat.geometry())
                    if geom:
                        d0 = QgsPointXY(geom[0]).distance(pt)
                        d1 = QgsPointXY(geom[-1]).distance(pt)
                        if d0 < d1 and d0 < tol:
                            target_node = QgsPointXY(geom[0])
                        elif d1 < tol:
                            target_node = QgsPointXY(geom[-1])
                if not target_node:
                    target_node = pt
                self.target_node = (target_node, target_feat)
                # Highlight target node
                if self.target_marker:
                    self.canvas.scene().removeItem(self.target_marker)
                self.target_marker = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
                self.target_marker.setToGeometry(QgsGeometry.fromPointXY(target_node), layer)
                self.target_marker.setColor(Qt.GlobalColor.red)
                self.target_marker.setWidth(10)
                # Always use the highlighted/selected node as the start of the new line
                node, feat = self.selected_node
                start_point = QgsPointXY(node)
                end_point = QgsPointXY(target_node)
                new_geom = QgsGeometry.fromPolylineXY([start_point, end_point])
                self.tool.add_feature(layer, new_geom, feat)
                layer.triggerRepaint()
                self.reset()
            return
        # Default: fillet mode logic
        if self.mode == 'fillet':
            self._set_cursor('fillet')
            layer = self.iface.activeLayer()
            if not layer or layer.geometryType() != QgsWkbTypes.LineGeometry:
                return
            pt = self.toMapCoordinates(event.pos())
            snap = self.snapping_utils.snapToMap(event.pos())
            if snap.isValid():
                pt = snap.point()
            feat = self.tool.find_nearest_line_feature(layer, pt)
            if not feat:
                return
            if not self.selected_feature:
                self.selected_feature = feat
                if self.first_band:
                    self.canvas.scene().removeItem(self.first_band)
                self.first_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
                geom = QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(feat.geometry()))
                self.first_band.setToGeometry(geom, layer)
                self.first_band.setColor(Qt.GlobalColor.blue)
                self.first_band.setWidth(3)
            else:
                if not layer.isEditable():
                    QMessageBox.warning(self.iface.mainWindow(), "Easy Fillet", "Layer must be in editing mode.")
                    return
                geom1 = QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(self.selected_feature.geometry()))
                geom2 = QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(feat.geometry()))
                result = self.tool.create_fillet_with_trim(geom1, geom2, self.radius)
                if not result:
                    QMessageBox.warning(self.iface.mainWindow(), "Easy Fillet", "Could not create fillet (parallel or too far)." )
                    return
                arc, tp1, tp2 = result['arc'], result['tp1'], result['tp2']
                trimmed1 = self.tool.trim_line_to_point(geom1, tp1)
                trimmed2 = self.tool.trim_line_to_point(geom2, tp2)
                self.tool.add_feature(layer, arc, self.selected_feature)
                self.tool.add_feature(layer, trimmed1, self.selected_feature)
                self.tool.add_feature(layer, trimmed2, feat)
                layer.triggerRepaint()
                self.reset()

    def canvasMoveEvent(self, event):
        if self.mode == 'extend' and self.selected_node:
            layer = self.iface.activeLayer()
            if not layer or layer.geometryType() != QgsWkbTypes.LineGeometry:
                return
            pt = self.toMapCoordinates(event.pos())
            snap = self.snapping_utils.snapToMap(event.pos())
            if snap.isValid():
                pt = snap.point()
            # Try to snap to a node of another line
            target_feat = self.tool.find_nearest_line_feature(layer, pt, exclude_fid=self.selected_feature.id())
            target_node = None
            tol = self.canvas.mapUnitsPerPixel() * 30
            if target_feat:
                geom = self.tool.get_single_line_geometry(target_feat.geometry())
                if geom:
                    d0 = QgsPointXY(geom[0]).distance(pt)
                    d1 = QgsPointXY(geom[-1]).distance(pt)
                    if d0 < d1 and d0 < tol:
                        target_node = QgsPointXY(geom[0])
                    elif d1 < tol:
                        target_node = QgsPointXY(geom[-1])
            if not target_node:
                target_node = pt
            # Preview extension
            node, feat = self.selected_node
            node_index = self.selected_node_index
            result = self.tool.extend_line_to_point(QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(feat.geometry())), node_index, target_node)
            if self.preview_band:
                self.canvas.scene().removeItem(self.preview_band)
                self.preview_band = None
            if result:
                self.preview_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
                self.preview_band.setToGeometry(result['extended'], layer)
                self.preview_band.setColor(Qt.GlobalColor.red)
                self.preview_band.setWidth(3)
            # Highlight target node
            if self.target_marker:
                self.canvas.scene().removeItem(self.target_marker)
                self.target_marker = None
            self.target_marker = QgsRubberBand(self.canvas, QgsWkbTypes.PointGeometry)
            self.target_marker.setToGeometry(QgsGeometry.fromPointXY(target_node), layer)
            self.target_marker.setColor(Qt.GlobalColor.red)
            self.target_marker.setWidth(10)
        else:
            if self.mode == 'fillet':
                self._set_cursor('fillet')
            if not self.selected_feature:
                return
            layer = self.iface.activeLayer()
            if not layer or layer.geometryType() != QgsWkbTypes.LineGeometry:
                return
            pt = self.toMapCoordinates(event.pos())
            snap = self.snapping_utils.snapToMap(event.pos())
            if snap.isValid():
                pt = snap.point()
            feat = self.tool.find_nearest_line_feature(layer, pt, exclude_fid=self.selected_feature.id())
            if self.preview_band:
                self.canvas.scene().removeItem(self.preview_band)
                self.preview_band = None
            if not feat:
                return
            result = self.tool.create_fillet_with_trim(
                QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(self.selected_feature.geometry())),
                QgsGeometry.fromPolylineXY(self.tool.get_single_line_geometry(feat.geometry())),
                self.radius
            )
            if result:
                arc = result['arc']
                self.preview_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
                self.preview_band.setToGeometry(arc, layer)
                self.preview_band.setColor(Qt.GlobalColor.red)
                self.preview_band.setWidth(3)

class EasyFilletTool:
    def __init__(self, iface):
        self.iface = iface
        self.map_tool = None
        self.radius = 5.0  # Default radius is now 5.0

    def find_nearest_line_feature(self, layer, point, exclude_fid=None):
        min_dist = float('inf')
        nearest = None
        for feat in layer.getFeatures():
            if exclude_fid is not None and feat.id() == exclude_fid:
                continue
            geom = self.get_single_line_geometry(feat.geometry())
            if not geom:
                continue
            d = QgsGeometry.fromPolylineXY(geom).distance(QgsGeometry.fromPointXY(point))
            if d < min_dist:
                min_dist = d
                nearest = feat
        return nearest

    def get_single_line_geometry(self, geom):
        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            return parts[0] if parts and parts[0] else []
        pts = geom.asPolyline()
        return pts if pts else []

    def create_fillet_with_trim(self, geom1, geom2, radius):
        # Computes fillet arc and trim points
        from .easyfillet_logic import create_fillet_and_trims  # user-provided logic file
        return create_fillet_and_trims(geom1, geom2, radius)

    def trim_line_to_point(self, geom, pt):
        from .easyfillet_logic import trim_line_to_point  # user-provided logic file
        return trim_line_to_point(geom, pt)

    def add_feature(self, layer, geom, source_feat):
        feat = QgsFeature(layer.fields())
        feat.setGeometry(geom)
        # Copy all attributes except 'fid'
        field_names = [field.name() for field in layer.fields()]
        try:
            fid_index = field_names.index('fid')
        except ValueError:
            fid_index = None
        source_attrs = source_feat.attributes()
        new_attrs = []
        for i, val in enumerate(source_attrs):
            if i == fid_index:
                new_attrs.append(None)  # Let QGIS assign a new fid
            else:
                new_attrs.append(val)
        feat.setAttributes(new_attrs)
        layer.addFeature(feat)

    def extend_line_to_point(self, geom, node_index, to_node):
        # Extend the line from the user-selected endpoint (node_index) to to_node
        pts = geom.asPolyline() if not geom.isMultipart() else geom.asMultiPolyline()[0]
        if len(pts) < 2:
            return None
        if node_index == 0:
            new_pts = [to_node] + pts[1:]
        elif node_index == -1:
            new_pts = pts[:-1] + [to_node]
        else:
            return None
        return {'extended': QgsGeometry.fromPolylineXY(new_pts)}

    def run(self):
        dlg = EasyFilletDialog(iface.mainWindow())
        dlg.radiusLineEdit.setText(str(self.radius))
        if not dlg.exec():
            return
        try:
            val = float(dlg.radiusLineEdit.text())
            if val <= 0:
                raise ValueError
            self.radius = val
        except Exception:
            QMessageBox.warning(iface.mainWindow(), "Easy Fillet", "Invalid radius.")
            return
        if not self.map_tool:
            self.map_tool = FilletMapTool(self.iface, self)
        self.map_tool.radius = self.radius
        self.map_tool.reset()
        iface.mapCanvas().setMapTool(self.map_tool)
        iface.mapCanvas().setFocus()  # Ensure canvas has focus for key events

# Singleton instance
_tool = None

def run_tool():
    """Called by PlanX to activate the Easy Fillet tool."""
    global _tool
    if _tool is None:
        _tool = EasyFilletTool(iface)
    _tool.run()
