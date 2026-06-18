"""Lightweight shell-facing session state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionState:
    """Session state shown in the shell and overview page."""

    project_name: str
    connection_text: str
    session_text: str
    active_page: str
    alerts_text: str = ""
    has_live_runtime: bool = False
    operator_name: str = "Missing"
    assembler_name: str = "Missing"
    metadata_edit_enabled: bool = False
