"""Production page implementation with runtime-backed ML 2.0 node testing."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextOption
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
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
        self.info_section = self.communication_section
        self.robot_nodes_section = self.communication_section
        self.test_control_section = self.communication_section
        self.uuid_section = _UuidCsvSection()
        self.stage_section = _TestStagesSection()
        self.node_status_section = _NodeStatusSection()
        self.result_summary_section = _ResultSummarySection()
        self.progress_section = _TestProgressSection()
        self._test_controller = ProductionTestController(bridge)
        self._parameter_controller = ProductionParameterController(bridge, node_map=ML20_NODE_MAP)
        self._ipqc_excel_adapter = IpqcExcelAdapter()
        self._result_logger = ProductionCsvLogger()
        self._last_status_entry = ""

        self.stage_section.configuration_requested.connect(self._handle_run_test)
        self.stage_section.single_axis_requested.connect(self._handle_single_axis_test_requested)
        self.stage_section.performance_requested.connect(self._handle_performance_test_requested)
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
        self.progress_section.refresh_requested.connect(self.refresh)
        self.progress_section.clear_requested.connect(self._handle_clear_progress_log)
        self._uuid_operation: str | None = None
        self._pending_expected_uuid: int | None = None

        self.add_weighted_row((self.communication_section, 3), (self.stage_section, 2))
        self.add_full_width(self.uuid_section)
        self.add_full_width(self.progress_section)

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
        self.progress_section.append_step("Refreshed Production status view")

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
            self.progress_section.append_step("Serial port not connected", level="error")
            self._refresh_runtime_panels()
            return
        connected = self._bridge.connect_runtime_serial(port=port, baud_rate=baud_rate)
        if connected:
            self.console_message.emit(f"[Production] Connected to {port} @ {baud_rate}")
            self.progress_section.append_step(f"Connected to {port} @ {baud_rate}", level="success")
        else:
            self.console_message.emit(f"[Production] Failed to connect to {port} @ {baud_rate}")
            self.progress_section.append_step(f"Failed to connect to {port} @ {baud_rate}", level="error")
        self._refresh_runtime_panels()

    def _handle_disconnect_requested(self) -> None:
        self._bridge.disconnect_runtime_serial()
        self.console_message.emit("[Production] Disconnected serial communication")
        self.progress_section.append_step("Serial port not connected", level="error")
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
            self._set_status_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return
        expected_uuid = None
        expected_uuid_text = self._get_workbook_expected_uuid_text()
        if expected_uuid_text:
            try:
                expected_uuid = parse_uuid_value(expected_uuid_text)
            except ValueError:
                expected_uuid = None
        self._test_controller.run_test(node_id, node_name, expected_uuid=expected_uuid)
        self._refresh_connection_status()

    def _handle_stop_test(self) -> None:
        self._test_controller.abort_test()
        self._refresh_connection_status()

    def _handle_single_axis_test_requested(self) -> None:
        self.progress_section.append_step("Single Axis Functional Test UI is present but command flow is not enabled yet")

    def _handle_performance_test_requested(self) -> None:
        self.progress_section.append_step("Performance Test UI is present but command flow is not enabled yet")

    def _handle_clear_result(self) -> None:
        if self._test_controller.is_active():
            self._test_controller.abort_test()
        self._reset_result_only()
        self.console_message.emit("[Production] Cleared result summary and progress")

    def _handle_clear_progress_log(self) -> None:
        self.progress_section.clear_log()

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
            self._set_status_result("FAIL", "IPQC workbook load failed.")
            self.progress_section.append_step("IPQC workbook load failed", level="error")
            self.uuid_section.set_workbook_validation(False, str(exc))
            self.uuid_section.set_last_workbook_action(f"Load failed: {exc}")
            self._refresh_workbook_action_states()
            return

        self.uuid_section.set_workbook_validation(True, "")
        self.console_message.emit(f"[Production] Loaded IPQC workbook: {path}")
        self.progress_section.append_step(f"Loaded IPQC workbook with {len(groups)} sheet group(s)", level="success")
        self._set_status_result("READY", "IPQC workbook loaded.")
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
            expected_serial = self._ipqc_excel_adapter.read_expected_uuid_serial()
            expected_pwm = self._ipqc_excel_adapter.read_expected_pwm_value()
        except Exception as exc:
            self.uuid_section.set_workbook_validation(False, str(exc))
            self.uuid_section.set_expected_values(serial_number="", pwm="", other_parameters="")
            self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
            self._refresh_workbook_action_states()
            return
        self.uuid_section.set_expected_values(
            expected_serial,
            expected_pwm,
            "",
        )
        self.uuid_section.set_programmed_values("-", PWM_COMMAND_SUPPORT_PENDING, "-")
        self.progress_section.append_step(f"Workbook validation: {self.uuid_section.workbook_validation_text}")
        self.progress_section.append_step(f"Expected S/N / UUID: {expected_serial or '-'}")
        self.progress_section.append_step(f"Expected PWM: {expected_pwm or '-'}")
        self._refresh_workbook_action_states()

    def _handle_write_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self._set_status_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        expected_uuid_text = self._get_workbook_expected_uuid_text()
        if expected_uuid_text is None:
            message = "Expected S/N is unavailable from the active IPQC workbook sheet."
            self._set_status_result("FAIL", message)
            self.progress_section.append_step("UUID write blocked: expected workbook S/N missing")
            self.console_message.emit(f"[Production] {message}")
            return
        try:
            expected_uuid = parse_uuid_value(expected_uuid_text)
        except ValueError as exc:
            message = f"Expected S/N in workbook B4 is invalid: {exc}"
            self._set_status_result("FAIL", message)
            self.progress_section.append_step("UUID write blocked: expected workbook S/N invalid")
            self.console_message.emit(f"[Production] {message}")
            return

        self._set_status_result("WRITING UUID", f"Writing UUID to Node {node_id} {node_name}.")
        success, message = self._parameter_controller.write_uuid(
            node_id,
            node_name,
            expected_uuid,
            expected_uuid_text=expected_uuid_text,
        )
        if success:
            self.progress_section.append_step(f"UUID write sent for Node {node_id} {node_name}")
            self._set_status_result("WRITE SENT", message)
            self.uuid_section.set_last_workbook_action("UUID write sent to MCU; awaiting read-back verification")
            self.progress_section.append_step(f"Last workbook action: {self.uuid_section.last_workbook_action_text}")
            self._report_pwm_write_readiness()
        else:
            self._set_status_result("FAIL", message)
            self.progress_section.append_step(f"Failed to write UUID for Node {node_id} {node_name}")
            self.console_message.emit(f"[Production] {message}")
        self._uuid_operation = None
        self._pending_expected_uuid = None
        self._refresh_connection_status()

    def _handle_verify_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self._set_status_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        expected_uuid_text = self._get_workbook_expected_uuid_text()
        if expected_uuid_text is None:
            message = "Expected S/N is unavailable from the active IPQC workbook sheet."
            self._set_status_result("FAIL", message)
            self.progress_section.append_step("UUID verify blocked: expected workbook S/N missing")
            self.console_message.emit(f"[Production] {message}")
            return
        try:
            expected_uuid = parse_uuid_value(expected_uuid_text)
        except ValueError as exc:
            message = f"Expected S/N in workbook B4 is invalid: {exc}"
            self._set_status_result("FAIL", message)
            self.progress_section.append_step("UUID verify blocked: expected workbook S/N invalid")
            self.console_message.emit(f"[Production] {message}")
            return

        self._uuid_operation = "verify"
        self._pending_expected_uuid = expected_uuid
        self._set_status_result("READING UUID", f"Reading and verifying UUID for Node {node_id} {node_name}.")
        started = self._parameter_controller.verify_uuid(
            node_id,
            node_name,
            expected_uuid,
            expected_uuid_text=expected_uuid_text,
        )
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
            self._parameter_controller.last_verify_actual_uuid_text
            if self._parameter_controller.last_verify_actual_uuid_text
            else ""
        )
        if passed:
            self._set_status_result("PASS", reason)
            if operation == "write":
                self.progress_section.append_step("UUID write + read-back verification passed")
            else:
                self.progress_section.append_step("UUID verification passed")
        else:
            self._set_status_result("FAIL", reason)
            if operation == "write":
                self.progress_section.append_step("UUID write + read-back verification failed")
            else:
                self.progress_section.append_step("UUID verification failed")
        check_text = "PASS" if passed else "FAIL"
        self.uuid_section.set_programmed_values(actual_value if actual_value != "" else "-", PWM_COMMAND_SUPPORT_PENDING, check_text)
        self.progress_section.append_step(f"Programmed/read-back S/N: {actual_value if actual_value != '' else '-'}")
        self.progress_section.append_step(f"Programmed/read-back PWM: {PWM_COMMAND_SUPPORT_PENDING}")
        self.progress_section.append_step(f"Check result: {check_text}")
        if self._ipqc_excel_adapter.has_loaded_workbook():
            self._update_uuid_cells_in_workbook_memory(actual_value, passed)

    def _reset_result_only(self) -> None:
        self._set_status_result("READY", "No test has been run yet.", append_to_log=False)
        self.progress_section.reset_steps(
            [
                "Waiting for workbook or test actions",
                "Use Refresh to reload visible runtime data",
            ]
        )
        self.stage_section.reset_stage_states()

    def _handle_test_started(self, node_id: int, node_name: str) -> None:
        self.node_status_section.set_node_status(node_id, "Testing")
        self.stage_section.set_stage_status("configuration", "testing")
        self._set_status_result("TESTING", f"Running Production test for Node {node_id} {node_name}.")
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
        self.stage_section.set_stage_status("configuration", "pass")
        self._set_status_result("PASS", reason)
        self.progress_section.append_step(f"Completed test profile for Node {node_id} {node_name}")

    def _handle_test_failed(self, node_id: int, node_name: str, reason: str) -> None:
        is_timeout = "Timed out" in reason
        self.node_status_section.set_node_status(node_id, "Timeout" if is_timeout else "Fail")
        self.stage_section.set_stage_status("configuration", "fail")
        self._set_status_result("TIMEOUT" if is_timeout else "FAIL", reason)
        self.progress_section.append_step(
            f"{'Timed out' if is_timeout else 'Failed'} test profile for Node {node_id} {node_name}"
        )

    def _handle_test_unsupported(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Unsupported")
        self.stage_section.set_stage_status("configuration", "neutral")
        self._set_status_result("UNSUPPORTED", reason)
        self.progress_section.append_step(f"Unsupported test for Node {node_id} {node_name}")

    def _handle_test_aborted(self, node_id: int, node_name: str, reason: str) -> None:
        self.node_status_section.set_node_status(node_id, "Aborted")
        self.stage_section.set_stage_status("configuration", "neutral")
        self._set_status_result("ABORTED", reason)
        self.progress_section.append_step(f"Aborted test profile for Node {node_id} {node_name}")

    def _handle_profile_finished(self, _final_node_result: object) -> None:
        pass

    def _get_workbook_expected_uuid_text(self) -> str | None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return None
        try:
            serial_text = self._ipqc_excel_adapter.read_expected_uuid_serial()
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to read expected workbook S/N: {exc}")
            return None
        if not serial_text:
            return None
        return serial_text

    def _get_workbook_expected_pwm_text(self) -> str | None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return None
        try:
            pwm_text = self._ipqc_excel_adapter.read_expected_pwm_value()
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to read expected workbook PWM: {exc}")
            return None
        if not pwm_text:
            return None
        return pwm_text

    @staticmethod
    def _parse_pwm_value(pwm_text: str) -> int:
        text = str(pwm_text).strip()
        if not text:
            raise ValueError("PWM value is required.")
        if not text.isdigit():
            raise ValueError("PWM value must contain digits only.")
        return int(text, 10)

    def _report_pwm_write_readiness(self) -> None:
        pwm_text = self._get_workbook_expected_pwm_text()
        if pwm_text is None:
            message = "PWM write blocked: expected PWM is unavailable from workbook B5. Command path remains pending."
            self.progress_section.append_step(message, level="error")
            self.console_message.emit(f"[Production] {message}")
            return
        try:
            expected_pwm = self._parse_pwm_value(pwm_text)
        except ValueError as exc:
            message = f"PWM write blocked: expected PWM in workbook B5 is invalid ({exc}). Command path remains pending."
            self.progress_section.append_step(message, level="error")
            self.console_message.emit(f"[Production] {message}")
            return
        message = (
            f"PWM command support pending: expected PWM {expected_pwm} loaded from B5, "
            "but firmware write/read-back command path is not yet confirmed."
        )
        self.progress_section.append_step(message)
        self.console_message.emit(f"[Production] {message}")

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
            self.progress_section.append_step(f"Last workbook action: {self.uuid_section.last_workbook_action_text}")
            return True
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to update IPQC workbook UUID report row: {exc}")
            self.progress_section.append_step("IPQC workbook UUID result write failed")
            self.uuid_section.set_last_workbook_action(f"UUID report row write failed: {exc}")
            self._set_status_result(
                "REPORTING ERROR",
                "Device result is available, but writing IPQC workbook report failed.",
            )
            return False

    def _handle_save_completed_workbook(self) -> None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            self._set_status_result("FAIL", "Load an IPQC workbook before saving a completed workbook.")
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
            self.progress_section.append_step(f"Completed workbook: {saved_path}")
            self.progress_section.append_step(f"Last workbook action: {self.uuid_section.last_workbook_action_text}")
        except Exception as exc:
            self.uuid_section.set_last_workbook_action(f"Completed workbook save failed: {exc}")
            self._set_status_result("REPORTING ERROR", "Failed to save completed IPQC workbook.")
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
            serial_text = self._ipqc_excel_adapter.read_expected_uuid_serial()
        except (RuntimeError, ValueError):
            return False
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

    def _set_status_result(self, status: str, reason: str, *, append_to_log: bool = True) -> None:
        self.result_summary_section.set_result(status, reason)
        entry = f"[{status}] {reason}"
        if append_to_log and entry != self._last_status_entry:
            level = "info"
            normalized = status.strip().upper()
            if normalized in {"PASS", "WRITE SENT"}:
                level = "success"
            elif normalized in {"FAIL", "TIMEOUT", "REPORTING ERROR"}:
                level = "error"
            self.progress_section.append_step(entry, level=level)
        self._last_status_entry = entry


class _ConnectionStatusSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Connection Status", "")
        self._detail_list = DetailListWidget([])
        self.body_layout.addWidget(self._detail_list)


class _CommunicationSection(PanelFrame):
    connect_requested = pyqtSignal(str, int)
    disconnect_requested = pyqtSignal()
    node_selected = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__("Communication", "")
        self._port_combo = QComboBox()
        self._baud_combo = QComboBox()
        self._connect_button = QPushButton("Connect")
        self._status_label = QLabel("○ Disconnected")
        self._status_label.setObjectName("DetailValue")
        self._connected = False
        self._firmware_value = "-"
        self._connected_nodes_value = "0"

        self._combo = QComboBox()
        self._combo.setObjectName("AxisSelectorCombo")
        for node_id, node_name in get_ml20_testable_nodes():
            self._combo.addItem(f"Node {node_id} - {node_name}", (node_id, node_name))

        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(8)
        top_grid.setVerticalSpacing(6)
        top_grid.addWidget(LabeledControl("COM Port", self._port_combo), 0, 0)
        top_grid.addWidget(LabeledControl("Baud Rate", self._baud_combo), 0, 1)
        top_grid.addWidget(LabeledControl("Selected Node", self._combo), 1, 0, 1, 2)
        self.body_layout.addLayout(top_grid)

        self._connect_button.clicked.connect(self._handle_toggle)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addWidget(self._connect_button)
        button_row.addWidget(self._status_label, 1)
        self.body_layout.addLayout(button_row)

        self._firmware_label = QLabel("MCU Firmware Version: -")
        self._firmware_label.setObjectName("DetailValue")
        self.body_layout.addWidget(self._firmware_label)

        self._connected_label = QLabel("No. of Connection / Connected Nodes: 0")
        self._connected_label.setObjectName("DetailValue")
        self.body_layout.addWidget(self._connected_label)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

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

    def set_nodes(self, nodes_model: dict) -> None:
        connected_nodes = [int(node_id) for node_id in nodes_model.get("connected_nodes", [])]
        rows = list(nodes_model.get("rows", []))
        self._connected_nodes_value = str(len(connected_nodes))
        self._connected_label.setText(
            f"No. of Connection / Connected Nodes: {self._connected_nodes_value}"
            + (f" ({', '.join(str(node) for node in connected_nodes)})" if connected_nodes else "")
        )
        firmware_values = [str(row.get("firmware", "")).strip() for row in rows if str(row.get("firmware", "")).strip()]
        self._firmware_value = firmware_values[0] if firmware_values else "-"
        self._firmware_label.setText(f"MCU Firmware Version: {self._firmware_value}")

    def selected_node(self) -> tuple[int, str]:
        selected = self._combo.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            fallback_nodes = get_ml20_testable_nodes()
            if fallback_nodes:
                return fallback_nodes[0]
            raise RuntimeError("No ML 2.0 testable nodes configured for Production.")
        node_id, node_name = selected
        return int(node_id), str(node_name)

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


class _ProductionInfoSection(PanelFrame):
    connect_requested = pyqtSignal(str, int)
    disconnect_requested = pyqtSignal()
    node_selected = pyqtSignal(int)
    load_workbook_requested = pyqtSignal()
    sheet_group_changed = pyqtSignal(str)
    write_requested = pyqtSignal()
    verify_requested = pyqtSignal()
    save_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Information / Workbook / Communication", "")
        self._port_combo = QComboBox()
        self._baud_combo = QComboBox()
        self._connect_button = QPushButton("Connect")
        self._status_label = QLabel("○ Disconnected")
        self._status_label.setObjectName("DetailValue")
        self._connected = False
        self._firmware_value = "-"
        self._connected_nodes_value = "0"
        self._workbook_validation_text = "Workbook validation: Not loaded"
        self._last_workbook_action_text = "No workbook write yet"
        self._workbook_output_text = WORKBOOK_OUTPUT_PENDING
        self._workbook_full_path = ""
        self._expected_serial_value = "-"
        self._expected_pwm_value = "-"
        self._expected_other_value = "-"
        self._actual_serial_value = "-"
        self._actual_pwm_value = PWM_COMMAND_SUPPORT_PENDING
        self._check_result_value = "-"

        self._combo = QComboBox()
        self._combo.setObjectName("AxisSelectorCombo")
        for node_id, node_name in get_ml20_testable_nodes():
            self._combo.addItem(f"Node {node_id} - {node_name}", (node_id, node_name))

        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(8)
        top_grid.setVerticalSpacing(6)
        top_grid.addWidget(LabeledControl("COM Port", self._port_combo), 0, 0)
        top_grid.addWidget(LabeledControl("Baud Rate", self._baud_combo), 0, 1)
        top_grid.addWidget(LabeledControl("Selected Node", self._combo), 1, 0, 1, 2)
        self.body_layout.addLayout(top_grid)

        self._connect_button.clicked.connect(self._handle_toggle)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addWidget(self._connect_button)
        button_row.addWidget(self._status_label, 1)
        self.body_layout.addLayout(button_row)

        self._firmware_label = QLabel("MCU Firmware Version: -")
        self._firmware_label.setObjectName("DetailValue")
        self.body_layout.addWidget(self._firmware_label)

        self._connected_label = QLabel("No. of Connection / Connected Nodes: 0")
        self._connected_label.setObjectName("DetailValue")
        self.body_layout.addWidget(self._connected_label)

        self._workbook_label = QLabel("Configuration File / IPQC Workbook: None")
        self._workbook_label.setObjectName("DetailValue")
        self._workbook_label.setWordWrap(True)
        self.body_layout.addWidget(self._workbook_label)

        self._sheet_group_combo = QComboBox()
        self._sheet_group_combo.setEnabled(False)
        self._sheet_group_combo.currentTextChanged.connect(self.sheet_group_changed.emit)
        self.body_layout.addWidget(LabeledControl("Selected sheet group", self._sheet_group_combo))

        workbook_button_grid = QGridLayout()
        workbook_button_grid.setContentsMargins(0, 0, 0, 0)
        workbook_button_grid.setHorizontalSpacing(8)
        workbook_button_grid.setVerticalSpacing(6)

        self.load_workbook_button = QPushButton("Load IPQC Workbook")
        self.load_workbook_button.setProperty("tone", "primary")
        self.load_workbook_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.load_workbook_button.clicked.connect(self.load_workbook_requested.emit)
        workbook_button_grid.addWidget(self.load_workbook_button, 0, 0)

        self.write_button = QPushButton("Write Parameters to MCU")
        self.write_button.setProperty("tone", "secondary")
        self.write_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.write_button.clicked.connect(self.write_requested.emit)
        workbook_button_grid.addWidget(self.write_button, 0, 1)

        self.verify_button = QPushButton("Read Back / Verify")
        self.verify_button.setProperty("tone", "primary")
        self.verify_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.verify_button.clicked.connect(self.verify_requested.emit)
        workbook_button_grid.addWidget(self.verify_button, 1, 0)

        self.save_button = QPushButton("Save / Download Completed Workbook")
        self.save_button.setProperty("tone", "secondary")
        self.save_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.save_button.clicked.connect(self.save_requested.emit)
        workbook_button_grid.addWidget(self.save_button, 1, 1)

        self.body_layout.addLayout(workbook_button_grid)

        self._headers = ["Node", "Firmware", "Serial(UUID)", "Node Type", "Status"]
        self._table = SimpleTableWidget(self._headers, [])
        self._table.setMinimumHeight(96)
        self._table.setMaximumHeight(144)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._row_node_ids: list[int] = []
        self._table.cellClicked.connect(self._handle_cell_clicked)
        self.body_layout.addWidget(self._table)

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

    def set_nodes(self, nodes_model: dict) -> None:
        connected_nodes = [int(node_id) for node_id in nodes_model.get("connected_nodes", [])]
        rows = list(nodes_model.get("rows", []))
        self._connected_nodes_value = str(len(connected_nodes))
        self._connected_label.setText(
            f"No. of Connection / Connected Nodes: {self._connected_nodes_value}"
            + (f" ({', '.join(str(node) for node in connected_nodes)})" if connected_nodes else "")
        )
        firmware_values = [str(row.get("firmware", "")).strip() for row in rows if str(row.get("firmware", "")).strip()]
        self._firmware_value = firmware_values[0] if firmware_values else "-"
        self._firmware_label.setText(f"MCU Firmware Version: {self._firmware_value}")

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

    def set_workbook_path(self, path: str) -> None:
        self._workbook_full_path = path
        display_name = Path(path).name if path else "None"
        self._workbook_label.setText(f"Configuration File / IPQC Workbook: {display_name}")
        self._workbook_label.setToolTip(path)

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
        self._expected_serial_value = serial_number or "-"
        self._expected_pwm_value = pwm or "-"
        self._expected_other_value = other_parameters or "-"

    def set_programmed_values(self, serial_number: str, pwm: str, check_result: str) -> None:
        self._actual_serial_value = serial_number or "-"
        self._actual_pwm_value = pwm or "-"
        self._check_result_value = check_result or "-"

    def set_workbook_validation(self, passed: bool, message: str) -> None:
        if passed:
            self._workbook_validation_text = "Workbook validation: PASSED"
            return
        reason = message or "FAILED"
        self._workbook_validation_text = f"Workbook validation: FAILED ({reason})"

    def set_workbook_output_path(self, path_or_status: str) -> None:
        self._workbook_output_text = path_or_status

    def set_last_workbook_action(self, status: str) -> None:
        self._last_workbook_action_text = status

    @property
    def workbook_validation_text(self) -> str:
        return self._workbook_validation_text

    @property
    def last_workbook_action_text(self) -> str:
        return self._last_workbook_action_text

    @property
    def workbook_output_text(self) -> str:
        return self._workbook_output_text

    def selected_node(self) -> tuple[int, str]:
        selected = self._combo.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            fallback_nodes = get_ml20_testable_nodes()
            if fallback_nodes:
                return fallback_nodes[0]
            raise RuntimeError("No ML 2.0 testable nodes configured for Production.")
        node_id, node_name = selected
        return int(node_id), str(node_name)

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


class _TestStagesSection(PanelFrame):
    configuration_requested = pyqtSignal()
    single_axis_requested = pyqtSignal()
    performance_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Test Stages", "")
        self._rows: dict[str, tuple[QLabel, QPushButton]] = {}
        self._add_stage_row("configuration", "Configuration", self.configuration_requested.emit)
        self._add_stage_row("single_axis", "Single Axis Functional Test", self.single_axis_requested.emit)
        self._add_stage_row("performance", "Performance Test", self.performance_requested.emit)
        self.reset_stage_states()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def _add_stage_row(self, key: str, label_text: str, handler) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        indicator = QLabel()
        indicator.setFixedSize(14, 14)
        indicator.setFrameShape(QFrame.Shape.NoFrame)
        indicator.setStyleSheet("border-radius: 7px; background: #B0B7C3;")
        row_layout.addWidget(indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(label_text)
        label.setObjectName("DetailValue")
        row_layout.addWidget(label, 1)

        button = QPushButton("Start Test")
        button.setProperty("tone", "secondary")
        button.clicked.connect(handler)
        row_layout.addWidget(button)

        self._rows[key] = (indicator, button)
        self.body_layout.addWidget(row)

    def reset_stage_states(self) -> None:
        for key in self._rows:
            self.set_stage_status(key, "neutral")

    def set_stage_status(self, key: str, status: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        indicator, button = row
        normalized = status.strip().lower()
        color = "#B0B7C3"
        if normalized in {"testing", "pending"}:
            color = "#D98732"
        elif normalized in {"pass", "success"}:
            color = "#2E7D32"
        elif normalized in {"fail", "failure", "timeout"}:
            color = "#C62828"
        indicator.setStyleSheet(f"border-radius: 7px; background: {color};")
        if key != "configuration":
            button.setEnabled(True)


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
        self._workbook_validation_text = "Workbook validation: Not loaded"
        self._last_workbook_action_text = "No workbook write yet"
        self._workbook_output_text = WORKBOOK_OUTPUT_PENDING
        self._expected_serial_value = "-"
        self._expected_pwm_value = "-"
        self._expected_other_value = "-"
        self._actual_serial_value = "-"
        self._actual_pwm_value = PWM_COMMAND_SUPPORT_PENDING
        self._check_result_value = "-"

        button_grid = QGridLayout()
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(8)
        button_grid.setVerticalSpacing(6)

        load_workbook_button = QPushButton("Load IPQC Workbook")
        load_workbook_button.setProperty("tone", "primary")
        load_workbook_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        load_workbook_button.clicked.connect(self.load_workbook_requested.emit)
        button_grid.addWidget(load_workbook_button, 0, 0)

        write_button = QPushButton("Write Parameters to MCU")
        write_button.setProperty("tone", "secondary")
        write_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        write_button.clicked.connect(self.write_requested.emit)
        button_grid.addWidget(write_button, 0, 1)

        verify_button = QPushButton("Read Back / Verify")
        verify_button.setProperty("tone", "primary")
        verify_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        verify_button.clicked.connect(self.verify_requested.emit)
        button_grid.addWidget(verify_button, 1, 0)

        save_button = QPushButton("Save / Download Completed Workbook")
        save_button.setProperty("tone", "secondary")
        save_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        save_button.clicked.connect(self.save_requested.emit)
        button_grid.addWidget(save_button, 1, 1)

        self.load_workbook_button = load_workbook_button
        self.verify_button = verify_button
        self.write_button = write_button
        self.save_button = save_button

        self.body_layout.addLayout(button_grid)

        self._workbook_label = QLabel("Configuration File / IPQC Workbook: None")
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
        display_name = Path(path).name if path else "None"
        self._workbook_label.setText(f"Configuration File / IPQC Workbook: {display_name}")
        self._workbook_label.setToolTip(path)

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
        self._expected_serial_value = serial_number or "-"
        self._expected_pwm_value = pwm or "-"
        self._expected_other_value = other_parameters or "-"
        self._expected_serial_label.setText(f"Expected S/N / UUID: {self._expected_serial_value}")
        self._expected_pwm_label.setText(f"Expected PWM: {self._expected_pwm_value}")
        self._expected_other_label.setText(f"Expected other parameters: {self._expected_other_value}")

    def set_programmed_values(self, serial_number: str, pwm: str, check_result: str) -> None:
        self._actual_serial_value = serial_number or "-"
        self._actual_pwm_value = pwm or "-"
        self._check_result_value = check_result or "-"
        self._actual_serial_label.setText(f"Programmed/read-back S/N: {self._actual_serial_value}")
        self._actual_pwm_label.setText(f"Programmed/read-back PWM: {self._actual_pwm_value}")
        self._check_result_label.setText(f"Check result: {self._check_result_value}")

    def set_workbook_validation(self, passed: bool, message: str) -> None:
        if passed:
            self._workbook_validation_text = "Workbook validation: PASSED"
            self._workbook_validation_label.setText("Workbook validation: PASSED")
            return
        reason = message or "FAILED"
        self._workbook_validation_text = f"Workbook validation: FAILED ({reason})"
        self._workbook_validation_label.setText(self._workbook_validation_text)

    def set_workbook_output_path(self, path_or_status: str) -> None:
        self._workbook_output_text = path_or_status
        self._workbook_output_label.setText(f"Completed workbook: {path_or_status}")
        self._workbook_output_label.setToolTip(path_or_status)

    def set_last_workbook_action(self, status: str) -> None:
        self._last_workbook_action_text = status
        self._last_workbook_action_label.setText(f"Last workbook action: {status}")

    @property
    def workbook_validation_text(self) -> str:
        return self._workbook_validation_text

    @property
    def last_workbook_action_text(self) -> str:
        return self._last_workbook_action_text

    @property
    def workbook_output_text(self) -> str:
        return self._workbook_output_text


class _TestProgressSection(PanelFrame):
    refresh_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Status / Test Progress", "")
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        refresh_button = QPushButton("Refresh")
        refresh_button.setProperty("tone", "secondary")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        button_row.addWidget(refresh_button)

        clear_button = QPushButton("Clear")
        clear_button.setProperty("tone", "secondary")
        clear_button.clicked.connect(self.clear_requested.emit)
        button_row.addWidget(clear_button)
        button_row.addStretch(1)
        self.body_layout.addLayout(button_row)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setObjectName("StatusProgressLog")
        self._log_output.setMinimumHeight(220)
        self._log_output.setMaximumHeight(320)
        self._log_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._log_output.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._log_output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body_layout.addWidget(self._log_output)

    def reset_steps(self, steps: list[str]) -> None:
        self._log_output.clear()
        for step in steps:
            self.append_step(step)

    def set_profile_steps(self, step_names: list[str]) -> None:
        self._log_output.clear()
        for index, step_name in enumerate(step_names, start=1):
            self.append_step(f"{index}. {step_name} - PENDING")

    def mark_profile_step(self, step_name: str, status: str) -> None:
        self.append_step(f"{step_name} - {status}")

    def append_step(self, step: str, *, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = None
        normalized = level.strip().lower()
        if normalized == "success":
            color = "#2E7D32"
        elif normalized == "error":
            color = "#C62828"
        escaped = html.escape(f"[{timestamp}] {step}")
        if color:
            self._log_output.append(f"<span style='color:{color};'>{escaped}</span>")
        else:
            self._log_output.append(escaped)
        self._scroll_to_bottom()

    def clear_log(self) -> None:
        self._log_output.clear()

    def to_plain_text(self) -> str:
        return self._log_output.toPlainText()

    def to_html(self) -> str:
        return self._log_output.toHtml()

    def _scroll_to_bottom(self) -> None:
        scrollbar = self._log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
