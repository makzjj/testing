"""Pure helpers for shared motion measurement primitives."""

from __future__ import annotations

SAFE_PARK_TARGET_COUNTS = -44_000


def calculate_outward_range(home_position: int, opposite_position: int) -> int:
    return abs(int(opposite_position) - int(home_position))


def calculate_return_range(opposite_position: int, returned_home_position: int) -> int:
    return abs(int(opposite_position) - int(returned_home_position))


def calculate_return_error(home_position: int, returned_home_position: int) -> int:
    return abs(int(returned_home_position) - int(home_position))


def calculate_midpoint_target(home_position: int, opposite_position: int) -> int:
    return int(int(home_position) + ((int(opposite_position) - int(home_position)) // 2))


def calculate_safe_park_target(axis_type: str | None, home_position: int, opposite_position: int) -> int:
    axis_name = str(axis_type or "").strip().upper()
    if axis_name in {"Z", "PZ"}:
        return SAFE_PARK_TARGET_COUNTS
    return calculate_midpoint_target(home_position, opposite_position)
