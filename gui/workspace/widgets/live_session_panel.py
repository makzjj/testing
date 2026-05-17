"""Persistent live session summary widget."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ..models import SessionState
from .effects import apply_card_shadow
from .status_chip import StatusChip


class LiveSessionPanel(QFrame):
    """Shows current project/session status as a compact right-side utility card."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("LiveSessionPanel")
        apply_card_shadow(self, blur_radius=16, y_offset=5)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(4)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)

        title = QLabel("Session")
        title.setObjectName("LiveSessionTitle")
        header.addWidget(title)
        header.addStretch(1)

        self.status_chip = StatusChip("OFFLINE", "warning")
        header.addWidget(self.status_chip)
        root.addLayout(header)

        details = QGridLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setHorizontalSpacing(4)
        details.setVerticalSpacing(1)

        runtime_label = QLabel("Runtime")
        runtime_label.setObjectName("SessionMetaLabel")
        details.addWidget(runtime_label, 0, 0)

        self.connection_value = QLabel()
        self.connection_value.setObjectName("SessionMetaValue")
        self.connection_value.setWordWrap(True)
        details.addWidget(self.connection_value, 0, 1)

        page_label = QLabel("Page")
        page_label.setObjectName("SessionMetaLabel")
        details.addWidget(page_label, 1, 0)

        self.page_value = QLabel()
        self.page_value.setObjectName("SessionMetaValue")
        self.page_value.setWordWrap(True)
        details.addWidget(self.page_value, 1, 1)

        details.setColumnStretch(1, 1)
        root.addLayout(details)

    def update_state(self, state: SessionState) -> None:
        """Refresh the shell-facing session summary."""
        self.connection_value.setText(state.connection_text)
        self.page_value.setText(state.active_page)
        self.status_chip.setText("LIVE" if state.has_live_runtime else "OFFLINE")
        self.status_chip.setProperty("tone", "success" if state.has_live_runtime else "warning")
        self.status_chip.style().unpolish(self.status_chip)
        self.status_chip.style().polish(self.status_chip)
