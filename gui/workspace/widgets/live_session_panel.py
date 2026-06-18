"""Persistent live session summary widget."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..models import SessionState
from .effects import apply_card_shadow


class LiveSessionPanel(QFrame):
    """Shows current project/session status as a compact right-side utility card."""

    edit_requested = pyqtSignal()

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

        self.edit_button = QPushButton("Edit")
        self.edit_button.setObjectName("SessionEditButton")
        self.edit_button.setProperty("tone", "secondary")
        self.edit_button.setEnabled(False)
        self.edit_button.clicked.connect(self.edit_requested.emit)
        header.addWidget(self.edit_button)
        root.addLayout(header)

        details = QGridLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setHorizontalSpacing(4)
        details.setVerticalSpacing(1)

        operator_label = QLabel("OPERATOR:")
        operator_label.setObjectName("SessionMetaLabel")
        details.addWidget(operator_label, 0, 0)

        self.operator_value = QLabel("Missing")
        self.operator_value.setObjectName("SessionMetaValue")
        self.operator_value.setWordWrap(True)
        details.addWidget(self.operator_value, 0, 1)

        assembler_label = QLabel("ASSEMBLER:")
        assembler_label.setObjectName("SessionMetaLabel")
        details.addWidget(assembler_label, 1, 0)

        self.assembler_value = QLabel("Missing")
        self.assembler_value.setObjectName("SessionMetaValue")
        self.assembler_value.setWordWrap(True)
        details.addWidget(self.assembler_value, 1, 1)

        page_label = QLabel("PAGE:")
        page_label.setObjectName("SessionMetaLabel")
        details.addWidget(page_label, 2, 0)

        self.page_value = QLabel("-")
        self.page_value.setObjectName("SessionMetaValue")
        self.page_value.setWordWrap(True)
        details.addWidget(self.page_value, 2, 1)

        details.setColumnStretch(1, 1)
        root.addLayout(details)

    def update_state(self, state: SessionState) -> None:
        """Refresh the shell-facing session summary."""
        self.operator_value.setText(state.operator_name.strip() or "Missing")
        self.assembler_value.setText(state.assembler_name.strip() or "Missing")
        self.page_value.setText(state.active_page)
        self.edit_button.setEnabled(bool(state.metadata_edit_enabled))
