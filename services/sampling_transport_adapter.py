"""Narrow ingress adapter for Sampling workflow packets.

This adapter keeps Sampling off the raw global packet fan-out path without
introducing a general request router yet. It forwards only packets that match
the controller's current workflow expectation.
"""

from __future__ import annotations

from typing import Any

from data.binary_cmd_parser import decode_command

try:
    from PyQt6.QtCore import QObject
except Exception:  # pragma: no cover - fallback type for non-GUI environments
    class QObject:  # type: ignore
        pass


class SamplingTransportAdapter(QObject):
    """Forward only workflow-relevant packets to the Sampling controller."""

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

        decoded_kind, decoded_value = decode_command(normalized["cmd"], normalized["params"])
        accepts_packet = getattr(self._controller, "accepts_workflow_packet", None)
        if not callable(accepts_packet):
            return
        if not accepts_packet(decoded_kind, decoded_value, sender=normalized["sender"]):
            return

        handle_packet = getattr(self._controller, "handle_runtime_packet", None)
        if callable(handle_packet):
            handle_packet([normalized["cmd"], *normalized["params"]])

    @staticmethod
    def _normalize_packet(packet: object) -> dict[str, Any] | None:
        if not isinstance(packet, dict):
            return None
        if packet.get("status") not in (None, "ok"):
            return None

        packet_type = packet.get("type")
        sender = packet.get("sender")
        if sender is None:
            sender = packet.get("node_id")

        if packet_type in (None, "can_over_uart"):
            cmd = packet.get("cmd")
            if cmd is None:
                return None
            params = packet.get("params", [])
            return {
                "sender": None if sender is None else int(sender),
                "cmd": int(cmd) & 0xFF,
                "params": [int(value) & 0xFF for value in list(params)],
            }

        if packet_type == "direct_uart":
            raw_payload = packet.get("raw_payload") or packet.get("payload")
            if not isinstance(raw_payload, (list, tuple, bytes, bytearray)):
                return None
            values = [int(value) & 0xFF for value in list(raw_payload)]
            if not values:
                return None
            return {
                "sender": None if sender is None else int(sender),
                "cmd": values[0],
                "params": values[1:],
            }

        return None
