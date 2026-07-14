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
    manual_prompt: str | None = None
    builder_name: str | None = None
    decoder_name: str | None = None
    display_name: str | None = None
    expected_response_description: str | None = None
    execution_policy: str | None = None
    category: str | None = None
    selected_by_default: bool = False
    sort_order: int | None = None
    cleanup_value: object | None = None
    unsupported_reason: str | None = None
    validation: dict[str, Any] | None = None
    command_form: str | None = None
    support_status: str | None = None
    execution_capability: str | None = None
    node_applicability: tuple[str, ...] | None = None
