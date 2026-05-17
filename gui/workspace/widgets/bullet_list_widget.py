"""Widget for rendering short bullet-style notes."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .effects import apply_card_shadow


class BulletListWidget(QWidget):
    """Displays short notes as stacked cards."""

    def __init__(self, items: list[str]) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        for text in items:
            card = QFrame()
            card.setObjectName("BulletNoteCard")
            apply_card_shadow(card, blur_radius=12, y_offset=3)

            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 9, 12, 9)
            card_layout.setSpacing(10)

            marker = QFrame()
            marker.setObjectName("BulletMarkerDot")
            marker.setFixedSize(8, 8)

            body = QLabel(text)
            body.setObjectName("BulletBody")
            body.setWordWrap(True)
            body.setMinimumHeight(body.fontMetrics().lineSpacing())

            card_layout.addWidget(marker, 0)
            card_layout.addWidget(body, 1)
            root.addWidget(card)
