"""Lightweight automated Firmware Integration case/result models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FirmwareTestCase:
    """Metadata for one future automated Firmware Integration test instance."""

    case_id: str
    name: str
    mode: str
    command_key: str
    parameter_value: object | None = None
    expected_response: str | None = None
    timeout_ms: int | None = None
    manual_verification: bool = False
    manual_prompt: str | None = None
    selected_by_default: bool = False
    category: str | None = None
    display_group: str | None = None


@dataclass(frozen=True)
class FirmwareTestResult:
    """Outcome data for one future automated Firmware Integration test instance."""

    case_id: str
    status: str
    expected: str | None = None
    actual: str | None = None
    tx_bytes: bytes | None = None
    rx_bytes: bytes | None = None
    latency_ms: float | None = None
    message: str | None = None
    manual_verification_outcome: str | None = None


@dataclass(frozen=True)
class FirmwareBinaryFitSnapshot:
    """Read-only Binary FIT render contract for UI consumers."""

    running: bool
    state: str
    current_case: FirmwareTestCase | None
    current_index: int
    total_cases: int
    completed_cases: int
    awaiting_manual_verification: bool
    results: tuple[FirmwareTestResult, ...]
    overall_status: str | None = None
    target_node_id: int | None = None
    manual_verification_case_id: str | None = None
    manual_verification_prompt: str | None = None


@dataclass(frozen=True)
class FirmwareTextFitSnapshot:
    """Read-only Text FIT render contract for future UI consumers."""

    running: bool
    state: str
    current_case: FirmwareTestCase | None
    current_index: int
    total_cases: int
    completed_cases: int
    awaiting_manual_verification: bool
    results: tuple[FirmwareTestResult, ...]
    overall_status: str | None = None
    manual_verification_case_id: str | None = None
    manual_verification_prompt: str | None = None
