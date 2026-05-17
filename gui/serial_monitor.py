# gui/serial_monitor.py
"""Serial monitor dialog."""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton
from PyQt6.QtGui import QTextCursor


class SerialMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Port Monitor")
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        rx_label = QLabel("Received (Rx):")
        self.rx_edit = QTextEdit()
        self.rx_edit.setReadOnly(True)

        self.clear_rx_btn = QPushButton("Clear Rx")
        self.clear_rx_btn.clicked.connect(self.rx_edit.clear)

        rx_layout = QHBoxLayout()
        rx_layout.addWidget(self.rx_edit)
        rx_layout.addWidget(self.clear_rx_btn)

        tx_label = QLabel("Transmitted (Tx):")
        self.tx_edit = QTextEdit()
        self.tx_edit.setReadOnly(True)

        self.clear_tx_btn = QPushButton("Clear Tx")
        self.clear_tx_btn.clicked.connect(self.tx_edit.clear)

        tx_layout = QHBoxLayout()
        tx_layout.addWidget(self.tx_edit)
        tx_layout.addWidget(self.clear_tx_btn)

        layout.addWidget(rx_label)
        layout.addLayout(rx_layout)
        layout.addWidget(tx_label)
        layout.addLayout(tx_layout)

        self.setLayout(layout)

    def append_rx(self, text: str):
        """Append text to the Rx text edit and auto-scroll."""
        self.rx_edit.append(text)
        self.rx_edit.moveCursor(QTextCursor.MoveOperation.End)

    def append_tx(self, text: str):
        """Append text to the Tx text edit and auto-scroll."""
        self.tx_edit.append(text)
        self.tx_edit.moveCursor(QTextCursor.MoveOperation.End)
