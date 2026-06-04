"""Adapter that connects the Functional Test controller to the runtime backend.

This keeps SingleAxisFunctionalPopup/controller free of backend specifics and
allows swapping between offline safe TX and live transport.
"""

from __future__ import annotations

from typing import Callable, Optional

try:
    # PyQt is available in the project (used in tests too)
    from PyQt6.QtCore import QObject
except Exception:  # pragma: no cover - fallback types for static use
    class QObject:  # type: ignore
        pass


class FunctionalTransportAdapter(QObject):
    """Small wrapper around RobotBackendClient and runtime window packet stream.

    Responsibilities:
    - Send TX payloads for a specific node using existing backend_client
    - Subscribe to runtime window's parsed packet signal and forward normalized
      payloads to controller's `handle_runtime_packet([cmd, *params])`
    - Log TX/RX lines via provided callbacks (appended in the popup)
    """

    def __init__(
        self,
        backend_client: object,
        *,
        node_id: int,
        tx_logger: Optional[Callable[[str], None]] = None,
        rx_logger: Optional[Callable[[str], None]] = None,
        controller_handler: Optional[Callable[[list[int]], None]] = None,
    ) -> None:
        super().__init__()
        self.backend_client = backend_client
        self.node_id = int(node_id)
        self._tx_logger = tx_logger or (lambda _m: None)
        self._rx_logger = rx_logger or (lambda _m: None)
        self._controller_handler = controller_handler or (lambda _p: None)
        self._runtime_window: Optional[object] = None

    # --- TX path ---
    def send(self, payload: list[int]) -> None:
        """Send command bytes to the selected node using live backend.

        The backend already handles AMX/CAN framing; we pass raw command bytes.
        """
        try:
            hex_str = " ".join(f"{b:02X}" for b in payload)
            self._tx_logger(f"TX Node {self.node_id}: {hex_str}")
            # Delegate to existing backend client transport
            if hasattr(self.backend_client, "send_command_bytes"):
                self.backend_client.send_command_bytes(self.node_id, list(payload))
        except Exception as exc:  # pragma: no cover - log-only path
            self._tx_logger(f"TX failed: {exc}")

    # --- RX path wiring ---
    def attach_runtime_window(self, runtime_window: object) -> None:
        """Attach to runtime window to receive parsed packets.

        Expects a `packet_received` PyQt signal that emits decoded packet dicts
        produced by the existing UART parser. We filter per node and forward
        `[cmd, *params]` to the controller handler.
        """
        if runtime_window is None:
            return
        self._runtime_window = runtime_window
        signal = getattr(runtime_window, "packet_received", None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(self._on_packet_received)

    def detach_runtime_window(self) -> None:
        if not self._runtime_window:
            return
        signal = getattr(self._runtime_window, "packet_received", None)
        if signal is not None and hasattr(signal, "disconnect"):
            try:
                signal.disconnect(self._on_packet_received)
            except Exception:
                pass
        self._runtime_window = None

    # --- RX packet handler ---
    def _on_packet_received(self, packet: dict) -> None:
        """Handle a decoded runtime packet from the main window.

        Packet format per existing parser typically includes:
        - type == "can_over_uart"
        - sender (int) and/or target (int)
        - cmd (int), params (list[int])
        We treat packets from our target node (`sender`) as incoming sensor/pos
        updates for the functional controller.
        """
        try:
            if not isinstance(packet, dict):
                return
            if packet.get("type") != "can_over_uart":
                return
            sender = packet.get("sender")
            if int(sender) != self.node_id:
                return
            cmd = int(packet.get("cmd", 0))
            params = list(packet.get("params", []))
            # Forward normalized payload to controller
            self._controller_handler([cmd, *params])
            # RX log with friendly labels for key events
            lbl = self._label_for_rx(cmd, params)
            hex_str = " ".join(f"{b:02X}" for b in [cmd, *params])
            if lbl:
                self._rx_logger(f"RX Node {self.node_id}: {hex_str} - {lbl}")
            else:
                self._rx_logger(f"RX Node {self.node_id}: {hex_str}")
        except Exception as exc:  # pragma: no cover - log-only path
            self._rx_logger(f"RX handler error: {exc}")

    @staticmethod
    def _label_for_rx(cmd: int, params: list[int]) -> str:
        # Match log labels requested in the task description
        if cmd == 0x81 and params:
            code = params[0]
            if code == ord('L'):
                return "Left sensor has been cut"
            if code == ord('R'):
                return "Right sensor has been cut"
            if code == ord('I'):
                return "Position initialized"
        if cmd == 0x82 and len(params) >= 4:
            # Position value is 4 bytes little-endian
            val = (params[0] << 24) | (params[1] << 16) | (params[2] << 8) | params[3]
            # Interpret as signed 32-bit if needed; the controller already handles it,
            # but we display numeric value for convenience.
            if val & 0x80000000:
                val = -((~val & 0xFFFFFFFF) + 1)
            return f"Position {val}"
        return ""
