"""Data-driven layout widget for grouped selector fields."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..models import SelectionField
from .labeled_control import LabeledControl
from .visible_selector import VisibleSelector


class SelectorFieldGrid(QWidget):
    """Render one or more rows of labeled selectors from field metadata."""

    def __init__(self, rows: list[list[SelectionField]]) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        for row_fields in rows:
            root.addWidget(self._build_row(row_fields))

    def _build_row(self, row_fields: list[SelectionField]) -> QWidget:
        """Build one selector row and balance list-selector heights inside that row."""
        row_container = QWidget()
        row_container.setObjectName("SelectorFieldRow")
        row_layout = QHBoxLayout(row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(12)

        shared_visible_rows = self._resolve_shared_visible_rows(row_fields)
        for field in row_fields:
            selector = VisibleSelector(
                options=field.options,
                current_value=field.current_value,
                style=field.style,
                columns=field.columns,
                visible_rows=self._resolve_visible_rows(field, shared_visible_rows),
            )
            row_layout.addWidget(LabeledControl(field.label, selector), field.stretch)

        return row_container

    def _resolve_shared_visible_rows(self, row_fields: list[SelectionField]) -> int | None:
        """Choose one shared list height when a row contains multiple list selectors."""
        list_field_sizes = [self._resolve_list_size(field) for field in row_fields if self._uses_list_style(field)]
        if len(list_field_sizes) < 2:
            return None
        return max(list_field_sizes)

    def _resolve_list_size(self, field: SelectionField) -> int:
        """Clamp the visible row count for a list selector to a balanced compact range."""
        if field.visible_rows is not None:
            return max(1, field.visible_rows)
        return max(2, min(4, len(field.options)))

    def _resolve_visible_rows(self, field: SelectionField, shared_visible_rows: int | None) -> int | None:
        """Choose the final visible row count for one selector field."""
        if field.visible_rows is not None:
            return field.visible_rows
        if self._uses_list_style(field):
            return shared_visible_rows or self._resolve_list_size(field)
        return None

    def _uses_list_style(self, field: SelectionField) -> bool:
        """Decide whether a field should participate in list-height balancing."""
        if field.style == "list":
            return True
        if field.style == "segmented":
            return False
        return len(field.options) > 3
