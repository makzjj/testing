"""Production page implementation with runtime-backed ML 2.0 node testing."""

from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QTableWidgetItem,
)

from ..bridges import WorkspaceRuntimeBridge
from ..models import DetailItem
from ..widgets import DetailListWidget, LabeledControl, PanelFrame, SimpleTableWidget
from ..widgets.layout_utils import clear_layout
from .base_page import BaseWorkspacePage
from .production_parameter_controller import ProductionParameterController
from .production_test_controller import ProductionTestController

# TODO(Phase 2/3): move ML 2.0 node mapping to project-config/model-aware constants.
# TODO(Phase 2/3): replace old hardcoded node lists in legacy pages with model-aware config.
# TODO(Phase 2/3): align ML2.0.yaml-driven node identities when config integration is prioritized.
# Fixed Phase 1 ML 2.0 production node identity map.
# Note: Node 2 is not part of the currently expected ML 2.0 production routing set.
ML20_NODE_MAP: dict[int, str] = {
    1: "MCU Master",
    3: "X",
    4: "Y",
    5: "V",
    6: "H",
    7: "NZ",
    8: "RZ",
    9: "PZ",
    10: "HMI",
    11: "NGActuator",
    12: "Z",
}
_ML20_NODE_ORDER: tuple[int, ...] = tuple(ML20_NODE_MAP)


def get_ml20_node_name(node_id: int) -> str:
    """Return the ML 2.0 display name for one node id."""
    return ML20_NODE_MAP.get(node_id, f"Node {node_id}")


def get_ml20_status_nodes() -> list[tuple[int, str]]:
    """Return all status-listed ML 2.0 nodes including MCU master."""
    return [(node_id, get_ml20_node_name(node_id)) for node_id in _ML20_NODE_ORDER]


def get_ml20_testable_nodes() -> list[tuple[int, str]]:
    """Return Production-selectable ML 2.0 test nodes (currently excluding Node 1 MCU Master)."""
    return [(node_id, get_ml20_node_name(node_id)) for node_id in _ML20_NODE_ORDER if node_id != 1]


