"""Compact status list for alerts and checklists."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .effects import apply_card_shadow
from .status_chip import StatusChip


class StatusListWidget(QWidget):
    """Render a compact stack of rounded status rows."""

    def __init__(self, items: list[tuple[str, str]]) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        for text, tone in items:
            row = QFrame()
            row.setObjectName("StatusRow")
            apply_card_shadow(row, blur_radius=14, y_offset=4)

            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 9, 12, 9)
            row_layout.setSpacing(10)

            row_layout.addWidget(StatusChip(tone.upper(), tone))

            label = QLabel(text)
            label.setObjectName("StatusRowText")
            label.setWordWrap(True)
            row_layout.addWidget(label, 1)

            root.addWidget(row)
