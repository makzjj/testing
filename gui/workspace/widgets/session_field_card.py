"""Small field card used inside the live session widget."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from .effects import apply_card_shadow


class SessionFieldCard(QFrame):
    """Displays one labeled session value inside a compact card."""

    def __init__(self, label_text: str, accent: bool = False) -> None:
        super().__init__()
        self.setObjectName("SessionFieldCard")
        if accent:
            self.setProperty("accent", True)
        apply_card_shadow(self, blur_radius=18, y_offset=5)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(2)

        label = QLabel(label_text)
        label.setObjectName("SessionFieldLabel")
        root.addWidget(label)

        self.value_label = QLabel()
        self.value_label.setObjectName("SessionFieldValue")
        self.value_label.setWordWrap(True)
        self.value_label.setMinimumHeight(self.value_label.fontMetrics().lineSpacing())
        root.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        """Update the card value."""
        self.value_label.setText(value)
