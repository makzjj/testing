"""Metric card model for overview KPIs and compact summaries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricItem:
    """One compact metric displayed in a card."""

    label: str
    value: str
    caption: str = ""
    tone: str = "neutral"
