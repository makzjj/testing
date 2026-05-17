"""Compact metric card widget."""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..models import MetricItem
from .effects import apply_card_shadow


class MetricCard(QFrame):
    """Displays one compact KPI value."""

    def __init__(self, metric: MetricItem) -> None:
        super().__init__()
        self.setObjectName("MetricCard")
        self.setProperty("tone", metric.tone)
        apply_card_shadow(self, blur_radius=22, y_offset=6)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        accent = QFrame()
        accent.setObjectName("MetricAccent")
        accent.setProperty("tone", metric.tone)
        accent.setFixedSize(28, 28)
        root.addWidget(accent)

        label = QLabel(metric.label)
        label.setObjectName("MetricLabel")
        root.addWidget(label)

        value = QLabel(metric.value)
        value.setObjectName("MetricValue")
        root.addWidget(value)

        if metric.caption:
            caption = QLabel(metric.caption)
            caption.setObjectName("MetricCaption")
            caption.setWordWrap(True)
            caption.setMinimumHeight(caption.fontMetrics().lineSpacing())
            root.addWidget(caption)

        root.addStretch(1)
