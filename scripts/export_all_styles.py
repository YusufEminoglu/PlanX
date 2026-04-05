import os
import shutil
from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

MENU_LABEL = "Export All Styles"

def run_tool():
    # Path to the styles folder in the plugin
    plugin_dir = os.path.dirname(os.path.dirname(__file__))
    styles_dir = os.path.join(plugin_dir, 'styles')

    if not os.path.exists(styles_dir):
        QMessageBox.warning(None, "Export Styles", "Styles folder not found!")
        return

    # Ask user where to save the styles
    out_dir = QFileDialog.getExistingDirectory(
        None,
        "Select Folder to Export All Styles"
    )
    if out_dir:
        try:
            count = 0
            for fname in os.listdir(styles_dir):
                src_path = os.path.join(styles_dir, fname)
                dst_path = os.path.join(out_dir, fname)
                if os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
                    count += 1
            QMessageBox.information(None, "Export Styles", f"Exported {count} style file(s) to:\n{out_dir}")
        except Exception as e:
            QMessageBox.critical(None, "Export Styles", f"Failed to export styles:\n{e}") 