"""Simple switch-style list for settings-like panels."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class SwitchListWidget(QWidget):
    """Render rows of labels paired with rounded switch controls."""

    def __init__(self, items: list[tuple[str, bool]]) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        for label_text, checked in items:
            row = QFrame()
            row.setObjectName("SwitchRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 10, 14, 10)
            row_layout.setSpacing(10)

            label = QLabel(label_text)
            label.setObjectName("SwitchLabel")
            row_layout.addWidget(label, 1)

            toggle = QCheckBox()
            toggle.setObjectName("SwitchToggle")
            toggle.setTristate(False)
            toggle.setChecked(checked)
            toggle.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            row_layout.addWidget(toggle, 0, Qt.AlignmentFlag.AlignRight)

            root.addWidget(row)
