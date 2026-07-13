"""Narrow ingress boundary for Firmware Integration packets."""

from __future__ import annotations

from typing import Any

try:
    from PyQt6.QtCore import QObject
except Exception:  # pragma: no cover - fallback type for non-GUI environments
    class QObject:  # type: ignore
        pass


class FirmwareTransportAdapter(QObject):
    """Forward only active Firmware Integration packets to the FIT controller."""

    def __init__(self, controller: object) -> None:
        super().__init__()
        self._controller = controller
        self._runtime_window: object | None = None

    @property
    def is_attached(self) -> bool:
        return self._runtime_window is not None

    @property
    def runtime_packet_source(self) -> object | None:
        return self._runtime_window

    def attach(self, runtime_packet_source: object | None) -> None:
        self.attach_runtime_window(runtime_packet_source)

    def detach(self) -> None:
        self.detach_runtime_window()

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

    def handle_packet(self, packet: object) -> None:
        self._on_packet_received(packet)

    def _on_packet_received(self, packet: object) -> None:
        pending_mode = self._pending_mode()
        if pending_mode in ("binary", "binary_fit"):
            normalized = self._normalize_binary_packet(packet)
            if normalized is None:
                return
            accepts_name = "accepts_manual_binary_packet" if pending_mode == "binary" else "accepts_binary_fit_packet"
            accepts = getattr(self._controller, accepts_name, None)
            if not callable(accepts):
                return
            if not accepts(
                sender=normalized["sender"],
                cmd=normalized["cmd"],
                params=normalized["params"],
            ):
                return
            handle_packet = getattr(self._controller, "handle_runtime_packet", None)
            if callable(handle_packet):
                handle_packet(normalized)
            return

        if pending_mode in ("text", "text_fit"):
            normalized = self._normalize_text_packet(packet)
            if normalized is None:
                return
            handler_name = "handle_manual_text_packet" if pending_mode == "text" else "handle_text_fit_packet"
            handle_packet = getattr(self._controller, handler_name, None)
            if callable(handle_packet):
                handle_packet(normalized)

    def _pending_mode(self) -> str | None:
        pending_mode = getattr(self._controller, "pending_request_mode", None)
        if callable(pending_mode):
            return pending_mode()

        has_binary = getattr(self._controller, "has_pending_manual_binary_request", None)
        if callable(has_binary) and has_binary():
            return "binary"
        has_text = getattr(self._controller, "has_pending_manual_text_request", None)
        if callable(has_text) and has_text():
            return "text"
        return None

    @staticmethod
    def _normalize_binary_packet(packet: object) -> dict[str, Any] | None:
        if not isinstance(packet, dict):
            return None
        if packet.get("status") not in (None, "ok"):
            return None
        if packet.get("type") != "can_over_uart":
            return None

        sender = packet.get("sender")
        cmd = packet.get("cmd")
        if sender is None or cmd is None:
            return None

        params = [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)]
        raw_packet = packet.get("raw_packet")
        if isinstance(raw_packet, (bytes, bytearray)):
            raw_hex = " ".join(f"{int(value) & 0xFF:02X}" for value in list(raw_packet))
        else:
            raw_hex = " ".join(f"{int(value) & 0xFF:02X}" for value in [int(cmd) & 0xFF, *params])

        return {
            "status": "ok",
            "type": "can_over_uart",
            "sender": int(sender),
            "cmd": int(cmd) & 0xFF,
            "params": params,
            "raw_hex": raw_hex,
        }

    @staticmethod
    def _normalize_text_packet(packet: object) -> dict[str, Any] | None:
        if not isinstance(packet, dict):
            return None
        if packet.get("status") not in (None, "ok"):
            return None
        if packet.get("type") != "direct_uart":
            return None

        raw_payload = packet.get("raw_payload")
        if not isinstance(raw_payload, (list, tuple, bytes, bytearray)):
            return None

        values = [int(value) & 0xFF for value in list(raw_payload)]
        if not values:
            return None

        return {
            "status": "ok",
            "type": "direct_uart",
            "node_id": None if packet.get("node_id") is None else int(packet.get("node_id")),
            "raw_payload": values,
            "raw_hex": str(packet.get("payload_hex") or " ".join(f"{value:02X}" for value in values)),
        }
