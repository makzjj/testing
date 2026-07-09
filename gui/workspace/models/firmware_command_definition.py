"""Lightweight firmware command metadata for future FIT workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FirmwareCommandDefinition:
    """Shared command metadata for future firmware integration workflows."""

    name: str
    mode: str
    opcode: int | None = None
    text_command: str | None = None
    parameter_schema: dict[str, Any] | None = None
    expected_response: str | None = None
    timeout_ms: int | None = None
    manual_verification: bool = False
    builder_name: str | None = None
    decoder_name: str | None = None
