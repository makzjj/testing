"""Production page implementation with runtime-backed ML 2.0 node testing."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QPushButton, QTableWidgetItem

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

        self.connection_section = _ConnectionStatusSection()
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
        self._test_controller.log_message.connect(self.console_message.emit)
        self._test_controller.test_started.connect(self._handle_test_started)
        self._test_controller.test_passed.connect(self._handle_test_passed)
        self._test_controller.test_failed.connect(self._handle_test_failed)
        self._test_controller.test_unsupported.connect(self._handle_test_unsupported)
        self._test_controller.test_aborted.connect(self._handle_test_aborted)
        self._parameter_controller.log_message.connect(self.console_message.emit)
        self._parameter_controller.verification_finished.connect(self._handle_uuid_verification_finished)
        self._uuid_operation: str | None = None

        self.add_full_width(self.connection_section)
        self.add_row(self.node_status_section, self.test_control_section)
        self.add_full_width(self.uuid_section)
        self.add_full_width(self.result_summary_section)
        self.add_full_width(self.progress_section)

        self._reset_result_only()
        self._refresh_connection_status()

    def refresh(self) -> None:
        """Refresh lightweight status without resetting operator state."""
        self._refresh_connection_status()

    def _refresh_connection_status(self) -> None:
        serial_connected, mcu_connected = self._bridge.get_runtime_connection_state()
        self.connection_section.set_status(serial_connected=serial_connected, mcu_connected=mcu_connected)

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
