"""Responsive chip group for compact status and capability tags."""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

from .status_chip import StatusChip


class ChipGroupWidget(QWidget):
    """Render a lightweight group of chips in a small responsive grid."""

    def __init__(self, chips: list[tuple[str, str]], columns: int = 3) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        for index, (text, tone) in enumerate(chips):
            layout.addWidget(StatusChip(text, tone), index // columns, index % columns)

        for column in range(columns):
            layout.setColumnStretch(column, 0)
        layout.setColumnStretch(columns, 1)
