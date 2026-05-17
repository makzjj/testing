"""Navigation metadata for the workspace shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavigationItem:
    """One first-level workspace route."""

    route_id: str
    label: str
    description: str = ""
    enabled: bool = True
