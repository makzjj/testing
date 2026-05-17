"""Field metadata used by grouped selector layouts."""

from __future__ import annotations

from dataclasses import dataclass

from .selection_option import SelectionOption


@dataclass(frozen=True)
class SelectionField:
    """One labeled selector field rendered by a selector-focused layout widget."""

    label: str
    options: list[str] | list[SelectionOption]
    current_value: str | None = None
    style: str = "auto"
    columns: int | None = None
    visible_rows: int | None = None
    stretch: int = 1
