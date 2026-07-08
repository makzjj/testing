"""Narrow ingress adapter for ProductionParameterController workflow packets."""

from __future__ import annotations

from typing import Any

try:
    from PyQt6.QtCore import QObject
except Exception:  # pragma: no cover - fallback type for non-GUI environments
    class QObject:  # type: ignore
        pass


class ProductionParameterTransportAdapter(QObject):
    """Forward only Production-parameter-relevant packets to the parameter controller."""

    def __init__(self, controller: object) -> None:
        super().__init__()
        self._controller = controller
        self._runtime_window: object | None = None

    def attach_runtime_window(self, runtime_window: object | None) -> None:
        if runtime_window is self._runtime_window:
            return
        self.detach_runtime_window()
        if runtime_window is None:
            return
        signal = getattr(runtime_window, "packet_received", None)
        if signal is None or not hasattr(signal, "connect"):
            return
        signal.connect(self._on_packet_received)
        self._runtime_window = runtime_window

    def detach_runtime_window(self) -> None:
        if self._runtime_window is None:
            return
        signal = getattr(self._runtime_window, "packet_received", None)
        if signal is not None and hasattr(signal, "disconnect"):
            try:
                signal.disconnect(self._on_packet_received)
            except (TypeError, RuntimeError):
                pass
        self._runtime_window = None

    def _on_packet_received(self, packet: object) -> None:
        normalized = self._normalize_packet(packet)
        if normalized is None:
            return

        accepts_packet = getattr(self._controller, "accepts_workflow_packet", None)
        if not callable(accepts_packet):
            return
        if not accepts_packet(
            sender=normalized["sender"],
            cmd=normalized["cmd"],
            params=normalized["params"],
        ):
            return

        handle_packet = getattr(self._controller, "handle_runtime_packet", None)
        if callable(handle_packet):
            handle_packet(normalized)

    @staticmethod
    def _normalize_packet(packet: object) -> dict[str, Any] | None:
        if not isinstance(packet, dict):
            return None
        if packet.get("status") != "ok" or packet.get("type") != "can_over_uart":
            return None

        sender = packet.get("sender")
        cmd = packet.get("cmd")
        if sender is None or cmd is None:
            return None

        return {
            "status": "ok",
            "type": "can_over_uart",
            "sender": int(sender),
            "cmd": int(cmd) & 0xFF,
            "params": [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)],
        }
