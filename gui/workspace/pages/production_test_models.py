"""Profile-driven Production test models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExpectedValue:
    value: Any = None
    description: str = ""


@dataclass(frozen=True)
class ActualValue:
    value: Any = None
    description: str = ""


@dataclass(frozen=True)
class Tolerance:
    exact_match: Any = None
    abs_margin: float | None = None
    min_value: float | None = None
    max_value: float | None = None


@dataclass(frozen=True)
class TestStep:
    step_id: str
    step_name: str
    step_type: str
    command_id: int | None = None
    command_name: str = ""
    payload: list[int] = field(default_factory=list)
    expected_value: Any = None
    tolerance: Tolerance | None = None
    timeout_ms: int = 3000
    stop_on_fail: bool = True
    expected_response_command_id: int | None = None
    send_command: bool = True
    wait_for_response: bool = True


@dataclass(frozen=True)
class TestProfile:
    profile_id: str
    profile_name: str
    node_id: int
    node_name: str
    steps: list[TestStep]


@dataclass(frozen=True)
class StepResult:
    step_id: str
    step_name: str
    expected_value: Any
    actual_value: Any
    result: str
    failure_reason: str
    raw_response_hex: str


@dataclass(frozen=True)
class FinalNodeResult:
    node_id: int
    node_name: str
    profile_id: str
    final_result: str
    failure_reason: str
    step_results: list[StepResult]


def evaluate_tolerance(
    expected_value: Any,
    actual_value: Any,
    tolerance: Tolerance | None,
) -> tuple[bool, str]:
    if tolerance is None:
        return expected_value == actual_value, "Value mismatch." if expected_value != actual_value else ""

    if tolerance.exact_match is not None:
        if actual_value == tolerance.exact_match:
            return True, ""
        return False, f"Expected exact match {tolerance.exact_match!r}, got {actual_value!r}."

    if tolerance.abs_margin is not None:
        try:
            expected_num = float(expected_value)
            actual_num = float(actual_value)
        except (TypeError, ValueError):
            return False, "Numeric absolute-margin comparison requires numeric expected/actual values."
        delta = abs(expected_num - actual_num)
        if delta <= float(tolerance.abs_margin):
            return True, ""
        return False, f"Absolute delta {delta} exceeds margin {tolerance.abs_margin}."

    if tolerance.min_value is not None or tolerance.max_value is not None:
        try:
            actual_num = float(actual_value)
        except (TypeError, ValueError):
            return False, "Range comparison requires a numeric actual value."
        if tolerance.min_value is not None and actual_num < float(tolerance.min_value):
            return False, f"Value {actual_num} is below minimum {tolerance.min_value}."
        if tolerance.max_value is not None and actual_num > float(tolerance.max_value):
            return False, f"Value {actual_num} is above maximum {tolerance.max_value}."
        return True, ""

    return expected_value == actual_value, "Value mismatch." if expected_value != actual_value else ""