class ProductionPage(BaseWorkspacePage):
    """Operator-focused Production page for runtime-backed node testing."""

    console_message = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Production", "Simple node-based quality control testing.")
        self._bridge = bridge

        self.communication_section = _CommunicationSection()
        self.robot_nodes_section = _RobotArmNodesSection()
        self.node_status_section = _NodeStatusSection()
        self.test_control_section = _TestControlSection()
        self.uuid_section = _UuidCsvSection()
        self.result_summary_section = _ResultSummarySection()
        self.progress_section = _TestProgressSection()
        self._test_controller = ProductionTestController(bridge)
        self._parameter_controller = ProductionParameterController(bridge, node_map=ML20_NODE_MAP)

        self.test_control_section.run_requested.connect(self._handle_run_test)
        self.test_control_section.stop_requested.connect(self._handle_stop_test)
        self.test_control_section.clear_requested.connect(self._handle_clear_result)
        self.uuid_section.load_csv_requested.connect(self._handle_load_uuid_csv)
        self.uuid_section.write_requested.connect(self._handle_write_uuid)
        self.uuid_section.verify_requested.connect(self._handle_verify_uuid)
        self.communication_section.connect_requested.connect(self._handle_connect_requested)
        self.communication_section.disconnect_requested.connect(self._handle_disconnect_requested)
        self.robot_nodes_section.node_selected.connect(self._handle_runtime_node_selected)
        self._test_controller.log_message.connect(self.console_message.emit)
        self._test_controller.test_started.connect(self._handle_test_started)
        self._test_controller.test_passed.connect(self._handle_test_passed)
        self._test_controller.test_failed.connect(self._handle_test_failed)
        self._test_controller.test_unsupported.connect(self._handle_test_unsupported)
        self._test_controller.test_aborted.connect(self._handle_test_aborted)
        self._parameter_controller.log_message.connect(self.console_message.emit)
        self._parameter_controller.verification_finished.connect(self._handle_uuid_verification_finished)
        self._uuid_operation: str | None = None

        self.add_row(self.communication_section, self.robot_nodes_section)
        self.add_row(self.node_status_section, self.test_control_section)
        self.add_full_width(self.uuid_section)
        self.add_full_width(self.result_summary_section)
        self.add_full_width(self.progress_section)

        self._runtime_poll_timer = QTimer(self)
        self._runtime_poll_timer.setInterval(1000)
        self._runtime_poll_timer.timeout.connect(self._refresh_runtime_panels)
        self._runtime_poll_timer.start()

        self._reset_result_only()
        self._refresh_runtime_panels()

    def refresh(self) -> None:
        """Refresh lightweight status without resetting operator state."""
        self._refresh_runtime_panels()

    def _refresh_runtime_panels(self) -> None:
        self._refresh_connection_status()
        self._refresh_robot_nodes()

    def _refresh_connection_status(self) -> None:
        communication_model = self._bridge.get_runtime_communication_model(create_if_missing=False)
        serial_connected = bool(communication_model.get("connected", False))
        self.communication_section.set_model(communication_model)
        if serial_connected:
            selected_port = communication_model.get("selected_port") or "Unknown"
            self.communication_section.set_status_text(f"● Connected ({selected_port})")
        else:
            self.communication_section.set_status_text("○ Disconnected")

    def _refresh_robot_nodes(self) -> None:
        nodes_model = self._bridge.get_runtime_robot_nodes(create_if_missing=False)
        self.robot_nodes_section.set_nodes(nodes_model)

    def _handle_connect_requested(self, port: str, baud_rate: int) -> None:
        if not port:
            self.console_message.emit("[Production] Select a serial port before connecting.")
            self._refresh_runtime_panels()
            return
        connected = self._bridge.connect_runtime_serial(port=port, baud_rate=baud_rate)
        if connected:
            self.console_message.emit(f"[Production] Connected to {port} @ {baud_rate}")
        else:
            self.console_message.emit(f"[Production] Failed to connect to {port} @ {baud_rate}")
        self._refresh_runtime_panels()

    def _handle_disconnect_requested(self) -> None:
        self._bridge.disconnect_runtime_serial()
        self.console_message.emit("[Production] Disconnected serial communication")
        self._refresh_runtime_panels()

    def _handle_runtime_node_selected(self, node_id: int) -> None:
        combo = self.test_control_section._combo
        for index in range(combo.count()):
            data = combo.itemData(index)
            if isinstance(data, tuple) and len(data) == 2 and int(data[0]) == node_id:
                combo.setCurrentIndex(index)
                return

    def _handle_run_test(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self.result_summary_section.set_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return
        self._test_controller.run_test(node_id, node_name)
        self._refresh_connection_status()

    def _handle_stop_test(self) -> None:
        self._test_controller.abort_test()
        self._refresh_connection_status()

    def _handle_clear_result(self) -> None:
        if self._test_controller.is_active():
            self._test_controller.abort_test()
        self._reset_result_only()
        self.console_message.emit("[Production] Cleared result summary and progress")

    def _handle_load_uuid_csv(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(self, "Load UUID CSV", "", "CSV Files (*.csv)")
        if not path:
            return

        valid = self._parameter_controller.load_uuid_csv(path)
        rows = self._parameter_controller.rows
        errors = self._parameter_controller.errors
        self.uuid_section.set_file_path(path)
        self.uuid_section.set_preview_rows(rows)
        self.uuid_section.set_validation(valid, errors)

        if valid:
            self.console_message.emit(f"[Production] Loaded UUID CSV: {path}")
            self.progress_section.append_step(f"Loaded UUID CSV with {len(rows)} row(s)")
            self.result_summary_section.set_result("READY", "UUID CSV validation passed.")
            self._refresh_connection_status()
        else:
            self.console_message.emit(f"[Production] UUID CSV validation failed: {path}")
            self.result_summary_section.set_result("FAIL", "UUID CSV validation failed.")
            self.progress_section.append_step("UUID CSV validation failed")
            self._refresh_connection_status()

    def _handle_write_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self.result_summary_section.set_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        self._uuid_operation = "write"
        self.result_summary_section.set_result("WRITING UUID", f"Writing UUID to Node {node_id} {node_name}.")
        success, message = self._parameter_controller.write_loaded_uuid(node_id, node_name)
        if success:
            self.progress_section.append_step(f"Started UUID write + read-back verification for Node {node_id} {node_name}")
        else:
            self._uuid_operation = None
            self.result_summary_section.set_result("FAIL", message)
            self.progress_section.append_step(f"Failed to write UUID for Node {node_id} {node_name}")
            self.console_message.emit(f"[Production] {message}")
        self._refresh_connection_status()

    def _handle_verify_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self.result_summary_section.set_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        self._uuid_operation = "verify"
        self.result_summary_section.set_result("READING UUID", f"Reading and verifying UUID for Node {node_id} {node_name}.")
        started = self._parameter_controller.verify_loaded_uuid(node_id, node_name)
        if started:
            self.progress_section.append_step(f"Started UUID read/verify for Node {node_id} {node_name}")
        else:
            self._uuid_operation = None
        self._refresh_connection_status()

    def _handle_uuid_verification_finished(self, passed: bool, reason: str) -> None:
        operation = self._uuid_operation
        self._uuid_operation = None
        if passed:
            self.result_summary_section.set_result("PASS", reason)
            if operation == "write":
                self.progress_section.append_step("UUID write + read-back verification passed")
            else:
                self.progress_section.append_step("UUID verification passed")
        else:
            self.result_summary_section.set_result("FAIL", reason)
            if operation == "write":
                self.progress_section.append_step("UUID write + read-back verification failed")
            else:
                self.progress_section.append_step("UUID verification failed")

    def _reset_result_only(self) -> None:
        self.result_summary_section.set_result("READY", "No test has been run yet.")
        self.progress_section.reset_steps(
            [
                "1. Waiting for node selection",
                "2. Waiting for Run Test",
            ]
        )

    def _handle_test_started(self, node_id: int, node_name: str) -> None:
        self.node_status_section.set_node_status(node_id, "Testing")
        self.result_summary_section.set_result("TESTING", f"Running Production test for Node {node_id} {node_name}.")
        self.progress_section.append_step(f"Started test for Node {node_id} {node_name}")

    def _handle_test_passed(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Pass")
        self.result_summary_section.set_result("PASS", reason)
        self.progress_section.append_step(f"Completed test for Node {node_id} {node_name}")

    def _handle_test_failed(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Fail")
        self.result_summary_section.set_result("FAIL", reason)
        self.progress_section.append_step(f"Failed test for Node {node_id} {node_name}")

    def _handle_test_unsupported(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Unsupported")
        self.result_summary_section.set_result("UNSUPPORTED", reason)
        self.progress_section.append_step(f"Unsupported test for Node {node_id} {node_name}")

    def _handle_test_aborted(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Aborted")
        self.result_summary_section.set_result("ABORTED", reason)
        self.progress_section.append_step(f"Aborted test for Node {node_id} {node_name}")


class _ConnectionStatusSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Connection Status", "")
        self._detail_list = DetailListWidget([])
        self.body_layout.addWidget(self._detail_list)


class _CommunicationSection(PanelFrame):
    connect_requested = pyqtSignal(str, int)
    disconnect_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Communication", "")
        self._port_combo = QComboBox()
        self._baud_combo = QComboBox()
        self._connect_button = QPushButton("Connect")
        self._status_label = QLabel("○ Disconnected")
        self._status_label.setObjectName("DetailValue")
        self._connected = False

        self.body_layout.addWidget(LabeledControl("Serial Port", self._port_combo))
        self.body_layout.addWidget(LabeledControl("Baud Rate", self._baud_combo))
        self._connect_button.clicked.connect(self._handle_toggle)
        self.body_layout.addWidget(self._connect_button)
        self.body_layout.addWidget(self._status_label)

    def set_model(self, model: dict) -> None:
        current_port = str(self._port_combo.currentData() or "")
        ports = model.get("ports", [])
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        for port_info in ports:
            label = str(port_info.get("label", ""))
            value = str(port_info.get("value", ""))
            self._port_combo.addItem(label, value)

        selected_port = str(model.get("selected_port") or current_port)
        if selected_port:
            for index in range(self._port_combo.count()):
                if str(self._port_combo.itemData(index) or "") == selected_port:
                    self._port_combo.setCurrentIndex(index)
                    break
        self._port_combo.blockSignals(False)

        selected_baud = str(model.get("selected_baud", "115200"))
        baud_rates = [str(rate) for rate in model.get("baud_rates", ["115200", "230400", "345600"])]
        self._baud_combo.blockSignals(True)
        self._baud_combo.clear()
        self._baud_combo.addItems(baud_rates)
        self._baud_combo.setCurrentText(selected_baud)
        self._baud_combo.blockSignals(False)

        self._connected = bool(model.get("connected", False))
        self._connect_button.setText("Disconnect" if self._connected else "Connect")
        self._port_combo.setEnabled(not self._connected)
        self._baud_combo.setEnabled(not self._connected)

    def set_status_text(self, text: str) -> None:
        self._status_label.setText(text)
        if text.startswith("●"):
            self._status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self._status_label.setStyleSheet("color: #808080; font-weight: bold;")

    def _handle_toggle(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
            return
        port = str(self._port_combo.currentData() or "")
        try:
            baud_rate = int(self._baud_combo.currentText())
        except ValueError:
            baud_rate = 115200
        self.connect_requested.emit(port, baud_rate)


class _RobotArmNodesSection(PanelFrame):
    node_selected = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__("Robot Arm Nodes", "")
        self._connected_label = QLabel("Connected nodes: None")
        self._connected_label.setObjectName("DetailValue")
        self._headers = ["Node", "Firmware", "Serial(UUID)", "Node Type", "Status"]
        self._table = SimpleTableWidget(self._headers, [])
        self._row_node_ids: list[int] = []
        self._table.cellClicked.connect(self._handle_cell_clicked)
        self.body_layout.addWidget(self._connected_label)
        self.body_layout.addWidget(self._table)

    def set_nodes(self, nodes_model: dict) -> None:
        connected_nodes = [int(node_id) for node_id in nodes_model.get("connected_nodes", [])]
        rows = list(nodes_model.get("rows", []))
        if connected_nodes:
            self._connected_label.setText(f"Connected nodes: {', '.join(str(node) for node in connected_nodes)}")
            self._connected_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self._connected_label.setText("Connected nodes: None")
            self._connected_label.setStyleSheet("color: red; font-weight: bold;")

        self._row_node_ids = []
        self._table.clearSpans()
        for row in rows:
            node_id = int(row.get("node_id", 0))
            self._row_node_ids.append(node_id)
        if not rows:
            self._table.setRowCount(1)
            for column in range(len(self._headers)):
                empty_item = QTableWidgetItem("")
                empty_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(0, column, empty_item)
            message_item = QTableWidgetItem("No connected nodes")
            message_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._table.setItem(0, 0, message_item)
            self._table.setSpan(0, 0, 1, len(self._headers))
            return

        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                str(row.get("node", "")),
                str(row.get("firmware", "")),
                str(row.get("uuid", "")),
                str(row.get("node_type", "")),
                str(row.get("status", "")),
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(row_index, column_index, item)

    def _handle_cell_clicked(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._row_node_ids):
            return
        self.node_selected.emit(self._row_node_ids[row])

    def set_status(self, *, serial_connected: bool, mcu_connected: bool) -> None:
        clear_layout(self.body_layout)
        serial_text = "● Connected" if serial_connected else "○ Disconnected"
        mcu_text = "● Connected" if mcu_connected else "○ Not Connected"
        self._detail_list = DetailListWidget(
            [
                DetailItem("Serial Connection", serial_text),
                DetailItem("MCU Master", mcu_text),
            ]
        )
        self.body_layout.addWidget(self._detail_list)


class _NodeStatusSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Node Status", "")
        status_nodes = get_ml20_status_nodes()
        rows = [[str(node_id), node_name, "Not Tested"] for node_id, node_name in status_nodes]
        self._row_by_node_id = {node_id: row_index for row_index, (node_id, _name) in enumerate(status_nodes)}
        self.table = SimpleTableWidget(["Node ID", "Node Name", "Status"], rows)
        self.body_layout.addWidget(self.table)

    def set_node_status(self, node_id: int, status: str) -> None:
        row_index = self._row_by_node_id.get(node_id)
        if row_index is None:
            return
        item = QTableWidgetItem(status)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row_index, 2, item)


class _TestControlSection(PanelFrame):
    run_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Test Control", "")
        self._combo = QComboBox()
        self._combo.setObjectName("AxisSelectorCombo")
        for node_id, node_name in get_ml20_testable_nodes():
            self._combo.addItem(f"Node {node_id} - {node_name}", (node_id, node_name))
        self.body_layout.addWidget(LabeledControl("Selected Node", self._combo))

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        run_button = QPushButton("Run Test")
        run_button.setProperty("tone", "primary")
        run_button.clicked.connect(self.run_requested.emit)
        button_row.addWidget(run_button)

        stop_button = QPushButton("Stop")
        stop_button.setProperty("tone", "danger")
        stop_button.clicked.connect(self.stop_requested.emit)
        button_row.addWidget(stop_button)

        self.body_layout.addLayout(button_row)

        clear_button = QPushButton("Clear Result")
        clear_button.setProperty("tone", "secondary")
        clear_button.clicked.connect(self.clear_requested.emit)
        self.body_layout.addWidget(clear_button)

    def selected_node(self) -> tuple[int, str]:
        selected = self._combo.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            fallback_nodes = get_ml20_testable_nodes()
            if fallback_nodes:
                return fallback_nodes[0]
            raise RuntimeError("No ML 2.0 testable nodes configured for Production.")
        node_id, node_name = selected
        return int(node_id), str(node_name)


class _ResultSummarySection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Result Summary", "")
        self._status_label = QLabel("READY")
        self._status_label.setObjectName("MetricValue")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addWidget(self._status_label)

        self._reason_label = QLabel("Reason: No test has been run yet.")
        self._reason_label.setObjectName("DetailValue")
        self._reason_label.setWordWrap(True)
        self.body_layout.addWidget(self._reason_label)

    def set_result(self, status: str, reason: str) -> None:
        self._status_label.setText(status)
        self._reason_label.setText(f"Reason: {reason}")


class _UuidCsvSection(PanelFrame):
    load_csv_requested = pyqtSignal()
    write_requested = pyqtSignal()
    verify_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("UUID CSV", "")
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        load_button = QPushButton("Load UUID CSV")
        load_button.setProperty("tone", "primary")
        load_button.clicked.connect(self.load_csv_requested.emit)
        button_row.addWidget(load_button)

        verify_button = QPushButton("Verify Current UUID")
        verify_button.setProperty("tone", "primary")
        verify_button.clicked.connect(self.verify_requested.emit)
        button_row.addWidget(verify_button)

        write_button = QPushButton("Write UUID to PCB")
        write_button.setProperty("tone", "secondary")
        write_button.clicked.connect(self.write_requested.emit)
        button_row.addWidget(write_button)

        self.load_button = load_button
        self.verify_button = verify_button
        self.write_button = write_button

        self.body_layout.addLayout(button_row)

        self._file_label = QLabel("Selected CSV: None")
        self._file_label.setObjectName("DetailValue")
        self._file_label.setWordWrap(True)
        self.body_layout.addWidget(self._file_label)

        self._validation_label = QLabel("Validation: Not loaded")
        self._validation_label.setObjectName("DetailValue")
        self._validation_label.setWordWrap(True)
        self.body_layout.addWidget(self._validation_label)

        self._error_list = QListWidget()
        self._error_list.setObjectName("SimpleList")
        self.body_layout.addWidget(self._error_list)

        self._preview_table: SimpleTableWidget = SimpleTableWidget(["Node ID", "Node Name", "UUID"], [])
        self.body_layout.addWidget(self._preview_table)

    def set_file_path(self, path: str) -> None:
        self._file_label.setText(f"Selected CSV: {path}")

    def set_preview_rows(self, rows) -> None:
        if self._preview_table is not None:
            self.body_layout.removeWidget(self._preview_table)
            self._preview_table.deleteLater()
        table_rows = [[str(row.node_id), row.node_name, row.uuid_text] for row in rows]
        self._preview_table = SimpleTableWidget(["Node ID", "Node Name", "UUID"], table_rows)
        self.body_layout.addWidget(self._preview_table)

    def set_validation(self, passed: bool, errors: list[str]) -> None:
        self._validation_label.setText("Validation: PASSED" if passed else "Validation: FAILED")
        self._error_list.clear()
        if errors:
            self._error_list.addItems(errors)


class _TestProgressSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Test Progress", "")
        self._list = QListWidget()
        self.body_layout.addWidget(self._list)

    def reset_steps(self, steps: list[str]) -> None:
        self._list.clear()
        self._list.addItems(steps)

    def append_step(self, step: str) -> None:
        self._list.addItem(step)
