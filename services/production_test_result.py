"""Structured production test result model for CSV logging."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductionTestResult:
    run_id: str | None = None
    job_id: str | None = None
    timestamp_utc: str | None = None
    node_id: int | None = None
    node_name: str | None = None
    test_type: str | None = None
    expected_value: object | None = None
    actual_value: object | None = None
    result: str | None = None
    failure_reason: str | None = None
    raw_response_hex: str | None = None
