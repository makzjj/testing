"""Reusable visual effects for workspace widgets."""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget


def apply_card_shadow(widget: QWidget, blur_radius: int = 28, y_offset: int = 10) -> None:
    """Attach a soft shadow to a card-like widget."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur_radius)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(164, 150, 140, 24))
    widget.setGraphicsEffect(shadow)
