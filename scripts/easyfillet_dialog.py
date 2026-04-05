from qgis.PyQt.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton

class EasyFilletDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fillet Radius")
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Enter fillet radius:"))
        self.radiusLineEdit = QLineEdit()
        self.radiusLineEdit.setPlaceholderText("Radius (map units)")
        self.radiusLineEdit.setText("5")  # Default radius is now 5.0
        layout.addWidget(self.radiusLineEdit)
        btn = QPushButton("OK")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
        self.setLayout(layout)
