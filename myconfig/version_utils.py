"""Shared helpers for dotted numeric version-style fields."""

from __future__ import annotations

import re


VERSION_TEXT_PATTERN = re.compile(r"^\d+(?:\.\d+){0,3}$")


def is_valid_version_text(value: str) -> bool:
    """Return whether the given value matches the supported dotted version pattern."""
    return bool(VERSION_TEXT_PATTERN.fullmatch(value.strip()))
