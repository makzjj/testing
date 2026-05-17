"""Base class for scrollable workspace pages."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ..widgets import ResponsiveRow


class BaseWorkspacePage(QScrollArea):
    """Base page scaffold with a compact intro and stacked rows of sections."""

    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("WorkspacePage")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("WorkspacePageContainer")
        self.setWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(3)

        if title:
            title_label = QLabel(title)
            title_label.setObjectName("PageTitle")
            root.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PageSubtitle")
            subtitle_label.setWordWrap(True)
            root.addWidget(subtitle_label)

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(6)
        root.addLayout(self.content_layout)
        root.addStretch(1)

    def add_row(self, *widgets: QWidget) -> None:
        """Add one horizontal row of equally stretched section widgets."""
        row = ResponsiveRow()
        for widget in widgets:
            row.add_panel(widget)
        self.content_layout.addWidget(row)

    def add_full_width(self, widget: QWidget) -> None:
        """Add one section that spans the page width."""
        self.content_layout.addWidget(widget)
