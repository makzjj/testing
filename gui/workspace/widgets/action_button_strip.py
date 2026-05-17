"""Button strip for section-level actions."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QPushButton, QWidget

from ..models import ActionItem


class ActionButtonStrip(QWidget):
    """Renders actions as a compact rounded button grid."""

    action_requested = pyqtSignal(str)

    def __init__(self, actions: list[ActionItem], columns: int = 2, primary_index: int = 0, show_hints: bool = False) -> None:
        super().__init__()
        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        for index, action in enumerate(actions):
            button = QPushButton(action.label)
            button.setObjectName("ActionButton")
            button.setProperty("tone", "primary" if index == primary_index else "secondary")
            if action.hint:
                button.setToolTip(action.hint)
            button.clicked.connect(lambda _checked=False, action_id=action.action_id: self.action_requested.emit(action_id))
            if show_hints:
                button.setProperty("showHints", True)
            root.addWidget(button, index // columns, index % columns)

        for column in range(columns):
            root.setColumnStretch(column, 1)
