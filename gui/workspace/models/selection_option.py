"""Option metadata used by visible workspace selectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelectionOption:
    """One discoverable option rendered by a visible selector."""

    label: str
    value: str
    description: str = ""
