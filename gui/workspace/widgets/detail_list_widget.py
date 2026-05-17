"""Widget for rendering compact label/value rows."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..models import DetailItem


class DetailListWidget(QWidget):
    """Renders detail items as light rounded summary rows."""

    def __init__(self, items: list[DetailItem]) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        for item in items:
            row = QFrame()
            row.setObjectName("DetailRow")

            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(12)

            label = QLabel(item.label)
            label.setObjectName("DetailLabel")
            row_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

            value = QLabel(item.value)
            value.setObjectName("DetailValue")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(True)
            value.setMinimumHeight(value.fontMetrics().lineSpacing())
            row_layout.addWidget(value, 1)

            root.addWidget(row)
