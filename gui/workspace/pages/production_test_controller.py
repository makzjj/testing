"""Production test controller for Phase 3 runtime-backed node checks."""

from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..bridges import WorkspaceRuntimeBridge

PHASE3_SUPPORTED_NODE_ID = 6
PRODUCTION_TEST_TIMEOUT_MS = 3000


class ProductionTestController(QObject):
    """Runs one Production-side runtime-backed node test at a time."""

    log_message = pyqtSignal(str)
    test_started = pyqtSignal(int, str)
    test_passed = pyqtSignal(int, str, str)
    test_failed = pyqtSignal(int, str, str)
    test_aborted = pyqtSignal(int, str, str)

    def __init__(self, bridge: WorkspaceRuntimeBridge, timeout_ms: int = PRODUCTION_TEST_TIMEOUT_MS) -> None:
        super().__init__()
        self._bridge = bridge
        self._timeout_ms = timeout_ms
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._handle_timeout)
        self._runtime_window = None
        self._active_node_id: int | None = None
        self._active_node_name: str | None = None
        self._active_command_name = "Get Position"
        self._active_command_bytes = [0x82]

    def is_active(self) -> bool:
        return self._active_node_id is not None

    def run_test(self, node_id: int, node_name: str) -> bool:
        self.abort_test(emit_signal=False)

        runtime_window = self._bridge.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            reason = "Runtime backend is unavailable for Production testing."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            reason = "Serial port not connected."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        if not hasattr(runtime_window, "packet_received"):
            reason = "Runtime packet listener is unavailable."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        if node_id != PHASE3_SUPPORTED_NODE_ID:
            reason = f"Phase 3 currently supports only Node {PHASE3_SUPPORTED_NODE_ID} H."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        self._attach_runtime_window(runtime_window)
        self._active_node_id = node_id
        self._active_node_name = node_name

        try:
            command_bytes = list(backend_client.get_command_bytes(self._active_command_name, self._active_command_bytes))
            payload = backend_client.send_command_bytes(node_id, command_bytes)
        except Exception as exc:
            self._clear_active_state()
            reason = f"Failed to send Node {node_id} test command: {exc}"
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        self._timeout_timer.start(self._timeout_ms)
        self.test_started.emit(node_id, node_name)
        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] Started test for Node {node_id} {node_name}")
        self.log_message.emit(f"[Production] TX[{self._active_command_name}] -> Node {node_id:02d}: {payload_text}")
        return True

    def abort_test(self, *, emit_signal: bool = True) -> bool:
        if self._active_node_id is None or self._active_node_name is None:
            if emit_signal:
                self.log_message.emit("[Production] No active test to abort")
            return False

        node_id = self._active_node_id
        node_name = self._active_node_name
        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None

        if backend_client is not None and backend_client.is_connected():
            try:
                backend_client.send_stop_motor(node_id)
                self.log_message.emit(f"[Production] Sent stop command to Node {node_id} {node_name}")
            except Exception as exc:
                self.log_message.emit(f"[Production] Failed to send stop command to Node {node_id} {node_name}: {exc}")

        self._timeout_timer.stop()
        self._clear_active_state()
        if emit_signal:
            reason = "Operator stopped the Production test."
            self.test_aborted.emit(node_id, node_name, reason)
            self.log_message.emit("[Production] Test aborted")
        return True

    def _attach_runtime_window(self, runtime_window) -> None:
        if runtime_window is self._runtime_window:
            return

        if self._runtime_window is not None and hasattr(self._runtime_window, "packet_received"):
            try:
                self._runtime_window.packet_received.disconnect(self._handle_runtime_packet)
            except (TypeError, RuntimeError):
                pass

        runtime_window.packet_received.connect(self._handle_runtime_packet)
        self._runtime_window = runtime_window

    def _handle_runtime_packet(self, packet: object) -> None:
        if self._active_node_id is None or self._active_node_name is None:
            return
        if not isinstance(packet, dict):
            return
        if packet.get("status") != "ok" or packet.get("type") != "can_over_uart":
            return

        node_id = int(packet.get("sender", -1))
        if node_id != self._active_node_id:
            return

        command = int(packet.get("cmd", 0))
        if command != 0x82:
            return

        decoded_key = packet.get("decoded_key")
        decoded_value = packet.get("decoded_value")
        if decoded_key != "getpos" or not isinstance(decoded_value, tuple) or len(decoded_value) != 2:
            reason = f"Node {node_id} returned an invalid Get Position response."
            self._finish_failure(reason)
            return

        self._timeout_timer.stop()
        node_name = self._active_node_name
        position = decoded_value[1]
        self._clear_active_state()
        self.log_message.emit(f"[Production] Node {node_id} {node_name} responded with position {position}")
        self.test_passed.emit(node_id, node_name, f"Node {node_id} {node_name} responded successfully.")

    def _handle_timeout(self) -> None:
        if self._active_node_id is None:
            return
        self._finish_failure(f"Timed out waiting for Node {self._active_node_id} response.")

    def _finish_failure(self, reason: str) -> None:
        if self._active_node_id is None or self._active_node_name is None:
            return
        node_id = self._active_node_id
        node_name = self._active_node_name
        self._timeout_timer.stop()
        self._clear_active_state()
        self.log_message.emit(f"[Production] {reason}")
        self.test_failed.emit(node_id, node_name, reason)

    def _clear_active_state(self) -> None:
        self._active_node_id = None
        self._active_node_name = None
