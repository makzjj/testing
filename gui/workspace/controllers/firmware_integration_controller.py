"""Single public workflow owner for future Firmware Integration Test behavior."""

from __future__ import annotations

from services.firmware_transport_adapter import FirmwareTransportAdapter


class FirmwareIntegrationController:
    """Inert FIT scaffold for the refactored firmware workspace surface."""

    def __init__(self) -> None:
        self._transport_adapter = FirmwareTransportAdapter(self)
        self._last_action: str | None = None

    @property
    def transport_adapter(self) -> FirmwareTransportAdapter:
        return self._transport_adapter

    @property
    def last_action(self) -> str | None:
        return self._last_action

    def open_manual_binary_mode(self) -> str:
        return self._record_placeholder("Manual Binary Command mode is scaffolded for FIT-0B. No command execution yet.")

    def open_manual_text_mode(self) -> str:
        return self._record_placeholder("Manual Text Command mode is scaffolded for FIT-0B. No command execution yet.")

    def start_binary_fit(self) -> str:
        return self._record_placeholder("Binary FIT is scaffolded for FIT-0B. No workflow execution yet.")

    def start_text_fit(self) -> str:
        return self._record_placeholder("Text FIT is scaffolded for FIT-0B. No workflow execution yet.")

    def open_reports(self) -> str:
        return self._record_placeholder("Reports / Export is scaffolded for FIT-0B. No report behavior yet.")

    def cancel_active_operation(self) -> str:
        return self._record_placeholder("No active Firmware Integration operation to cancel in FIT-0B.")

    def handle_runtime_packet(self, packet: object) -> None:
        """Placeholder ingress target for future transport adapter wiring."""
        _ = packet

    def _record_placeholder(self, message: str) -> str:
        self._last_action = message
        return message
