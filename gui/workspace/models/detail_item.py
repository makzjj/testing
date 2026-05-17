"""Label/value items used by summary sections."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetailItem:
    """One labeled value shown in a summary list."""

    label: str
    value: str
