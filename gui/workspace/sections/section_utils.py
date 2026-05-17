"""Shared helpers for workspace section modules."""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QWidget

from ..models import DetailItem


def build_grid_layout(parent: QWidget | None = None, *, spacing: int = 12) -> QGridLayout:
    """Create a grid layout with the standard zero-margin section styling."""
    layout = QGridLayout(parent) if parent is not None else QGridLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(spacing)
    layout.setVerticalSpacing(spacing)
    return layout


def detail_map(items: list[DetailItem]) -> dict[str, str]:
    """Convert detail items into a label-to-value mapping."""
    return {item.label: item.value for item in items}
