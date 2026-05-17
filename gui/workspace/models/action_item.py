"""Action metadata used by button-driven workspace sections."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionItem:
    """One user-facing action item rendered by a workspace section."""

    action_id: str
    label: str
    hint: str = ""
