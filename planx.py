# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PlanX
     QGIS Plugin
 Comprehensive suite of spatial-planning tools under a unified menu,
 dynamically loading sub-plugins from the scripts folder.
***************************************************************************/
"""

import os
import importlib
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

class PlanX:
    """
    PlanX QGIS Plugin
    Dynamically loads all modules in the scripts folder as sub-plugins.
    """
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.menu = None
        self.actions = []
        self.providers = []

    def initGui(self):
        """Create the PlanX menu directly on the main menu bar."""
        # Load plugin icon
        icon_file = os.path.join(self.plugin_dir, 'icons', 'planx.png')
        menu_icon = QIcon(icon_file) if os.path.exists(icon_file) else QIcon()

        # Create PlanX menu on the main window's menu bar
        self.menu = QMenu('PlanX', self.iface.mainWindow().menuBar())
        self.menu.menuAction().setIcon(menu_icon)
        self.iface.mainWindow().menuBar().addMenu(self.menu)

        # Discover and load script modules
        scripts_dir = os.path.join(self.plugin_dir, 'scripts')
        for fname in sorted(os.listdir(scripts_dir)):
            if not fname.endswith('.py') or fname.startswith('_'):
                continue
            mod_name = fname[:-3]
            try:
                module = importlib.import_module(f'.scripts.{mod_name}', package='planx')

                # Prepare icon for the sub-plugin
                icon_path = os.path.join(self.plugin_dir, 'icons', f'{mod_name}.png')
                action_icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

                # Add QAction if module has run_tool()
                if hasattr(module, 'run_tool'):
                    label = getattr(module, 'MENU_LABEL', mod_name.replace('_', ' ').title())
                    action = QAction(action_icon, label, self.iface.mainWindow())
                    action.triggered.connect(module.run_tool)
                    self.menu.addAction(action)
                    self.actions.append(action)

                # Register processing provider if available
                if hasattr(module, 'provider'):
                    QgsApplication.processingRegistry().addProvider(module.provider)
                    self.providers.append(module.provider)

            except Exception as e:
                print(f"PlanX: failed to load '{mod_name}': {e}")

    def unload(self):
        """Clean up menu and processing providers."""
        if self.menu:
            self.iface.mainWindow().menuBar().removeAction(self.menu.menuAction())
        for action in self.actions:
            self.menu.removeAction(action)
        self.actions.clear()

        for prov in self.providers:
            QgsApplication.processingRegistry().removeProvider(prov)
        self.providers.clear()
