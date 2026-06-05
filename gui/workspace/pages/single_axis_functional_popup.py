"""Compact Functional popup shell for future single-axis controller integration.

This UI dialog is intentionally controller-agnostic. It exposes public methods
that the future functional-test state machine/controller will call to update UI.
Do not add binary builders/parsers or controller logic here.
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QTimer, Qt
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

if TYPE_CHECKING:  # pragma: no cover - only for type checking to avoid circular import at runtime
    from gui.workspace.controllers.single_axis_functional_test_controller import (
        SingleAxisFunctionalTestController,
    )


class SingleAxisFunctionalPopup(QDialog):
    """Compact Functional popup for Single Axis Functional Test."""

    _INACTIVE_FLAG_COLOR = "#7A4D1F"
    _ACTIVE_FLAG_COLOR = "#FF8C00"

    def __init__(
        self,
        parent: QWidget | None = None,
        node_options: list[tuple[int, str]] | None = None,
        controller: Optional['SingleAxisFunctionalTestController'] = None,
        bridge: Optional[object] = None,
        allow_safe_tx: bool = False,
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
        # safe TX log for tests/inspection (no real hardware tx in this phase)
        self._tx_log: list[list[int]] = []
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

        self.reset_flags()

    # Public API used by controller/state-machine integration
    def append_status(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.status_block.append(f"[{timestamp}] {message}")

    def update_position(self, value: object) -> None:
        self.position_field.setText(str(value))

    def update_range(self, value: object) -> None:
        self.range_field.setText(str(value))

    def set_left_flag_active(self, active: bool) -> None:
        self._set_led_state(self.left_flag_led, active)

    def set_right_flag_active(self, active: bool) -> None:
        self._set_led_state(self.right_flag_led, active)

    def reset_flags(self) -> None:
        self.set_left_flag_active(False)
        self.set_right_flag_active(False)

    def mark_passed(self) -> None:
        node_text = self._selected_node_text()
        self.append_status(f"Node {node_text}: Functional test PASSED.")
        # Re-enable controls after finish
        self._finish_run_ui()
        # Handoff to sampling prompt (placeholder only)
        self.ask_start_sampling()

    def mark_failed(self, reason: str) -> None:
        from PyQt6.QtWidgets import QMessageBox  # local import to keep top clean

        node_text = self._selected_node_text()
        self.append_status(f"Node {node_text}: Functional test FAILED. Reason: {reason}")
        QMessageBox.warning(self, "Functional Test Failed", str(reason))
        self._finish_run_ui()

    def mark_aborted(self) -> None:
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
        super().closeEvent(event)

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
        self.update_position(0)
        self.update_range("-")
        self.reset_flags()

        # Add session separator
        self.append_status("— New functional test session —")
        self.append_status(f"Tolerance selected: {int(tolerance)} counts")
        # Start controller with real transport if available
        self._ensure_controller()
        assert self.controller is not None
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
                )
                # Attach RX routing if a runtime window exists
                if hasattr(adapter, "attach_runtime_window"):
                    adapter.attach_runtime_window(runtime_window)

                # Replace command sender to use the real transport
                self.controller.command_requested = adapter.send
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
        self._adapter = None
        self._active_node_id = None

    def _show_log_placeholder(self) -> None:
        log_text = self.status_block.toPlainText().strip() or "No status messages available."
        QMessageBox.information(self, "Functional Log", log_text)

    def _selected_node_text(self) -> str:
        node_data = self.node_combo.currentData()
        if not isinstance(node_data, tuple) or len(node_data) != 2:
            return "-"
        return str(node_data[0])

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
        cls._set_led_state(led, False)
        return led

    @classmethod
    def _set_led_state(cls, led: QLabel, active: bool) -> None:
        color = cls._ACTIVE_FLAG_COLOR if active else cls._INACTIVE_FLAG_COLOR
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
        def _safe_tx(payload: list[int]) -> None:
            self._tx_log.append(list(payload))
            hex_str = " ".join(f"{b:02X}" for b in payload)
            if payload == [0xDD] and self._active_node_id is not None:
                self.append_status(f"TX Node {self._active_node_id}: {hex_str}")
            else:
                self.append_status(f"TX requested: {hex_str}")

        # Range/diff helpers: update range label and append status for visibility
        def _on_range1(val: int) -> None:
            self.update_range(val)
            self.append_status(f"Range 1: {int(val)}")

        def _on_range2(val: int) -> None:
            self.update_range(val)
            self.append_status(f"Range 2: {int(val)}")

        def _on_diff(val: int) -> None:
            self.update_range(val)
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
        self.controller.command_requested = _safe_tx
        self.controller.status_changed = self.append_status
        self.controller.position_changed = self.update_position
        self.controller.range1_changed = _on_range1
        self.controller.range2_changed = _on_range2
        self.controller.difference_changed = _on_diff
        self.controller.left_flag_changed = self.set_left_flag_active
        self.controller.right_flag_changed = self.set_right_flag_active
        self.controller.test_passed = _on_pass
        self.controller.test_failed = _on_fail
        self.controller.test_aborted = _on_abort

    def _ensure_controller(self) -> None:
        if self.controller is None:
            # Local import to break circular dependency on module import
            from gui.workspace.controllers.single_axis_functional_test_controller import (
                SingleAxisFunctionalTestController,
            )
            self.controller = SingleAxisFunctionalTestController()
            self._wire_controller_callbacks()
