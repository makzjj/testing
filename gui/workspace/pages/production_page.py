"""Production page implementation with runtime-backed ML 2.0 node testing."""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
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
from services.ipqc_excel_adapter import IpqcExcelAdapter
from services.production_csv_logger import ProductionCsvLogger
from .base_page import BaseWorkspacePage
from .production_parameter_controller import ProductionParameterController, parse_uuid_value
from .production_test_controller import ProductionTestController
from .production_test_models import StepResult

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
RUNTIME_POLL_INTERVAL_MS = 1000
WORKBOOK_OUTPUT_PENDING = "Pending"
PWM_COMMAND_SUPPORT_PENDING = "Pending command support"


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
        self._ipqc_excel_adapter = IpqcExcelAdapter()
        self._result_logger = ProductionCsvLogger()

        self.test_control_section.run_requested.connect(self._handle_run_test)
        self.test_control_section.stop_requested.connect(self._handle_stop_test)
        self.test_control_section.clear_requested.connect(self._handle_clear_result)
        self.uuid_section.load_workbook_requested.connect(self._handle_load_ipqc_workbook)
        self.uuid_section.sheet_group_changed.connect(self._handle_ipqc_sheet_group_changed)
        self.uuid_section.write_requested.connect(self._handle_write_uuid)
        self.uuid_section.verify_requested.connect(self._handle_verify_uuid)
        self.uuid_section.save_requested.connect(self._handle_save_completed_workbook)
        self.communication_section.connect_requested.connect(self._handle_connect_requested)
        self.communication_section.disconnect_requested.connect(self._handle_disconnect_requested)
        self.robot_nodes_section.node_selected.connect(self._handle_runtime_node_selected)
        self._test_controller.log_message.connect(self.console_message.emit)
        self._test_controller.test_started.connect(self._handle_test_started)
        self._test_controller.test_passed.connect(self._handle_test_passed)
        self._test_controller.test_failed.connect(self._handle_test_failed)
        self._test_controller.test_unsupported.connect(self._handle_test_unsupported)
        self._test_controller.test_aborted.connect(self._handle_test_aborted)
        self._test_controller.profile_started.connect(self._handle_profile_started)
        self._test_controller.step_finished.connect(self._handle_step_finished)
        self._test_controller.profile_finished.connect(self._handle_profile_finished)
        self._parameter_controller.log_message.connect(self.console_message.emit)
        self._parameter_controller.verification_finished.connect(self._handle_uuid_verification_finished)
        self._uuid_operation: str | None = None
        self._pending_expected_uuid: int | None = None

        self.add_weighted_row((self.communication_section, 1), (self.robot_nodes_section, 2))
        self.add_row(self.node_status_section, self.test_control_section)
        self.add_weighted_row((self.result_summary_section, 1), (self.progress_section, 2))
        self.add_full_width(self.uuid_section)

        self._runtime_poll_timer = QTimer(self)
        self._runtime_poll_timer.setInterval(RUNTIME_POLL_INTERVAL_MS)
        self._runtime_poll_timer.timeout.connect(self._refresh_runtime_panels)
        self._runtime_poll_timer.start()

        self.uuid_section.set_workbook_output_path(WORKBOOK_OUTPUT_PENDING)
        self.uuid_section.set_last_workbook_action("No workbook write yet")
        self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
        self._reset_result_only()
        self._refresh_runtime_panels()
        self._refresh_workbook_action_states()

    def refresh(self) -> None:
        """Refresh lightweight status without resetting operator state."""
        self._refresh_runtime_panels()

    def _refresh_runtime_panels(self) -> None:
        self._refresh_connection_status()
        self._refresh_robot_nodes()
        self._refresh_workbook_action_states()

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
        expected_uuid = self._get_workbook_expected_uuid()
        self._test_controller.run_test(node_id, node_name, expected_uuid=expected_uuid)
        self._refresh_connection_status()

    def _handle_stop_test(self) -> None:
        self._test_controller.abort_test()
        self._refresh_connection_status()

    def _handle_clear_result(self) -> None:
        if self._test_controller.is_active():
            self._test_controller.abort_test()
        self._reset_result_only()
        self.console_message.emit("[Production] Cleared result summary and progress")

    def _handle_load_ipqc_workbook(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Load IPQC Workbook",
            "",
            "Excel Files (*.xlsx *.xlsm)",
        )
        if not path:
            return

        try:
            groups = self._ipqc_excel_adapter.load_template(path)
            active_group = self._ipqc_excel_adapter.active_sheet_group or ""
            self.uuid_section.set_workbook_path(path)
            self.uuid_section.set_sheet_groups(groups, active_group)
            self._result_logger.set_output_dir(Path(path).expanduser().resolve().parent)
            self.uuid_section.set_workbook_output_path(WORKBOOK_OUTPUT_PENDING)
            self.uuid_section.set_last_workbook_action("Workbook loaded; no write performed yet")
            self._refresh_ipqc_expected_preview()
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to load IPQC workbook: {exc}")
            self.result_summary_section.set_result("FAIL", "IPQC workbook load failed.")
            self.progress_section.append_step("IPQC workbook load failed")
            self.uuid_section.set_workbook_validation(False, str(exc))
            self.uuid_section.set_last_workbook_action(f"Load failed: {exc}")
            self._refresh_workbook_action_states()
            return

        self.uuid_section.set_workbook_validation(True, "")
        self.console_message.emit(f"[Production] Loaded IPQC workbook: {path}")
        self.progress_section.append_step(f"Loaded IPQC workbook with {len(groups)} sheet group(s)")
        self.result_summary_section.set_result("READY", "IPQC workbook loaded.")
        self._refresh_workbook_action_states()

    def _handle_ipqc_sheet_group_changed(self, base_group: str) -> None:
        if not base_group:
            return
        try:
            self._ipqc_excel_adapter.select_sheet_group(base_group)
            self._refresh_ipqc_expected_preview()
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to select IPQC sheet group '{base_group}': {exc}")
            self.uuid_section.set_workbook_validation(False, str(exc))
            self._refresh_workbook_action_states()
            return
        self.uuid_section.set_workbook_validation(True, "")
        self._refresh_workbook_action_states()

    def _refresh_ipqc_expected_preview(self) -> None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            self.uuid_section.set_expected_values(serial_number="", pwm="", other_parameters="")
            self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
            return
        try:
            expected = self._ipqc_excel_adapter.read_expected_summary(strict=False)
        except Exception as exc:
            self.uuid_section.set_workbook_validation(False, str(exc))
            self.uuid_section.set_expected_values(serial_number="", pwm="", other_parameters="")
            self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
            self._refresh_workbook_action_states()
            return
        self.uuid_section.set_expected_values(
            expected.serial_number,
            expected.pwm,
            expected.other_parameters,
        )
        self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
        self._refresh_workbook_action_states()

    def _handle_write_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self.result_summary_section.set_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        expected_uuid = self._get_workbook_expected_uuid()
        if expected_uuid is None:
            message = "Expected S/N is unavailable from the active IPQC workbook sheet."
            self.result_summary_section.set_result("FAIL", message)
            self.progress_section.append_step("UUID write blocked: expected workbook S/N missing")
            self.console_message.emit(f"[Production] {message}")
            return

        self.result_summary_section.set_result("WRITING UUID", f"Writing UUID to Node {node_id} {node_name}.")
        success, message = self._parameter_controller.write_uuid(node_id, node_name, expected_uuid)
        if success:
            self.progress_section.append_step(f"UUID write sent for Node {node_id} {node_name}")
            self.result_summary_section.set_result("WRITE SENT", message)
            self.uuid_section.set_last_workbook_action("UUID write sent to MCU; awaiting read-back verification")
        else:
            self.result_summary_section.set_result("FAIL", message)
            self.progress_section.append_step(f"Failed to write UUID for Node {node_id} {node_name}")
            self.console_message.emit(f"[Production] {message}")
        self._uuid_operation = None
        self._pending_expected_uuid = None
        self._refresh_connection_status()

    def _handle_verify_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self.result_summary_section.set_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        expected_uuid = self._get_workbook_expected_uuid()
        if expected_uuid is None:
            message = "Expected S/N is unavailable from the active IPQC workbook sheet."
            self.result_summary_section.set_result("FAIL", message)
            self.progress_section.append_step("UUID verify blocked: expected workbook S/N missing")
            self.console_message.emit(f"[Production] {message}")
            return

        self._uuid_operation = "verify"
        self._pending_expected_uuid = expected_uuid
        self.result_summary_section.set_result("READING UUID", f"Reading and verifying UUID for Node {node_id} {node_name}.")
        started = self._parameter_controller.verify_uuid(node_id, node_name, expected_uuid)
        if started:
            self.progress_section.append_step(f"Started UUID read/verify for Node {node_id} {node_name}")
        else:
            self._uuid_operation = None
            self._pending_expected_uuid = None
        self._refresh_connection_status()

    def _handle_uuid_verification_finished(self, passed: bool, reason: str) -> None:
        operation = self._uuid_operation
        self._uuid_operation = None
        self._pending_expected_uuid = None
        actual_value = (
            self._parameter_controller.last_verify_actual_uuid
            if self._parameter_controller.last_verify_actual_uuid is not None
            else ""
        )
        if not passed and actual_value == "":
            mismatch = re.search(r"expected\s+(\d+),\s+got\s+(\d+)", reason)
            if mismatch is not None:
                actual_value = mismatch.group(2)
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
        check_text = "PASS" if passed else "FAIL"
        self.uuid_section.set_programmed_values(actual_value if actual_value != "" else "-", PWM_COMMAND_SUPPORT_PENDING, check_text)
        if self._ipqc_excel_adapter.has_loaded_workbook():
            self._update_uuid_cells_in_workbook_memory(actual_value, passed)

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
        self.progress_section.append_step(f"Started test profile for Node {node_id} {node_name}")

    def _handle_profile_started(self, _node_id: int, _node_name: str, step_names: object) -> None:
        names = [str(value) for value in step_names] if isinstance(step_names, list) else []
        self.progress_section.set_profile_steps(names)

    def _handle_step_finished(self, node_id: int, node_name: str, step_result: object) -> None:
        if not isinstance(step_result, StepResult):
            return
        self.progress_section.mark_profile_step(step_result.step_name, step_result.result)

    def _handle_test_passed(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Pass")
        self.result_summary_section.set_result("PASS", reason)
        self.progress_section.append_step(f"Completed test profile for Node {node_id} {node_name}")

    def _handle_test_failed(self, node_id: int, node_name: str, reason: str) -> None:
        is_timeout = "Timed out" in reason
        self.node_status_section.set_node_status(node_id, "Timeout" if is_timeout else "Fail")
        self.result_summary_section.set_result("TIMEOUT" if is_timeout else "FAIL", reason)
        self.progress_section.append_step(
            f"{'Timed out' if is_timeout else 'Failed'} test profile for Node {node_id} {node_name}"
        )

    def _handle_test_unsupported(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Unsupported")
        self.result_summary_section.set_result("UNSUPPORTED", reason)
        self.progress_section.append_step(f"Unsupported test for Node {node_id} {node_name}")

    def _handle_test_aborted(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Aborted")
        self.result_summary_section.set_result("ABORTED", reason)
        self.progress_section.append_step(f"Aborted test profile for Node {node_id} {node_name}")

    def _handle_profile_finished(self, _final_node_result: object) -> None:
        pass

    def _get_workbook_expected_uuid(self) -> int | None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return None
        try:
            expected = self._ipqc_excel_adapter.read_expected_summary(strict=False)
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to read expected workbook S/N: {exc}")
            return None
        serial_text = expected.serial_number.strip()
        if not serial_text:
            return None
        try:
            return parse_uuid_value(serial_text)
        except ValueError as exc:
            self.console_message.emit(f"[Production] Invalid workbook expected S/N '{serial_text}': {exc}")
            return None

    def _update_uuid_cells_in_workbook_memory(self, actual_value: str | int | None, passed: bool) -> bool:
        """Write UUID summary result into the loaded workbook object.

        Side effects:
        - Updates last workbook action labels.
        - Emits production console messages.
        - Sets result summary to REPORTING ERROR when write fails.

        Returns True only when workbook write/reporting succeeds.
        Returns False when no workbook is loaded or when write fails.
        """
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return False
        try:
            actual_value_or_empty: str | int = "" if actual_value is None else actual_value
            self._ipqc_excel_adapter.write_uuid_actual_and_check(actual_value_or_empty, "PASS" if passed else "FAIL")
            self.uuid_section.set_last_workbook_action("UUID report row updated in workbook memory")
            self.console_message.emit("[Production] IPQC workbook UUID report row updated in memory")
            return True
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to update IPQC workbook UUID report row: {exc}")
            self.progress_section.append_step("IPQC workbook UUID result write failed")
            self.uuid_section.set_last_workbook_action(f"UUID report row write failed: {exc}")
            self.result_summary_section.set_result(
                "REPORTING ERROR",
                "Device result is available, but writing IPQC workbook report failed.",
            )
            return False

    def _handle_save_completed_workbook(self) -> None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            self.result_summary_section.set_result("FAIL", "Load an IPQC workbook before saving a completed workbook.")
            self.console_message.emit("[Production] Save blocked: no IPQC workbook is loaded.")
            return
        suggested = self._ipqc_excel_adapter.suggest_completed_output_path()
        save_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Completed IPQC Workbook",
            str(suggested),
            "Excel Files (*.xlsx *.xlsm)",
        )
        if not save_path:
            return
        try:
            saved_path = self._ipqc_excel_adapter.save_completed_workbook(save_path)
            self.uuid_section.set_workbook_output_path(str(saved_path))
            self.uuid_section.set_last_workbook_action("Completed workbook saved")
            self.console_message.emit(f"[Production] Completed IPQC workbook saved: {saved_path}")
        except Exception as exc:
            self.uuid_section.set_last_workbook_action(f"Completed workbook save failed: {exc}")
            self.result_summary_section.set_result("REPORTING ERROR", "Failed to save completed IPQC workbook.")
            self.console_message.emit(f"[Production] Failed to save completed IPQC workbook: {exc}")

    def _refresh_workbook_action_states(self) -> None:
        can_use_workbook_uuid = self._has_workbook_expected_uuid()
        has_workbook = self._ipqc_excel_adapter.has_loaded_workbook()
        self.uuid_section.verify_button.setEnabled(can_use_workbook_uuid)
        self.uuid_section.write_button.setEnabled(can_use_workbook_uuid)
        self.uuid_section.save_button.setEnabled(has_workbook)

    def _has_workbook_expected_uuid(self) -> bool:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return False
        try:
            expected = self._ipqc_excel_adapter.read_expected_summary(strict=False)
        except (RuntimeError, ValueError):
            return False
        serial_text = expected.serial_number.strip()
        if not serial_text:
            return False
        return self._is_valid_uuid_text(serial_text)

    @staticmethod
    def _is_valid_uuid_text(serial_text: str) -> bool:
        try:
            parse_uuid_value(serial_text)
            return True
        except ValueError:
            return False


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
        self._table.setMinimumHeight(132)
        self._table.setMaximumHeight(198)
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
        self.table.setMinimumHeight(170)
        self.table.setMaximumHeight(238)
        self.body_layout.addWidget(self.table)
        for row_index in range(self.table.rowCount()):
            status_item = self.table.item(row_index, 2)
            if status_item is not None:
                self._apply_status_style(status_item, status_item.text())

    def set_node_status(self, node_id: int, status: str) -> None:
        row_index = self._row_by_node_id.get(node_id)
        if row_index is None:
            return
        item = QTableWidgetItem(status)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self._apply_status_style(item, status)
        self.table.setItem(row_index, 2, item)

    def _apply_status_style(self, item: QTableWidgetItem, status: str) -> None:
        normalized = status.strip().upper()
        font = item.font()
        font.setBold(normalized in {"PASS", "FAIL", "TESTING", "ABORTED", "TIMEOUT", "UNSUPPORTED"})
        item.setFont(font)
        if normalized == "PASS":
            item.setForeground(QColor("#2E7D32"))
        elif normalized == "FAIL":
            item.setForeground(QColor("#C62828"))
        elif normalized == "TESTING":
            item.setForeground(QColor("#D98732"))
        elif normalized in {"ABORTED", "TIMEOUT", "UNSUPPORTED"}:
            item.setForeground(QColor("#6F7783"))
        else:
            item.setForeground(QColor("#594C44"))


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
    load_workbook_requested = pyqtSignal()
    sheet_group_changed = pyqtSignal(str)
    write_requested = pyqtSignal()
    verify_requested = pyqtSignal()
    save_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("IPQC Workbook Parameter Programming", "")
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        load_workbook_button = QPushButton("Load IPQC Workbook")
        load_workbook_button.setProperty("tone", "primary")
        load_workbook_button.clicked.connect(self.load_workbook_requested.emit)
        button_row.addWidget(load_workbook_button)

        write_button = QPushButton("Write Parameters to MCU")
        write_button.setProperty("tone", "secondary")
        write_button.clicked.connect(self.write_requested.emit)
        button_row.addWidget(write_button)

        verify_button = QPushButton("Read Back / Verify")
        verify_button.setProperty("tone", "primary")
        verify_button.clicked.connect(self.verify_requested.emit)
        button_row.addWidget(verify_button)

        save_button = QPushButton("Save / Download Completed Workbook")
        save_button.setProperty("tone", "secondary")
        save_button.clicked.connect(self.save_requested.emit)
        button_row.addWidget(save_button)

        self.load_workbook_button = load_workbook_button
        self.verify_button = verify_button
        self.write_button = write_button
        self.save_button = save_button

        self.body_layout.addLayout(button_row)

        self._workbook_label = QLabel("Selected workbook: None")
        self._workbook_label.setObjectName("DetailValue")
        self._workbook_label.setWordWrap(True)
        self.body_layout.addWidget(self._workbook_label)

        self._sheet_group_combo = QComboBox()
        self._sheet_group_combo.setEnabled(False)
        self._sheet_group_combo.currentTextChanged.connect(self.sheet_group_changed.emit)
        self.body_layout.addWidget(LabeledControl("IPQC Sheet Group", self._sheet_group_combo))

        self._workbook_validation_label = QLabel("Workbook validation: Not loaded")
        self._workbook_validation_label.setObjectName("DetailValue")
        self._workbook_validation_label.setWordWrap(True)
        self.body_layout.addWidget(self._workbook_validation_label)

        self._expected_serial_label = QLabel("Expected S/N / UUID: -")
        self._expected_serial_label.setObjectName("DetailValue")
        self._expected_serial_label.setWordWrap(True)
        self.body_layout.addWidget(self._expected_serial_label)

        self._expected_pwm_label = QLabel("Expected PWM: -")
        self._expected_pwm_label.setObjectName("DetailValue")
        self._expected_pwm_label.setWordWrap(True)
        self.body_layout.addWidget(self._expected_pwm_label)

        self._expected_other_label = QLabel("Expected other parameters: -")
        self._expected_other_label.setObjectName("DetailValue")
        self._expected_other_label.setWordWrap(True)
        self.body_layout.addWidget(self._expected_other_label)

        self._actual_serial_label = QLabel("Programmed/read-back S/N: -")
        self._actual_serial_label.setObjectName("DetailValue")
        self._actual_serial_label.setWordWrap(True)
        self.body_layout.addWidget(self._actual_serial_label)

        self._actual_pwm_label = QLabel(f"Programmed/read-back PWM: {PWM_COMMAND_SUPPORT_PENDING}")
        self._actual_pwm_label.setObjectName("DetailValue")
        self._actual_pwm_label.setWordWrap(True)
        self.body_layout.addWidget(self._actual_pwm_label)

        self._check_result_label = QLabel("Check result: -")
        self._check_result_label.setObjectName("DetailValue")
        self._check_result_label.setWordWrap(True)
        self.body_layout.addWidget(self._check_result_label)

        self._workbook_output_label = QLabel("Completed workbook: Pending")
        self._workbook_output_label.setObjectName("DetailValue")
        self._workbook_output_label.setWordWrap(True)
        self.body_layout.addWidget(self._workbook_output_label)

        self._last_workbook_action_label = QLabel("Last workbook action: No workbook write yet")
        self._last_workbook_action_label.setObjectName("DetailValue")
        self._last_workbook_action_label.setWordWrap(True)
        self.body_layout.addWidget(self._last_workbook_action_label)

    def set_workbook_path(self, path: str) -> None:
        self._workbook_label.setText(f"Selected workbook: {path}")

    def set_sheet_groups(self, groups: list[str], selected: str) -> None:
        self._sheet_group_combo.blockSignals(True)
        self._sheet_group_combo.clear()
        for group in groups:
            self._sheet_group_combo.addItem(group)
        self._sheet_group_combo.setEnabled(bool(groups))
        if selected and groups:
            index = self._sheet_group_combo.findText(selected)
            if index >= 0:
                self._sheet_group_combo.setCurrentIndex(index)
        self._sheet_group_combo.blockSignals(False)
        if selected:
            self.sheet_group_changed.emit(selected)

    def set_expected_values(self, serial_number: str, pwm: str, other_parameters: str) -> None:
        self._expected_serial_label.setText(f"Expected S/N / UUID: {serial_number or '-'}")
        self._expected_pwm_label.setText(f"Expected PWM: {pwm or '-'}")
        self._expected_other_label.setText(f"Expected other parameters: {other_parameters or '-'}")

    def set_programmed_values(self, serial_number: str, pwm: str, check_result: str) -> None:
        self._actual_serial_label.setText(f"Programmed/read-back S/N: {serial_number or '-'}")
        self._actual_pwm_label.setText(f"Programmed/read-back PWM: {pwm or '-'}")
        self._check_result_label.setText(f"Check result: {check_result or '-'}")

    def set_workbook_validation(self, passed: bool, message: str) -> None:
        if passed:
            self._workbook_validation_label.setText("Workbook validation: PASSED")
            return
        reason = message or "FAILED"
        self._workbook_validation_label.setText(f"Workbook validation: FAILED ({reason})")

    def set_workbook_output_path(self, path_or_status: str) -> None:
        self._workbook_output_label.setText(f"Completed workbook: {path_or_status}")

    def set_last_workbook_action(self, status: str) -> None:
        self._last_workbook_action_label.setText(f"Last workbook action: {status}")


class _TestProgressSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Test Progress", "")
        self._list = QListWidget()
        self._list.setMinimumHeight(120)
        self._list.setMaximumHeight(176)
        self.body_layout.addWidget(self._list)
        self._profile_step_rows: dict[str, int] = {}

    def reset_steps(self, steps: list[str]) -> None:
        self._list.clear()
        self._list.addItems(steps)
        self._profile_step_rows = {}

    def set_profile_steps(self, step_names: list[str]) -> None:
        self._list.clear()
        self._profile_step_rows = {}
        for index, step_name in enumerate(step_names, start=1):
            text = f"{index}. {step_name} - PENDING"
            self._list.addItem(text)
            self._profile_step_rows[step_name] = index - 1

    def mark_profile_step(self, step_name: str, status: str) -> None:
        row_index = self._profile_step_rows.get(step_name)
        if row_index is None:
            self.append_step(f"{step_name} - {status}")
            return
        self._list.item(row_index).setText(f"{row_index + 1}. {step_name} - {status}")

    def append_step(self, step: str) -> None:
        self._list.addItem(step)
