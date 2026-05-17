"""Card-style panel widget used by workspace sections."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from .effects import apply_card_shadow


class PanelFrame(QFrame):
    """Reusable titled panel container."""

    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        self.setObjectName("WorkspacePanel")
        apply_card_shadow(self, blur_radius=26, y_offset=8)
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("PanelTitle")
        root.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("PanelSubtitle")
            subtitle_label.setWordWrap(True)
            root.addWidget(subtitle_label)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(6)
        root.addWidget(self.body)
