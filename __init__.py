# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PlanX
                                 A QGIS plugin
 Comprehensive suite of spatial‐planning tools for data import,
 advanced spatial statistics, zoning-rule workflows, and urban-design analyses.
                              -------------------
        begin                : 2025-05-07
        copyright            : (C) 2025 by Yusuf Eminoglu
        email                : yusuf.emnglu@gmail.com
        repository           : https://github.com/YusufEminoglu/PlanX
 ***************************************************************************/
"""

def classFactory(iface):
    """
    QGIS calls this factory function to instantiate your plugin.
    
    :param iface: A QGIS interface instance.
    :returns: Instance of PlanX.
    """
    from .planx import PlanX
    return PlanX(iface)
