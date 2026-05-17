"""Painted backdrop for the lighter Phase 2 workspace shell."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QWidget


class WorkspaceBackdrop(QWidget):
    """Custom background widget with a soft warm-to-cool product backdrop."""

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())

        base = QLinearGradient(rect.topLeft(), rect.bottomRight())
        base.setColorAt(0.0, QColor("#F9EFE3"))
        base.setColorAt(0.22, QColor("#FCF7F2"))
        base.setColorAt(0.64, QColor("#FAFBFD"))
        base.setColorAt(1.0, QColor("#F5F6F8"))
        painter.fillRect(rect, base)

        for center, radius, inner_color in (
            (QPointF(rect.left() + rect.width() * 0.08, rect.top() + rect.height() * 0.07), rect.width() * 0.34, QColor(255, 188, 128, 62)),
            (QPointF(rect.left() + rect.width() * 0.86, rect.top() + rect.height() * 0.10), rect.width() * 0.30, QColor(233, 238, 250, 86)),
            (QPointF(rect.left() + rect.width() * 0.82, rect.top() + rect.height() * 0.90), rect.width() * 0.36, QColor(246, 225, 206, 54)),
        ):
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0.0, inner_color)
            glow.setColorAt(1.0, QColor(inner_color.red(), inner_color.green(), inner_color.blue(), 0))
            painter.fillRect(rect, glow)

        painter.setPen(Qt.PenStyle.NoPen)

        top_band = QPainterPath()
        top_band.moveTo(rect.left(), rect.top() + rect.height() * 0.02)
        top_band.lineTo(rect.right(), rect.top() + rect.height() * 0.18)
        top_band.lineTo(rect.right(), rect.top())
        top_band.lineTo(rect.left(), rect.top())
        top_band.closeSubpath()
        top_gradient = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top() + rect.height() * 0.18)
        top_gradient.setColorAt(0.0, QColor(255, 255, 255, 76))
        top_gradient.setColorAt(0.5, QColor(255, 232, 208, 24))
        top_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(top_band, top_gradient)

        beam = QPainterPath()
        beam.moveTo(rect.left() + rect.width() * 0.28, rect.top())
        beam.lineTo(rect.left() + rect.width() * 0.48, rect.top())
        beam.lineTo(rect.left() + rect.width() * 0.18, rect.bottom())
        beam.lineTo(rect.left() + rect.width() * 0.02, rect.bottom())
        beam.closeSubpath()
        beam_gradient = QLinearGradient(rect.left(), rect.top(), rect.left() + rect.width() * 0.48, rect.bottom())
        beam_gradient.setColorAt(0.0, QColor(255, 255, 255, 32))
        beam_gradient.setColorAt(0.55, QColor(255, 225, 197, 16))
        beam_gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(beam, beam_gradient)
