"""Compact Functional popup shell for single-axis controller integration.

This dialog renders state and emits user actions. Controller and transport
wiring live outside the widget boundary where practical.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from typing import TYPE_CHECKING, Optional, Any
from services.release_watch_helper import ReleaseWatchHelper

if TYPE_CHECKING:  # pragma: no cover - only for type checking to avoid circular import at runtime
    from gui.workspace.controllers.single_axis_functional_test_controller import (
        SingleAxisFunctionalTestController,
    )


class SingleAxisFunctionalPopup(QDialog):
    """Compact Functional popup for Single Axis Functional Test."""

    functional_passed = pyqtSignal(int, str)
    functional_failed = pyqtSignal(int, str, str)
    functional_aborted = pyqtSignal(int, str, str)
    sampling_start_requested = pyqtSignal()

    _INACTIVE_FLAG_COLOR = "#7A4D1F"
    _ACTIVE_FLAG_COLOR = "#FF8C00"
    _UNKNOWN_FLAG_COLOR = "#777777"

    def __init__(
        self,
        parent: QWidget | None = None,
        node_options: list[tuple[int, str]] | None = None,
        controller: Optional['SingleAxisFunctionalTestController'] = None,
        bridge: Optional[object] = None,
        allow_safe_tx: bool = False,
        release_watch_helper: ReleaseWatchHelper | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Functional")
        self.setModal(False)
        self.resize(420, 320)
        self.setMinimumSize(400, 300)

        self._is_running = False
        self._active_node_id: int | None = None
        self._bridge = bridge  # WorkspaceRuntimeBridge when provided
        self._adapter = None  # set during live runs
        self._runtime_packet_window: QObject | None = None
        self._release_watch_helper = release_watch_helper or (ReleaseWatchHelper(bridge) if bridge is not None else None)
        self._transport_sender = None
        # safe TX log for tests/inspection (no real hardware tx in this phase)
        self._tx_log: list[list[int]] = []
        self._last_position_value: int | None = None
        self._middle_travel_origin_position: int | None = None
        self._middle_travel_target_position: int | None = None
        self._middle_travel_display_value: int | None = None
        self._middle_travel_active = False
        # Test-only flag: when True and no backend is connected/provided,
        # allow starting in safe TX mode. For normal UI usage this should be False.
        self._allow_safe_tx: bool = bool(allow_safe_tx)

        # Controller instance (lazy to avoid circular imports on module load)
        self.controller: ['SingleAxisFunctionalTestController'] | None = controller
        if self.controller is not None:
            self._wire_controller_callbacks()
        else:
            # Create lazily but at construction time for convenience in tests/usage
            self._ensure_controller()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        top_row = QGridLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setHorizontalSpacing(8)
        top_row.setVerticalSpacing(4)

        node_label = QLabel("Node")
        self.node_combo = QComboBox()
        self.node_combo.setMinimumWidth(130)
        self.node_combo.addItem("Select Node", None)
        for node_id, node_name in node_options or []:
            self.node_combo.addItem(f"Node {int(node_id)} ({str(node_name)})", (int(node_id), str(node_name)))
        self.node_combo.currentIndexChanged.connect(self._handle_selected_node_changed)

        self.position_field = QLabel("0")
        self.position_field.setObjectName("DetailValue")
        self.range_field = QLabel("-")
        self.range_field.setObjectName("DetailValue")

        top_row.addWidget(node_label, 0, 0)
        top_row.addWidget(self.node_combo, 0, 1)
        top_row.addWidget(QLabel("Position"), 1, 0)
        top_row.addWidget(self.position_field, 1, 1)
        top_row.addWidget(QLabel("Range"), 2, 0)
        top_row.addWidget(self.range_field, 2, 1)

        flags_layout = QVBoxLayout()
        flags_layout.setContentsMargins(0, 0, 0, 0)
        flags_layout.setSpacing(6)
        self.left_flag_led = self._build_led_widget()
        self.right_flag_led = self._build_led_widget()
        flags_layout.addLayout(self._build_flag_row(self.left_flag_led, "Left Flag (INT0)"))
        flags_layout.addLayout(self._build_flag_row(self.right_flag_led, "Right Flag (INT1)"))
        flags_layout.addStretch(1)
        top_row.addLayout(flags_layout, 0, 2, 3, 1)
        top_row.setColumnStretch(1, 1)
        root_layout.addLayout(top_row)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)

        self.status_block = QTextEdit()
        self.status_block.setReadOnly(True)
        self.status_block.setMinimumHeight(140)
        status_row.addWidget(self.status_block, 1)

        side_buttons = QVBoxLayout()
        side_buttons.setContentsMargins(0, 0, 0, 0)
        side_buttons.setSpacing(6)
        self.log_button = QPushButton("Log")
        self.log_button.setProperty("tone", "secondary")
        self.log_button.clicked.connect(self._show_log_placeholder)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("tone", "secondary")
        self.clear_button.clicked.connect(self.status_block.clear)
        side_buttons.addWidget(self.log_button)
        side_buttons.addWidget(self.clear_button)
        side_buttons.addStretch(1)
        status_row.addLayout(side_buttons)
        root_layout.addLayout(status_row)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(8)
        tolerance_row = QHBoxLayout()
        tolerance_row.setContentsMargins(0, 0, 0, 0)
        tolerance_row.setSpacing(6)
        tolerance_label = QLabel("Tolerance")
        self.tolerance_combo = QComboBox()
        for counts in (128, 256, 512, 1024, 2048, 4096):
            self.tolerance_combo.addItem(f"{counts} counts", counts)
        self.tolerance_combo.setCurrentIndex(2)
        tolerance_row.addWidget(tolerance_label)
        tolerance_row.addWidget(self.tolerance_combo)
        footer_row.addLayout(tolerance_row)
        footer_row.addStretch(1)
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._handle_run_clicked)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("tone", "danger")
        self.stop_button.clicked.connect(self._handle_stop_clicked)
        self.stop_button.setEnabled(False)
        self.close_button = QPushButton("Close")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)
        footer_row.addWidget(self.run_button)
        footer_row.addWidget(self.stop_button)
        footer_row.addWidget(self.close_button)
        root_layout.addLayout(footer_row)

        self._attach_runtime_packet_listener()
        self._refresh_interrupt_leds()

    # Public API used by controller/state-machine integration
    def append_status(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_block.append(f"[{timestamp}] {message}")

    def update_position(self, value: object) -> None:
        self.position_field.setText(str(value))
        try:
            self._last_position_value = int(value)
        except (TypeError, ValueError):
            self._last_position_value = None

    def update_range(self, value: object) -> None:
        self.range_field.setText(str(value))

    def mark_passed(self) -> None:
        node_text = self._selected_node_text()
        self.append_status(f"Node {node_text}: Functional test PASSED.")
        node_id, node_name = self._selected_node_data()
        self.functional_passed.emit(node_id, node_name)
        # Re-enable controls after finish
        self._finish_run_ui()
        self._clear_middle_travel_state()
        # Keep the pass gate independent from the sampling prompt decision.
        if self.ask_start_sampling():
            self.sampling_start_requested.emit()

    def mark_failed(self, reason: str) -> None:
        from PyQt6.QtWidgets import QMessageBox  # local import to keep top clean

        node_text = self._selected_node_text()
        self.append_status(f"Node {node_text}: Functional test FAILED. Reason: {reason}")
        node_id, node_name = self._selected_node_data()
        self.functional_failed.emit(node_id, node_name, str(reason))
        self._clear_middle_travel_state()
        QMessageBox.warning(self, "Functional Test Failed", str(reason))
        self._finish_run_ui()

    def mark_aborted(self) -> None:
        node_id, node_name = self._selected_node_data()
        self.functional_aborted.emit(node_id, node_name, "Functional test aborted.")
        self._clear_middle_travel_state()
        self._finish_run_ui()

    def ask_start_sampling(self) -> bool:
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setWindowTitle("Functional")
        message_box.setText("Functional Test Passed. Do you want to start collecting 32 samples now?")
        start_sampling_button = message_box.addButton("Start Sampling", QMessageBox.ButtonRole.AcceptRole)
        message_box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        message_box.exec()
        return message_box.clickedButton() is start_sampling_button

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._is_running:
            event.ignore()
            QMessageBox.information(self, "Functional", "Test is running. Please wait for completion.")
            return
        self._cancel_release_watch("popup_closed")
        self._detach_runtime_packet_listener()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._attach_runtime_packet_listener()
        self._refresh_interrupt_leds()

    def _handle_run_clicked(self) -> None:
        if self._is_running:
            return
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            QMessageBox.warning(self, "Functional", "Please select a node before running the functional test.")
            return
        node_id, _node_name = node_data
        self._start_controller_run(int(node_id), self._selected_tolerance())

    def _handle_stop_clicked(self) -> None:
        if not self._is_running:
            return
        self._cancel_release_watch("user_stop")
        self._ensure_controller()
        assert self.controller is not None
        self.controller.abort_by_user()

    def _start_controller_run(self, node_id: int, tolerance: int) -> None:
        # Determine transport state before marking as running
        runtime_window = None
        backend_client = None
        # Bridge contract is kept loose to avoid tight coupling in tests
        if self._bridge is not None and hasattr(self._bridge, "get_runtime_window"):
            try:
                runtime_window = self._bridge.get_runtime_window(create_if_missing=True)  # type: ignore[attr-defined]
            except Exception:
                runtime_window = None
        # Fallback: parent may expose a runtime window directly
        if runtime_window is None and hasattr(self.parent(), "get_runtime_window"):
            try:
                runtime_window = self.parent().get_runtime_window(create_if_missing=False)  # type: ignore[attr-defined]
            except Exception:
                runtime_window = None

        if runtime_window is not None and hasattr(runtime_window, "backend_client"):
            backend_client = getattr(runtime_window, "backend_client", None)

        # Decide run mode
        live_connected = bool(
            backend_client is not None
            and hasattr(backend_client, "is_connected")
            and backend_client.is_connected()
        )

        if not live_connected and not self._allow_safe_tx:
            # Do not start. Warn user and log. Ensure UI enabled and _is_running stays False.
            self.append_status("Transport not connected. Functional test not started.")
            QMessageBox.warning(
                self,
                "Functional",
                "Please connect the serial connection before running the functional test.",
            )
            self._finish_run_ui()
            return

        # At this point, we are either live-connected, or explicitly allowed safe TX (tests)
        self._active_node_id = node_id
        self._is_running = True
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.node_combo.setEnabled(False)
        self.tolerance_combo.setEnabled(False)
        self._clear_middle_travel_state()
        self.update_position(0)
        self.update_range("-")
        self._attach_runtime_packet_listener()
        self._refresh_interrupt_leds()

        # Add session separator
        self.append_status("— New functional test session —")
        self.append_status(f"Tolerance selected: {int(tolerance)} counts")
        # Start controller with real transport if available
        self._ensure_controller()
        assert self.controller is not None
        self.controller.cfg.zero_tolerance = int(tolerance)
        self.controller.cfg.movement_tolerance = int(tolerance)
        self.controller.cfg.range_tolerance = int(tolerance)
        self.controller.cfg.middle_position_tolerance = int(tolerance)

        if live_connected:
            try:
                from services.functional_transport_adapter import FunctionalTransportAdapter

                # Prepare adapter with node-scoped TX/RX and logging into the popup
                adapter = FunctionalTransportAdapter(
                    backend_client,
                    node_id=node_id,
                    tx_logger=self.append_status,
                    rx_logger=self.append_status,
                    controller_handler=self.controller.handle_runtime_packet,
                    controller_relevance=self.controller.accepts_workflow_packet,
                )
                # Attach RX routing if a runtime window exists
                if hasattr(adapter, "attach_runtime_window"):
                    adapter.attach_runtime_window(runtime_window)

                # Replace command sender to use the real transport
                self._transport_sender = self._build_live_transport_sender(adapter)
                self.controller.command_requested = self._handle_controller_command_requested
                self._adapter = adapter
                self.append_status(f"Using live transport for Node {node_id}")
            except Exception as exc:
                # Fall back to safe TX only if explicitly allowed (tests). Otherwise abort.
                if self._allow_safe_tx:
                    self.append_status(f"Live transport unavailable, falling back to safe TX: {exc}")
                else:
                    self.append_status("Transport not connected. Functional test not started.")
                    QMessageBox.warning(
                        self,
                        "Functional",
                        "Please connect the serial connection before running the functional test.",
                    )
                    self._finish_run_ui()
                    return
        else:
            # Safe TX path explicitly enabled (tests only)
            self.append_status("Using safe TX mode (test).")
            self._transport_sender = self._build_safe_transport_sender()

        # Start controller sequence
        self.controller.start(node_id)

    def _finish_run_ui(self) -> None:
        self._is_running = False
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.node_combo.setEnabled(True)
        self.tolerance_combo.setEnabled(True)
        # Detach live adapter if present to stop receiving packets
        if self._adapter is not None and hasattr(self._adapter, "detach_runtime_window"):
            try:
                self._adapter.detach_runtime_window()
            except Exception:
                pass
        self._cancel_release_watch("run_finished")
        self._adapter = None
        self._transport_sender = self._build_safe_transport_sender()
        self._active_node_id = None
        self._clear_middle_travel_state()
        self._refresh_interrupt_leds()

    def _show_log_placeholder(self) -> None:
        log_text = self.status_block.toPlainText().strip() or "No status messages available."
        QMessageBox.information(self, "Functional Log", log_text)

    def _selected_node_text(self) -> str:
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            return "-"
        return str(node_data[0])

    def _selected_node_data(self) -> tuple[int, str]:
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            return 0, ""
        node_id, node_name = node_data
        return int(node_id), str(node_name)

    def _selected_tolerance(self) -> int:
        tolerance = self.tolerance_combo.currentData()
        if isinstance(tolerance, int):
            return tolerance
        return 512

    @classmethod
    def _build_led_widget(cls) -> QLabel:
        led = QLabel()
        led.setFixedSize(12, 12)
        led.setFrameShape(QFrame.Shape.NoFrame)
        cls._set_led_display_state(led, "unknown")
        return led

    @classmethod
    def _set_led_display_state(cls, led: QLabel, state: str) -> None:
        if state == "cut":
            color = cls._ACTIVE_FLAG_COLOR
        elif state == "not_cut":
            color = cls._INACTIVE_FLAG_COLOR
        else:
            color = cls._UNKNOWN_FLAG_COLOR
        led.setStyleSheet(f"border-radius: 6px; background: {color};")

    @staticmethod
    def _build_flag_row(led: QLabel, label_text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(led, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(QLabel(label_text), 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return row


    # --- Controller wiring helpers ---
    def _wire_controller_callbacks(self) -> None:
        # Safe TX handler: log and store only
        def _safe_tx(payload: list[int]) -> bool:
            self._tx_log.append(list(payload))
            hex_str = " ".join(f"{b:02X}" for b in payload)
            if payload == [0xDD] and self._active_node_id is not None:
                self.append_status(f"TX Node {self._active_node_id}: {hex_str}")
            else:
                self.append_status(f"TX requested: {hex_str}")
            return True

        # Range/diff helpers: update range label and append status for visibility
        def _on_range1(val: int) -> None:
            self.update_range(val)
            self.append_status(f"Range 1: {int(val)}")

        def _on_range2(val: int) -> None:
            self.update_range(val)
            self.append_status(f"Range 2: {int(val)}")

        def _on_diff(val: int) -> None:
            self.append_status(f"Difference: {int(val)}")

        # Pass/fail wrappers
        def _on_pass() -> None:
            self.mark_passed()

        def _on_fail(reason: str) -> None:
            self.mark_failed(reason)

        def _on_abort(_reason: str) -> None:
            self.mark_aborted()

        # Bind
        assert self.controller is not None
        self._transport_sender = _safe_tx
        self.controller.command_requested = self._handle_controller_command_requested
        self.controller.status_changed = self.append_status
        self.controller.position_changed = self.update_position
        self.controller.range1_changed = _on_range1
        self.controller.range2_changed = _on_range2
        self.controller.difference_changed = _on_diff
        self.controller.test_passed = _on_pass
        self.controller.test_failed = _on_fail
        self.controller.test_aborted = _on_abort

    def _clear_middle_travel_state(self) -> None:
        self._middle_travel_active = False
        self._middle_travel_origin_position = None
        self._middle_travel_target_position = None
        self._middle_travel_display_value = None

    def _maybe_start_middle_travel_display(self, payload: list[int]) -> None:
        if len(payload) != 5 or payload[0] != 0x81:
            return
        target = int.from_bytes(bytes(payload[1:]), byteorder="big", signed=False)
        self._middle_travel_active = True
        self._middle_travel_target_position = target
        self._middle_travel_origin_position = self._last_position_value
        if self._middle_travel_origin_position is None:
            self._middle_travel_display_value = target
        else:
            self._middle_travel_display_value = abs(target - self._middle_travel_origin_position)
        self.append_status(f"Middle travel distance: {int(self._middle_travel_display_value)}")

    def _ensure_controller(self) -> None:
        if self.controller is None:
            # Local import to break circular dependency on module import
            from gui.workspace.controllers.single_axis_functional_test_controller import (
                SingleAxisFunctionalTestController,
            )
            self.controller = SingleAxisFunctionalTestController()
            self._wire_controller_callbacks()

    def _display_node_id(self) -> int | None:
        if self._active_node_id is not None:
            return int(self._active_node_id)
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            return None
        node_id, _node_name = node_data
        return int(node_id)

    def _runtime_interrupt_state(self) -> dict[str, object]:
        node_id = self._display_node_id()
        if node_id is None:
            return {"left_state": "unknown", "right_state": "unknown"}
        if self._bridge is not None and hasattr(self._bridge, "get_runtime_node_interrupt_state"):
            try:
                state = self._bridge.get_runtime_node_interrupt_state(node_id, create_if_missing=False)  # type: ignore[attr-defined]
                if isinstance(state, dict):
                    return state
            except Exception:
                pass
        return {"left_state": "unknown", "right_state": "unknown"}

    def _refresh_interrupt_leds(self) -> None:
        interrupt_state = self._runtime_interrupt_state()
        self._set_led_display_state(self.left_flag_led, str(interrupt_state.get("left_state", "unknown")))
        self._set_led_display_state(self.right_flag_led, str(interrupt_state.get("right_state", "unknown")))

    def _handle_selected_node_changed(self) -> None:
        combo_node_id = self._combo_selected_node_id()
        if (
            self._release_watch_helper is not None
            and self._release_watch_helper.is_active
            and combo_node_id != self._release_watch_helper.active_node_id
        ):
            self._cancel_release_watch("node_changed")
        self._refresh_interrupt_leds()

    def _attach_runtime_packet_listener(self) -> None:
        runtime_window = None
        if self._bridge is not None and hasattr(self._bridge, "get_runtime_window"):
            try:
                runtime_window = self._bridge.get_runtime_window(create_if_missing=False)  # type: ignore[attr-defined]
            except Exception:
                runtime_window = None
        if runtime_window is self._runtime_packet_window:
            return
        self._detach_runtime_packet_listener()
        self._runtime_packet_window = runtime_window
        if runtime_window is not None and hasattr(runtime_window, "packet_received"):
            runtime_window.packet_received.connect(self._handle_runtime_packet_event)

    def _detach_runtime_packet_listener(self) -> None:
        if self._runtime_packet_window is None:
            return
        try:
            self._runtime_packet_window.packet_received.disconnect(self._handle_runtime_packet_event)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self._runtime_packet_window = None

    def _handle_runtime_packet_event(self, packet: object) -> None:
        if not isinstance(packet, dict):
            return
        if packet.get("type") != "can_over_uart":
            return
        sender = packet.get("sender")
        display_node_id = self._display_node_id()
        if sender is None or display_node_id is None or int(sender) != int(display_node_id):
            return
        if int(packet.get("cmd", 0)) & 0xFF not in (0x81, 0xD8):
            return
        QTimer.singleShot(0, self._refresh_interrupt_leds)

    def _combo_selected_node_id(self) -> int | None:
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            return None
        node_id, _node_name = node_data
        return int(node_id)

    def _build_safe_transport_sender(self):
        def _safe_send(payload: list[int]) -> bool:
            self._tx_log.append(list(payload))
            hex_str = " ".join(f"{b:02X}" for b in payload)
            if payload == [0xDD] and self._active_node_id is not None:
                self.append_status(f"TX Node {self._active_node_id}: {hex_str}")
            else:
                self.append_status(f"TX requested: {hex_str}")
            return True

        return _safe_send

    @staticmethod
    def _build_live_transport_sender(adapter):
        def _live_send(payload: list[int]) -> bool:
            adapter.send(list(payload))
            return True

        return _live_send

    def _handle_controller_command_requested(self, payload: list[int]) -> None:
        sender = self._transport_sender
        if sender is None:
            return
        sent = False
        try:
            sent = bool(sender(list(payload)))
        except Exception as exc:
            self.append_status(f"[ReleaseWatch] Command send failed: {exc}")
            sent = False
        if not sent:
            self._log_release_watch_skip("command send failed")
            return
        self._maybe_start_middle_travel_display(payload)
        self._maybe_start_release_watch(payload)

    def _maybe_start_release_watch(self, payload: list[int]) -> None:
        if self._release_watch_helper is None:
            return
        sensor_or_reason = self._expected_release_watch_sensor(payload)
        if sensor_or_reason is None:
            return
        if sensor_or_reason not in {"L", "R"}:
            self._log_release_watch_skip(sensor_or_reason)
            return
        node_id = self._display_node_id()
        if node_id is None:
            self._log_release_watch_skip("no active node")
            return
        started = self._release_watch_helper.start_release_watch(
            node_id,
            sensor_or_reason,
            self._send_release_watch_query,
            on_released=self._on_release_watch_released,
            on_timeout=self._on_release_watch_timeout,
            on_stopped=self._on_release_watch_stopped,
        )
        if started:
            self.append_status(f"[ReleaseWatch] Started for Node {node_id} sensor {sensor_or_reason}")
        else:
            self._log_release_watch_skip("duplicate watch active")

    def _expected_release_watch_sensor(self, payload: list[int]) -> str | None:
        if not self._is_running:
            return "test not running"
        if self._release_watch_helper is not None and self._release_watch_helper.is_active:
            return "duplicate watch active"
        if self._active_node_id is None:
            return "no active node"
        sign = self._movement_sign_for_payload(payload)
        if sign is None:
            if payload and payload[0] in (0x88, 0x81):
                return "movement direction unknown"
            return None

        interrupt_state = self._runtime_interrupt_state()
        left_cut = interrupt_state.get("left_cut")
        right_cut = interrupt_state.get("right_cut")
        if left_cut is None or right_cut is None:
            return "unknown interrupt state"
        if left_cut is True and right_cut is True:
            return "both sensors cut"
        if left_cut is False and right_cut is False:
            return "no cut sensor"
        cut_sensor = "L" if left_cut is True and right_cut is False else "R" if right_cut is True and left_cut is False else None
        if cut_sensor is None:
            return "unknown interrupt state"

        polarity = self._runtime_motion_polarity()
        if not polarity.get("known"):
            return "unknown motion polarity"
        toward_sensor = polarity.get("positive_run_sensor") if sign > 0 else polarity.get("negative_run_sensor")
        if toward_sensor not in {"L", "R"}:
            return "movement direction unknown"
        if toward_sensor == cut_sensor:
            return "moving toward cut sensor"
        return str(cut_sensor)

    def _movement_sign_for_payload(self, payload: list[int]) -> int | None:
        if not payload:
            return None
        command = int(payload[0]) & 0xFF
        if command == 0x88 and len(payload) >= 3:
            raw = ((int(payload[1]) & 0xFF) << 8) | (int(payload[2]) & 0xFF)
            if raw & 0x8000:
                raw -= 0x10000
            if raw == 0:
                return None
            return 1 if raw > 0 else -1
        if command == 0x81 and len(payload) == 5 and self._last_position_value is not None:
            target = int.from_bytes(bytes(payload[1:5]), byteorder="big", signed=False)
            if target & 0x80000000:
                target -= 0x100000000
            delta = int(target) - int(self._last_position_value)
            if delta == 0:
                return None
            return 1 if delta > 0 else -1
        return None

    def _runtime_motion_polarity(self) -> dict[str, object]:
        node_id = self._display_node_id()
        if node_id is None:
            return {"known": False}
        if self._bridge is not None and hasattr(self._bridge, "get_runtime_node_motion_polarity"):
            try:
                result = self._bridge.get_runtime_node_motion_polarity(node_id, create_if_missing=False)  # type: ignore[attr-defined]
                if isinstance(result, dict):
                    return result
            except Exception:
                pass
        return {"known": False}

    def _send_release_watch_query(self, payload: list[int]) -> None:
        sender = self._transport_sender
        if sender is None:
            return
        sender(list(payload))

    def _cancel_release_watch(self, reason: str) -> None:
        if self._release_watch_helper is None:
            return
        self._release_watch_helper.stop_release_watch(str(reason))

    def _on_release_watch_released(self, node_id: int, sensor: str) -> None:
        self.append_status(f"[ReleaseWatch] Release detected for Node {node_id} sensor {sensor}")

    def _on_release_watch_timeout(self, node_id: int, sensor: str) -> None:
        self.append_status(f"[ReleaseWatch] Timeout waiting for Node {node_id} sensor {sensor}")

    def _on_release_watch_stopped(self, node_id: int, sensor: str, reason: str) -> None:
        if reason not in {"released", "timeout"}:
            self.append_status(f"[ReleaseWatch] Cancelled for Node {node_id} sensor {sensor}: {reason}")

    def _log_release_watch_skip(self, reason: str) -> None:
        self.append_status(f"[ReleaseWatch] Skipped: {reason}")
