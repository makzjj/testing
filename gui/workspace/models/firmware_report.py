"""Shared Firmware Integration report models."""

from __future__ import annotations

from dataclasses import dataclass

from .firmware_test_case import FirmwareTestResult


@dataclass(frozen=True)
class FirmwareFitReport:
    """Immutable run-level report data for one completed FIT run."""

    run_id: str
    mode: str
    started_at: str | None
    completed_at: str | None
    duration_ms: float | None
    overall_status: str
    selected_case_count: int
    completed_case_count: int
    target_node_id: int | None = None
    operator_name: str | None = None
    station_name: str | None = None
    software_version: str | None = None
    firmware_context: str | None = None
    results: tuple[FirmwareTestResult, ...] = ()
    passed_count: int = 0
    failed_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    cancelled_count: int = 0
