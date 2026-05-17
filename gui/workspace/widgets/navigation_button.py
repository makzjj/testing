"""Navigation button used by the workspace shell."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton, QSizePolicy


class NavigationButton(QPushButton):
    """Checkable button that represents one workspace route."""

    def __init__(self, label: str, description: str = "", variant: str = "rail") -> None:
        super().__init__(label)
        self.setCheckable(True)
        self.setObjectName("NavigationButton")
        self.setProperty("variant", variant)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        if variant == "toolbar":
            self.setMinimumHeight(32)
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        else:
            self.setMinimumHeight(42)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        if description:
            self.setToolTip(description)
