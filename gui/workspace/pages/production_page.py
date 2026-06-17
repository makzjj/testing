"""Production page implementation with runtime-backed ML 2.0 node testing."""

from __future__ import annotations

import html
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..bridges import WorkspaceRuntimeBridge
from ..dialogs.sampling_test_popup import SamplingTestPopup
from ..widgets import DetailListWidget, LabeledControl, PanelFrame, SimpleTableWidget
from ..controllers.sampling_test_controller import SamplingTestConfig, SamplingTestController
from .single_axis_functional_popup import SingleAxisFunctionalPopup
from services.ipqc_excel_adapter import IpqcExcelAdapter
from .base_page import BaseWorkspacePage
from .production_parameter_controller import (
    ParameterDefinition,
    ParameterRequest,
    ParameterVerificationResult,
    ProductionParameterController,
    default_workbook_parameter_definitions,
    parse_pwm_value,
    parse_uuid_value,
)
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
EEPROM_SAVE_SETTLE_MS = 2000
WORKBOOK_OUTPUT_PENDING = "Pending"


WORKBOOK_PARAMETER_DEFINITIONS: dict[str, ParameterDefinition] = {
    definition.name: definition for definition in default_workbook_parameter_definitions()
}


@dataclass
class _SamplingSession:
    node_id: int
    node_name: str
    runtime_window: object


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
        self.robot_nodes_section = _NodeStatusSection()
        self.test_control_section = self.communication_section
        self.uuid_section = _UuidCsvSection()
        self.stage_section = _TestStagesSection()
        self.node_status_section = self.robot_nodes_section
        self.result_summary_section = _ResultSummarySection()
        self.progress_section = _TestProgressSection()
        self._test_controller = ProductionTestController(bridge)
        self._parameter_controller = ProductionParameterController(bridge, node_map=ML20_NODE_MAP)
        self._ipqc_excel_adapter = IpqcExcelAdapter()
        self._last_status_entry = ""
        self._single_axis_popup: SingleAxisFunctionalPopup | None = None
        self._sampling_popup: SamplingTestPopup | None = None
        self._single_axis_passed = False
        self._sampling_controller = SamplingTestController(self._ipqc_excel_adapter, SamplingTestConfig())
        self._sampling_session: _SamplingSession | None = None

        self.stage_section.configuration_requested.connect(self._handle_run_test)
        self.stage_section.single_axis_requested.connect(self._handle_single_axis_test_requested)
        self.stage_section.sampling_requested.connect(self._handle_start_sampling_requested)
        self.stage_section.performance_requested.connect(self._handle_performance_test_requested)
        self.uuid_section.load_workbook_requested.connect(self._handle_load_ipqc_workbook)
        self.uuid_section.write_requested.connect(self._handle_write_uuid)
        self.uuid_section.verify_requested.connect(self._handle_verify_uuid)
        self.uuid_section.save_requested.connect(self._handle_save_completed_workbook)
        self.communication_section.connect_requested.connect(self._handle_connect_requested)
        self.communication_section.disconnect_requested.connect(self._handle_disconnect_requested)
        self.node_status_section.update_nodes_requested.connect(self._handle_update_nodes_requested)
        self.node_status_section.robot_power_requested.connect(self._handle_robot_power_requested)
        self.node_status_section.clear_nodes_requested.connect(self._handle_clear_nodes_requested)
        self._test_controller.log_message.connect(self.console_message.emit)
        self._test_controller.test_started.connect(self._handle_test_started)
        self._test_controller.test_passed.connect(self._handle_test_passed)
        self._test_controller.test_failed.connect(self._handle_test_failed)
        self._test_controller.test_unsupported.connect(self._handle_test_unsupported)
        self._test_controller.test_aborted.connect(self._handle_test_aborted)
        self._test_controller.profile_started.connect(self._handle_profile_started)
        self._test_controller.step_finished.connect(self._handle_step_finished)
        self._test_controller.profile_finished.connect(self._handle_profile_finished)
        self._sampling_controller.command_requested = self._send_sampling_command
        self._sampling_controller.log_message = self._handle_sampling_log
        self._sampling_controller.packet_message = self._handle_sampling_packet_message
        self._sampling_controller.state_changed = self._handle_sampling_state_changed
        self._sampling_controller.status_changed = self._handle_sampling_status_changed
        self._sampling_controller.current_pwm_changed = self._handle_sampling_current_pwm_changed
        self._sampling_controller.current_direction_changed = self._handle_sampling_current_direction_changed
        self._sampling_controller.current_sample_changed = self._handle_sampling_current_sample_changed
        self._sampling_controller.samples_completed_changed = self._handle_sampling_completed_count_changed
        self._sampling_controller.latest_measurement_changed = self._handle_sampling_latest_measurement_changed
        self._sampling_controller.latest_workbook_cell_written = self._handle_sampling_latest_cell_written
        self._sampling_controller.measurement_completed = self._handle_sampling_measurement_completed
        self._sampling_controller.sampling_completed = self._handle_sampling_completed
        self._sampling_controller.sampling_failed = self._handle_sampling_failed
        self._sampling_controller.sampling_aborted = self._handle_sampling_aborted
        self._parameter_controller.log_message.connect(self.console_message.emit)
        self._parameter_controller.parameter_write_finished.connect(self._handle_parameter_write_finished)
        self._parameter_controller.parameter_verification_finished.connect(self._handle_parameter_verification_finished)
        self._parameter_controller.eeprom_save_finished.connect(self._handle_eeprom_save_finished)
        self.progress_section.refresh_requested.connect(self.refresh)
        self.progress_section.clear_requested.connect(self._handle_clear_progress_log)
        self.test_control_section.node_selected.connect(self._handle_test_control_node_selected)
        self._current_programmed_pwm_value = "-"
        self._parameter_definitions = list(WORKBOOK_PARAMETER_DEFINITIONS.values())
        self._pending_parameter_requests: list[ParameterRequest] = []
        self._pending_persistent_parameter_requests: list[ParameterRequest] = []
        self._pending_runtime_parameter_requests: list[ParameterRequest] = []
        self._last_parameter_verification_results_by_name: dict[str, ParameterVerificationResult] = {}
        self._workbook_loaded = False
        self._workbook_write_completed = False
        self._workbook_verification_passed = False
        self._workbook_parameter_write_pending = False
        self._workbook_runtime_write_pending = False
        self._workbook_eeprom_save_pending = False
        self._workbook_eeprom_save_failed = False
        self._workbook_eeprom_settle_active = False

        self.add_weighted_row((self.communication_section, 1), (self.stage_section, 1))
        self.add_full_width(self.node_status_section)
        self.add_full_width(self.uuid_section)
        self.add_full_width(self.progress_section)

        self._runtime_poll_timer = QTimer(self)
        self._runtime_poll_timer.setInterval(RUNTIME_POLL_INTERVAL_MS)
        self._runtime_poll_timer.timeout.connect(self._refresh_runtime_panels)
        self._runtime_poll_timer.start()

        self._eeprom_save_settle_timer = QTimer(self)
        self._eeprom_save_settle_timer.setSingleShot(True)
        self._eeprom_save_settle_timer.timeout.connect(self._handle_eeprom_save_settle_finished)

        self.uuid_section.set_workbook_output_path(WORKBOOK_OUTPUT_PENDING)
        self.uuid_section.set_workbook_path("")
        self.uuid_section.set_last_workbook_action("-")
        self.uuid_section.set_workbook_validation_idle()
        self.uuid_section.set_programmed_values("-", self._current_programmed_pwm_value, "-")
        self._reset_result_only()
        self._refresh_runtime_panels()
        self._refresh_workbook_action_states()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._refresh_runtime_panels()

    def refresh(self) -> None:
        """Refresh lightweight status without resetting operator state."""
        self._refresh_runtime_panels()
        self.progress_section.append_step("Refreshed Production status view")

    def _refresh_runtime_panels(self) -> None:
        self._refresh_connection_status()
        self._refresh_robot_nodes()
        self._refresh_robot_power_controls()
        self._refresh_workbook_action_states()
        self._refresh_sampling_action_states()

    def _refresh_connection_status(self) -> None:
        communication_model = self._bridge.get_runtime_communication_model(create_if_missing=False)
        serial_connected = bool(communication_model.get("connected", False))
        self.communication_section.set_model(communication_model)
        self.node_status_section.set_connected(serial_connected)
        if serial_connected:
            selected_port = communication_model.get("selected_port") or "Unknown"
            self.communication_section.set_status_text(f"● Connected ({selected_port})")
        else:
            self.communication_section.set_status_text("○ Disconnected")
        self._refresh_sampling_action_states()

    def _refresh_robot_nodes(self) -> None:
        nodes_model = self._bridge.get_runtime_robot_nodes(create_if_missing=False)
        self.communication_section.set_nodes(nodes_model)
        self.node_status_section.set_nodes(nodes_model)

    def _refresh_robot_power_controls(self) -> None:
        return

    def _handle_update_nodes_requested(self) -> None:
        requested = False
        request_scan = getattr(self._bridge, "request_runtime_node_scan", None)
        if callable(request_scan):
            requested = bool(request_scan())
        if requested:
            self.console_message.emit("[Production] Requested runtime node scan update.")
            self.progress_section.append_step("Requested runtime node scan update")
        else:
            self.console_message.emit(
                "[Production] Update Nodes requested, but no runtime scan hook is available yet (TODO backend hook)."
            )
            self.progress_section.append_step("Update Nodes requested (TODO backend hook)")
        self._refresh_robot_nodes()

    def _handle_clear_nodes_requested(self) -> None:
        self.node_status_section.clear_node_states()
        self.progress_section.append_step("Cleared displayed node states to unknown")

    def _handle_robot_power_requested(self) -> None:
        self.progress_section.append_step("Robot power command requested.")
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Question)
        message_box.setWindowTitle("Robot Power")
        message_box.setText("Choose robot power command to send.")
        power_on_button = message_box.addButton("Power ON", QMessageBox.ButtonRole.AcceptRole)
        power_off_button = message_box.addButton("Power OFF", QMessageBox.ButtonRole.DestructiveRole)
        cancel_button = message_box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        message_box.exec()
        clicked_button = message_box.clickedButton()
        if clicked_button is cancel_button:
            self.progress_section.append_step("Robot power command cancelled.")
            return

        if clicked_button is power_on_button:
            target_power_on = True
            action_label = "ON"
        elif clicked_button is power_off_button:
            target_power_on = False
            action_label = "OFF"
        else:
            self.progress_section.append_step("Robot power command cancelled.")
            return

        try:
            self._bridge.send_runtime_robot_power(target_power_on)
        except Exception as exc:
            self.progress_section.append_step(f"Robot power command failed: {exc}", level="error")
            return

        self.progress_section.append_step(f"Robot power {action_label} command sent.")

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
        if self._sampling_controller.is_active():
            self._sampling_controller.abort_by_user()
            self._refresh_sampling_action_states()
            return
        self._test_controller.abort_test()
        self._refresh_connection_status()

    def _handle_single_axis_test_requested(self) -> None:
        if self._single_axis_popup is None:
            # Pass the workspace bridge so the popup can discover the already-connected backend
            self._single_axis_popup = SingleAxisFunctionalPopup(
                self,
                node_options=get_ml20_testable_nodes(),
                bridge=self._bridge,
            )
            self._single_axis_popup.functional_passed.connect(self._handle_single_axis_passed)
            self._single_axis_popup.functional_failed.connect(self._handle_single_axis_failed)
            self._single_axis_popup.functional_aborted.connect(self._handle_single_axis_aborted)
            self._single_axis_popup.sampling_start_requested.connect(self._handle_start_sampling_requested)
        self._single_axis_popup.show()
        self._single_axis_popup.raise_()
        self._single_axis_popup.activateWindow()

    def _handle_single_axis_passed(self, node_id: int, node_name: str) -> None:
        self._single_axis_passed = True
        self.console_message.emit(f"[Production] Single Axis Functional Test PASSED for Node {node_id} {node_name}")
        self.progress_section.append_step(f"Single Axis PASSED for Node {node_id} {node_name}", level="success")
        self.stage_section.set_stage_status("single_axis", "pass")
        self._refresh_sampling_action_states()

    def _handle_single_axis_failed(self, node_id: int, node_name: str, reason: str) -> None:
        self._single_axis_passed = False
        self.console_message.emit(f"[Production] Single Axis Functional Test FAILED for Node {node_id} {node_name}: {reason}")
        self.progress_section.append_step(f"Single Axis FAILED for Node {node_id} {node_name}: {reason}", level="error")
        self.stage_section.set_stage_status("single_axis", "fail")
        self._refresh_sampling_action_states()

    def _handle_single_axis_aborted(self, node_id: int, node_name: str, reason: str) -> None:
        self._single_axis_passed = False
        self.console_message.emit(f"[Production] Single Axis Functional Test ABORTED for Node {node_id} {node_name}: {reason}")
        self.progress_section.append_step(f"Single Axis ABORTED for Node {node_id} {node_name}", level="warning")
        self.stage_section.set_stage_status("single_axis", "fail")
        self._refresh_sampling_action_states()

    # Minimal passthrough to allow popups to query the runtime window via parent
    def get_runtime_window(self, *, create_if_missing: bool = False):  # pragma: no cover - thin delegate
        try:
            return self._bridge.get_runtime_window(create_if_missing=create_if_missing)
        except Exception:
            return None

    def _handle_performance_test_requested(self) -> None:
        self.progress_section.append_step("Performance Test UI is present but command flow is not enabled yet")

    def _handle_start_sampling_requested(self) -> None:
        popup = self._ensure_sampling_popup()
        self._refresh_sampling_popup_state()
        popup.show()
        popup.raise_()
        popup.activateWindow()
        if self._sampling_controller.is_active():
            self._refresh_sampling_action_states()
            return
        self._refresh_sampling_action_states()
        if popup.start_button.isEnabled():
            try:
                node_id, node_name = self.test_control_section.selected_node()
            except RuntimeError:
                node_id = self._sampling_session.node_id if self._sampling_session is not None else None
                node_name = self._sampling_session.node_name if self._sampling_session is not None else None
            active_group = self._ipqc_excel_adapter.active_sheet_group or "-"
            if node_id is not None and node_name and active_group != "-":
                try:
                    sheet_name = self._ipqc_excel_adapter.resolve_sampling_sheet_name(active_group)
                except Exception:
                    sheet_name = "-"
                if sheet_name != "-":
                    popup.append_operator_log(
                        f"Sampling ready for Node {int(node_id)} {node_name} using {sheet_name}"
                    )
        else:
            reason = popup.start_button.toolTip().strip()
            if reason:
                self.console_message.emit(f"[Production] {reason}")
                self.progress_section.append_step(reason, level="warning")

    def _handle_sampling_popup_resume_requested(self) -> None:
        popup = self._ensure_sampling_popup()
        popup.show()
        popup.raise_()
        popup.activateWindow()
        if self._sampling_controller.is_active():
            self._refresh_sampling_action_states()
            return
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError:
            node_id = self._sampling_session.node_id if self._sampling_session is not None else None
            node_name = self._sampling_session.node_name if self._sampling_session is not None else None
        active_group = self._ipqc_excel_adapter.active_sheet_group
        resume_enabled, resume_reason = self._sampling_controller.resume_availability(
            node_id=node_id,
            node_name=node_name,
            base_group=active_group,
        )
        if not resume_enabled:
            if resume_reason:
                self.console_message.emit(f"[Production] {resume_reason}")
                self.progress_section.append_step(resume_reason, level="warning")
            self._refresh_sampling_action_states()
            return
        if self._sampling_session is not None:
            self._attach_sampling_runtime_window(self._sampling_session.runtime_window)
        resumed = self._sampling_controller.resume(node_id=node_id, node_name=node_name, base_group=active_group)
        if not resumed:
            self._refresh_sampling_action_states()
            return
        context = self._sampling_controller.resume_context
        if context is not None:
            message = (
                f"Sampling resumed for Node {context.node_id} {context.node_name} "
                f"from PWM {context.current_pwm}, sample {context.current_sample_index}"
            )
            self.console_message.emit(f"[Production] {message}")
            self.progress_section.append_step(message)
        self._refresh_sampling_action_states()

    def _handle_sampling_popup_start_requested(self) -> None:
        if self._sampling_controller.is_active():
            popup = self._ensure_sampling_popup()
            popup.show()
            popup.raise_()
            popup.activateWindow()
            self._refresh_sampling_action_states()
            return

        popup = self._ensure_sampling_popup()
        if not popup.start_button.isEnabled():
            self._refresh_sampling_action_states()
            return

        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            reason = str(exc)
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="warning")
            self._set_status_result("READY", reason)
            self._refresh_sampling_action_states()
            return

        if not self._single_axis_passed:
            reason = "Sampling is disabled until the Single Axis Functional Test passes."
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="warning")
            self._set_status_result("READY", reason)
            self._refresh_sampling_action_states()
            return

        if not self._ipqc_excel_adapter.has_loaded_workbook():
            reason = "Load an IPQC workbook before starting Sampling."
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="warning")
            self._set_status_result("READY", reason)
            self._refresh_sampling_action_states()
            return

        active_group = self._ipqc_excel_adapter.active_sheet_group
        if not active_group:
            reason = "Select an active workbook sheet group before starting Sampling."
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="warning")
            self._set_status_result("READY", reason)
            self._refresh_sampling_action_states()
            return

        try:
            layout = self._ipqc_excel_adapter.discover_sampling_layout(active_group)
        except Exception as exc:
            reason = f"Sampling workbook layout is invalid: {exc}"
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="error")
            self._set_status_result("FAIL", reason)
            self._refresh_sampling_action_states()
            return

        runtime_window = self.get_runtime_window(create_if_missing=True)
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if runtime_window is None or backend_client is None or not backend_client.is_connected():
            reason = "Serial port not connected. Sampling cannot start."
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="warning")
            self._set_status_result("READY", reason)
            self._refresh_sampling_action_states()
            return

        popup = self._ensure_sampling_popup()
        self._sampling_session = _SamplingSession(node_id=node_id, node_name=node_name, runtime_window=runtime_window)
        popup.set_context(node_id, node_name, layout.sheet_name)
        selected_pwm_values = popup.selected_pwm_values()
        selected_samples_per_pwm = popup.selected_samples_per_pwm()
        popup.prepare_for_run(
            total_samples=selected_samples_per_pwm,
            total_measurements=len(selected_pwm_values) * selected_samples_per_pwm * 2,
        )
        popup.show()
        popup.raise_()
        popup.activateWindow()
        self._attach_sampling_runtime_window(runtime_window)
        try:
            started = self._sampling_controller.start(
                node_id,
                node_name,
                single_axis_passed=self._single_axis_passed,
                base_group=active_group,
                pwm_values=selected_pwm_values,
                samples_per_pwm=selected_samples_per_pwm,
            )
        except Exception as exc:
            reason = f"Sampling failed to start: {exc}"
            self._sampling_session = None
            self._detach_sampling_runtime_window()
            self.console_message.emit(f"[Production] {reason}")
            self.progress_section.append_step(reason, level="error")
            self._set_status_result("FAIL", reason)
            if self._sampling_popup is not None:
                self._sampling_popup.set_status_text(reason)
                self._sampling_popup.set_state_text("IDLE")
                self._sampling_popup.set_final_status("IDLE")
                self._sampling_popup.set_stop_available(False)
                self._sampling_popup.set_sampling_configuration_enabled(True)
            self._refresh_sampling_action_states()
            return
        if not started:
            self._sampling_session = None
            self._detach_sampling_runtime_window()
            if self._sampling_popup is not None:
                self._sampling_popup.set_status_text("Sampling did not start.")
                self._sampling_popup.set_state_text("IDLE")
                self._sampling_popup.set_final_status("IDLE")
                self._sampling_popup.set_stop_available(False)
                self._sampling_popup.set_sampling_configuration_enabled(True)
            self._refresh_sampling_action_states()
            if self._sampling_controller.last_result is None:
                self._set_status_result("READY", "Sampling did not start.")
            return

        self._set_status_result("TESTING", f"Sampling started for Node {node_id} {node_name}")
        self.stage_section.set_stage_status("sampling", "testing")
        if self._sampling_popup is not None:
            self._sampling_popup.set_final_status("RUNNING")
            self._sampling_popup.set_stop_available(True)
        self._refresh_sampling_action_states()

    def _handle_sampling_stop_requested(self) -> None:
        if self._sampling_controller.is_active():
            self._sampling_controller.abort_by_user()

    def _ensure_sampling_popup(self) -> SamplingTestPopup:
        if self._sampling_popup is None:
            self._sampling_popup = SamplingTestPopup(self)
            self._sampling_popup.start_requested.connect(self._handle_sampling_popup_start_requested)
            self._sampling_popup.resume_requested.connect(self._handle_sampling_popup_resume_requested)
            self._sampling_popup.stop_requested.connect(self._handle_sampling_stop_requested)
        self._refresh_sampling_popup_state()
        return self._sampling_popup

    def _refresh_sampling_popup_state(self) -> None:
        if self._sampling_popup is None:
            return
        popup = self._sampling_popup
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError:
            node_id = self._sampling_session.node_id if self._sampling_session is not None else None
            node_name = self._sampling_session.node_name if self._sampling_session is not None else None
        sheet_name = "-"
        if self._ipqc_excel_adapter.has_loaded_workbook():
            try:
                active_group = self._ipqc_excel_adapter.active_sheet_group
                if active_group:
                    sheet_name = self._ipqc_excel_adapter.resolve_sampling_sheet_name(active_group)
            except Exception:
                sheet_name = "-"
        popup.set_context(node_id, node_name, sheet_name)
        popup.set_start_available(
            self.stage_section.stage_enabled("sampling"),
            self.stage_section.stage_tooltip("sampling"),
        )
        if self._sampling_controller.is_active():
            popup.set_resume_available(False, "Resume unavailable: Sampling is already running.")
            popup.set_resume_hint("Resume unavailable: Sampling is already running.")
            popup.set_stop_available(True)
        else:
            try:
                node_id, node_name = self.test_control_section.selected_node()
            except RuntimeError:
                node_id = self._sampling_session.node_id if self._sampling_session is not None else None
                node_name = self._sampling_session.node_name if self._sampling_session is not None else None
            active_group = self._ipqc_excel_adapter.active_sheet_group
            resume_enabled, resume_reason = self._sampling_controller.resume_availability(
                node_id=node_id,
                node_name=node_name,
                base_group=active_group,
            )
            popup.set_resume_available(resume_enabled, resume_reason)
            popup.set_resume_hint(resume_reason)
            popup.set_stop_available(False)

    def _attach_sampling_runtime_window(self, runtime_window) -> None:
        if runtime_window is None or not hasattr(runtime_window, "packet_received"):
            return
        try:
            runtime_window.packet_received.connect(self._sampling_controller.handle_runtime_packet)
        except (TypeError, RuntimeError):
            pass

    def _detach_sampling_runtime_window(self, *, preserve_session: bool = False) -> None:
        runtime_window = self._sampling_session.runtime_window if self._sampling_session is not None else None
        if runtime_window is not None and hasattr(runtime_window, "packet_received"):
            try:
                runtime_window.packet_received.disconnect(self._sampling_controller.handle_runtime_packet)
            except (TypeError, RuntimeError):
                pass
        if not preserve_session:
            self._sampling_session = None

    def _send_sampling_command(self, payload: list[int]) -> None:
        runtime_window = self._sampling_session.runtime_window if self._sampling_session is not None else None
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if runtime_window is None or backend_client is None or not backend_client.is_connected():
            raise RuntimeError("Sampling runtime transport is not connected.")
        if self._sampling_session is None:
            raise RuntimeError("Sampling node is not selected.")
        backend_client.send_command_bytes(self._sampling_session.node_id, list(payload))
        hex_str = " ".join(f"{byte:02X}" for byte in payload)
        self._handle_sampling_packet_message(f"[TX] Node {self._sampling_session.node_id}: {hex_str}")

    def _handle_sampling_log(self, text: str) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.append_operator_log(text)

    def _handle_sampling_packet_message(self, text: str) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.append_packet_log(text)

    def _handle_sampling_state_changed(self, text: str) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_state_text(text)

    def _handle_sampling_status_changed(self, text: str) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_status_text(text)

    def _handle_sampling_current_pwm_changed(self, pwm: int) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_current_pwm(int(pwm))

    def _handle_sampling_current_direction_changed(self, direction: str) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_current_direction(direction)

    def _handle_sampling_current_sample_changed(self, sample_index: int) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_current_sample(sample_index, self._sampling_controller.samples_per_direction)

    def _handle_sampling_completed_count_changed(self, completed: int, total: int) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_completed_counts(completed, total)

    def _handle_sampling_latest_measurement_changed(self, range_value: int, elapsed_seconds: float, speed: float) -> None:
        if self._sampling_popup is not None:
            self._sampling_popup.set_latest_measurement_details(range_value, elapsed_seconds, speed)

    def _handle_sampling_latest_cell_written(self, cell_ref: str) -> None:
        if self._sampling_popup is not None:
            current_text = self._sampling_popup.latest_cell_value.text()
            if "Range=" not in current_text and "Speed=" not in current_text and "Time=" not in current_text:
                self._sampling_popup.set_latest_workbook_cell(cell_ref)

    def _handle_sampling_measurement_completed(self, result: object) -> None:
        if self._sampling_popup is None:
            return
        cells = getattr(result, "workbook_cells", None)
        cell_summary_text = "-"
        if isinstance(cells, dict) and cells:
            ordered_cells = [f"{name}={cells[name]}" for name in ("Range", "Speed", "Time") if name in cells]
            if ordered_cells:
                cell_summary_text = ", ".join(ordered_cells)
            else:
                cell_summary_text = ", ".join(str(value) for value in cells.values())
        self._sampling_popup.set_latest_workbook_cell(cell_summary_text)
        direction = str(getattr(result, "direction", "?")).strip()
        if direction == "+":
            direction_text = "+"
        elif direction == "-":
            direction_text = "-"
        else:
            direction_text = direction
        message = (
            f"Sample {getattr(result, 'sample_index', '?')}/{self._sampling_controller.samples_per_direction} "
            f"{direction_text} complete | range={getattr(result, 'range_value', '?')} | "
            f"time={float(getattr(result, 'elapsed_seconds', 0.0)):.3f}s | "
            f"speed={float(getattr(result, 'speed', 0.0)):.2f}"
        )
        self._sampling_popup.append_operator_log(message)

    def _handle_sampling_completed(self) -> None:
        self._detach_sampling_runtime_window()
        self._set_status_result("PASS", f"Sampling PASSED for {self._sampling_node_label()}")
        self.stage_section.set_stage_status("sampling", "pass")
        if self._sampling_popup is not None:
            self._sampling_popup.set_state_text("COMPLETED")
            self._sampling_popup.set_status_text("Sampling completed")
            self._sampling_popup.set_final_status("COMPLETED")
            self._sampling_popup.set_stop_available(False)
            self._sampling_popup.set_sampling_configuration_enabled(True)
        self._refresh_sampling_action_states()

    def _handle_sampling_failed(self, reason: str) -> None:
        self._detach_sampling_runtime_window(preserve_session=True)
        self._set_status_result("FAIL", f"Sampling FAILED for {self._sampling_node_label()}: {reason}")
        self.stage_section.set_stage_status("sampling", "fail")
        if self._sampling_popup is not None:
            self._sampling_popup.set_state_text("FAILED")
            self._sampling_popup.set_status_text(reason)
            self._sampling_popup.set_failure_details(
                pwm=self._sampling_controller.current_pwm,
                direction=self._sampling_controller.current_direction,
                sample_index=self._sampling_controller.current_sample_index,
                reason=reason,
                completed_count=self._sampling_controller.completed_measurements,
                total_count=self._sampling_controller.total_measurements,
            )
            self._sampling_popup.set_stop_available(False)
            self._sampling_popup.set_sampling_configuration_enabled(True)
        self._refresh_sampling_action_states()

    def _handle_sampling_aborted(self, reason: str) -> None:
        self._detach_sampling_runtime_window(preserve_session=True)
        self._set_status_result("FAIL", f"Sampling ABORTED for {self._sampling_node_label()}")
        self.stage_section.set_stage_status("sampling", "fail")
        if self._sampling_popup is not None:
            self._sampling_popup.set_state_text("ABORTED")
            self._sampling_popup.set_status_text(reason)
            self._sampling_popup.set_aborted_details(
                pwm=self._sampling_controller.current_pwm,
                direction=self._sampling_controller.current_direction,
                sample_index=self._sampling_controller.current_sample_index,
                reason=reason,
                completed_count=self._sampling_controller.completed_measurements,
                total_count=self._sampling_controller.total_measurements,
            )
            self._sampling_popup.set_stop_available(False)
            self._sampling_popup.set_sampling_configuration_enabled(True)
        self._refresh_sampling_action_states()

    def _handle_clear_result(self) -> None:
        if self._sampling_controller.is_active():
            self._sampling_controller.abort_by_user()
        elif self._test_controller.is_active():
            self._test_controller.abort_test()
        self._reset_result_only()
        self.console_message.emit("[Production] Cleared result summary and progress")

    def _handle_clear_progress_log(self) -> None:
        self.progress_section.clear_log()

    def _handle_test_control_node_selected(self) -> None:
        self._clear_parameter_verification_cache()
        self._refresh_workbook_action_states()

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
            self._reset_workbook_workflow_state()
            self._workbook_loaded = True
            self.uuid_section.set_workbook_path(path)
            self.uuid_section.set_sheet_groups(groups, active_group)
            self.uuid_section.set_workbook_output_path(WORKBOOK_OUTPUT_PENDING)
            self.uuid_section.set_last_workbook_action("Workbook loaded; no write performed yet")
            self._refresh_ipqc_expected_preview()
        except Exception as exc:
            self._workbook_loaded = False
            self._workbook_write_completed = False
            self._workbook_verification_passed = False
            self._workbook_parameter_write_pending = False
            self._workbook_runtime_write_pending = False
            self._workbook_eeprom_save_pending = False
            self._workbook_eeprom_save_failed = False
            self._workbook_eeprom_settle_active = False
            self._eeprom_save_settle_timer.stop()
            self.console_message.emit(f"[Production] Failed to load IPQC workbook: {exc}")
            self._set_status_result("FAIL", "IPQC workbook load failed.")
            self.progress_section.append_step("IPQC workbook load failed", level="error")
            self.uuid_section.set_workbook_validation_idle()
            self.uuid_section.set_last_workbook_action(f"Load failed: {exc}")
            self._refresh_workbook_action_states()
            return

        self.uuid_section.set_workbook_validation_ready()
        self.console_message.emit(f"[Production] Loaded IPQC workbook: {path}")
        self.progress_section.append_step(f"Loaded IPQC workbook with {len(groups)} sheet group(s)", level="success")
        self._set_status_result("READY", "Workbook loaded; no write performed yet")
        self._refresh_workbook_action_states()

    def _handle_ipqc_sheet_group_changed(self, base_group: str) -> None:
        if not base_group:
            return
        try:
            self._ipqc_excel_adapter.select_sheet_group(base_group)
            self._clear_parameter_verification_cache()
            self._refresh_ipqc_expected_preview()
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to select IPQC sheet group '{base_group}': {exc}")
            self.uuid_section.set_workbook_validation_ready()
            self._refresh_workbook_action_states()
            return
        self.uuid_section.set_workbook_validation_ready()
        self._refresh_workbook_action_states()

    def _refresh_ipqc_expected_preview(self) -> None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            self.uuid_section.set_expected_values(serial_number="", pwm="", other_parameters="")
            self._current_programmed_pwm_value = "-"
            self.uuid_section.set_programmed_values("-", self._current_programmed_pwm_value, "-")
            return
        try:
            expected_serial = self._ipqc_excel_adapter.read_expected_uuid_serial()
            expected_pwm = self._ipqc_excel_adapter.read_expected_pwm_value()
        except Exception as exc:
            self.uuid_section.set_workbook_validation_ready()
            self.uuid_section.set_expected_values(serial_number="", pwm="", other_parameters="")
            self._current_programmed_pwm_value = "-"
            self.uuid_section.set_programmed_values("-", self._current_programmed_pwm_value, "-")
            self._refresh_workbook_action_states()
            return
        self.uuid_section.set_expected_values(
            serial_number=expected_serial,
            pwm=expected_pwm,
            other_parameters="",
        )
        self._current_programmed_pwm_value = "-"
        self.uuid_section.set_programmed_values("-", self._current_programmed_pwm_value, "-")
        supported_count, raw_labels = self._count_supported_workbook_parameters()
        if supported_count == 0:
            labels_text = ", ".join(raw_labels) if raw_labels else "(none)"
            self.progress_section.append_step(f"No supported parameter rows found. Labels found: {labels_text}", level="error")
        self.progress_section.append_step(f"Loaded Programming table with {supported_count} supported parameter(s).")
        self._refresh_workbook_action_states()

    def _handle_write_uuid(self) -> None:
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self._set_status_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        requests = self._build_workbook_parameter_requests(node_id, node_name)
        if requests is None:
            return
        original_request_count = len(requests)
        requests, skipped_labels = self._filter_write_requests_by_previous_verification(requests)
        if requests:
            self._invalidate_parameter_verification_cache_for_requests(requests)
        persistent_requests = [request for request in requests if request.definition.persistent]
        runtime_requests = [request for request in requests if not request.definition.persistent]
        labels = ", ".join(self._parameter_write_log_name(request.definition) for request in requests if request.definition.build_write_command)
        if requests:
            self.progress_section.append_step(f"WRITE PLAN: {len(requests)} mismatched parameter(s): {labels}")
        else:
            if original_request_count > 0:
                self.progress_section.append_step("No parameter writes required; all workbook values already match MCU read-back.")
        if skipped_labels:
            self.progress_section.append_step(f"SKIPPED: {len(skipped_labels)} parameter(s) already matched read-back values.")
        self._pending_persistent_parameter_requests = persistent_requests
        self._pending_runtime_parameter_requests = runtime_requests
        self._workbook_write_completed = False
        self._workbook_verification_passed = False
        self._workbook_parameter_write_pending = False
        self._workbook_runtime_write_pending = False
        self._workbook_eeprom_save_pending = False
        self._workbook_eeprom_save_failed = False
        self._workbook_eeprom_settle_active = False
        self._eeprom_save_settle_timer.stop()

        if not persistent_requests and not runtime_requests:
            if original_request_count > 0:
                message = "No parameter writes required; all workbook values already match MCU read-back."
                self._set_status_result("READY", message)
                self.console_message.emit(f"[Production] {message}")
            else:
                self._set_status_result("FAIL", "No workbook parameters are available to write.")
                self.console_message.emit("[Production] No workbook parameters are available to write.")
            return

        if persistent_requests:
            self._workbook_parameter_write_pending = True
            self._set_status_result("WRITING PARAMETERS", f"Writing {labels} to Node {node_id} {node_name}.")
            success, message = self._parameter_controller.write_parameters(persistent_requests)
            if success:
                self._set_status_result("WRITE SENT", message)
                self.uuid_section.set_last_workbook_action(f"{labels} persistent write in progress")
            else:
                self._workbook_parameter_write_pending = False
                self._set_status_result("FAIL", message)
                self.console_message.emit(f"[Production] {message}")
                return
        elif runtime_requests:
            self._workbook_runtime_write_pending = True
            self._set_status_result("WRITING PARAMETERS", f"Writing {labels} to Node {node_id} {node_name}.")
            success, message = self._parameter_controller.write_parameters(runtime_requests)
            if success:
                self._set_status_result("WRITE SENT", message)
                self.uuid_section.set_last_workbook_action(f"{labels} runtime write in progress")
            else:
                self._workbook_runtime_write_pending = False
                self._set_status_result("FAIL", message)
                self.console_message.emit(f"[Production] {message}")
                return
        self._refresh_workbook_action_states()
        self._refresh_connection_status()

    def _handle_verify_uuid(self) -> None:
        if (
            self._workbook_eeprom_save_pending
            or self._workbook_eeprom_settle_active
            or self._workbook_parameter_write_pending
            or self._workbook_runtime_write_pending
        ):
            return
        try:
            node_id, node_name = self.test_control_section.selected_node()
        except RuntimeError as exc:
            self._set_status_result("READY", str(exc))
            self.console_message.emit(f"[Production] {exc}")
            return

        requests = self._build_workbook_parameter_requests(node_id, node_name)
        if requests is None:
            return
        requests_to_verify, skipped_labels = self._filter_verify_requests_by_previous_verification(requests)
        if skipped_labels:
            self.progress_section.append_step(
                f"SKIPPED: {len(skipped_labels)} parameter(s) already passed read-back verification."
            )
        if not requests_to_verify:
            if self._all_supported_workbook_parameters_passed():
                cached_results = self._get_cached_parameter_verification_results()
                if cached_results:
                    self._handle_parameter_verification_finished(
                        True,
                        "Workbook parameter read-back verification",
                        cached_results,
                    )
                else:
                    self._set_status_result("PASS", "Workbook parameter read-back verification")
                    self.uuid_section.set_workbook_validation_result(True, "")
                    self.uuid_section.set_last_workbook_action("Workbook parameter read-back verification completed")
                self._refresh_connection_status()
                return
            self._set_status_result("FAIL", "Workbook parameter read-back verification could not be completed.")
            self._refresh_connection_status()
            return
        self._pending_parameter_requests = requests_to_verify
        self._set_status_result("READING PARAMETERS", f"Reading and verifying workbook parameters for Node {node_id} {node_name}.")
        started = self._parameter_controller.verify_parameters(requests_to_verify)
        if not started:
            self._pending_parameter_requests = []
        self._refresh_connection_status()

    def _reset_workbook_workflow_state(self) -> None:
        self._parameter_controller.reset_workbook_parameter_workflow()
        self._pending_parameter_requests = []
        self._pending_persistent_parameter_requests = []
        self._pending_runtime_parameter_requests = []
        self._clear_parameter_verification_cache()
        self._workbook_loaded = False
        self._workbook_write_completed = False
        self._workbook_verification_passed = False
        self._workbook_parameter_write_pending = False
        self._workbook_runtime_write_pending = False
        self._workbook_eeprom_save_pending = False
        self._workbook_eeprom_save_failed = False
        self._workbook_eeprom_settle_active = False
        self._eeprom_save_settle_timer.stop()

    def _build_workbook_parameter_requests(self, node_id: int, node_name: str) -> list[ParameterRequest] | None:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            message = "Load an IPQC workbook first."
            self._set_status_result("FAIL", message)
            self.console_message.emit(f"[Production] {message}")
            return None

        supported_definitions, validation_error = self._get_supported_workbook_parameter_definitions()
        if validation_error is not None:
            self._set_status_result("FAIL", validation_error)
            self.console_message.emit(f"[Production] {validation_error}")
            return None

        requests: list[ParameterRequest] = []
        for definition in supported_definitions:
            expected_text = self._read_parameter_expected_text(definition)
            request = self._parameter_controller.build_parameter_request(
                definition,
                node_id,
                node_name,
                expected_text,
            )
            requests.append(request)
        if not requests:
            message = "No supported programming parameters are populated in the active IPQC workbook sheet."
            self._set_status_result("FAIL", message)
            self.console_message.emit(f"[Production] {message}")
            return None
        return requests

    def _read_parameter_expected_text(self, definition: ParameterDefinition) -> str:
        return self._ipqc_excel_adapter.read_programming_parameter_source(definition.name)

    def _handle_parameter_write_finished(self, passed: bool, reason: str) -> None:
        self._workbook_parameter_write_pending = False
        self._workbook_runtime_write_pending = False
        if not passed:
            self._workbook_write_completed = False
            self._workbook_verification_passed = False
            self._workbook_eeprom_save_pending = False
            self._workbook_eeprom_save_failed = True
            self._workbook_eeprom_settle_active = False
            self._pending_persistent_parameter_requests = []
            self._pending_runtime_parameter_requests = []
            self._eeprom_save_settle_timer.stop()
            self._set_status_result("FAIL", reason, append_to_log=False)
            self.uuid_section.set_last_workbook_action(f"Workbook parameter write failed: {reason}")
            self.progress_section.append_step(reason, level="error")
            self._refresh_workbook_action_states()
            return

        if self._pending_persistent_parameter_requests and not self._workbook_eeprom_save_pending and not self._workbook_eeprom_save_failed:
            node_id, node_name = self.test_control_section.selected_node()
            self._workbook_eeprom_save_pending = True
            self.uuid_section.set_last_workbook_action("Persistent parameters written; requesting EEPROM save")
            save_started = self._parameter_controller.save_parameters_to_eeprom(node_id, node_name)
            if save_started:
                self.progress_section.append_step(f"EEPROM save requested for Node {node_id} {node_name}")
                self._pending_persistent_parameter_requests = []
            else:
                self._workbook_eeprom_save_pending = False
                self._pending_persistent_parameter_requests = []
                self._pending_runtime_parameter_requests = []
                self._workbook_write_completed = False
                self._set_status_result("FAIL", "Failed to request EEPROM save.", append_to_log=False)
                self.console_message.emit("[Production] Failed to request EEPROM save.")
        elif self._pending_runtime_parameter_requests:
            self._workbook_runtime_write_pending = False
            self._workbook_write_completed = True
            self._pending_runtime_parameter_requests = []
            self.uuid_section.set_last_workbook_action("Runtime parameters written")
        self._refresh_workbook_action_states()

    def _handle_parameter_verification_finished(
        self,
        passed: bool,
        reason: str,
        results_object: object,
    ) -> None:
        results = [result for result in results_object if isinstance(result, ParameterVerificationResult)]
        self._cache_parameter_verification_results(results)
        uuid_result = self._last_parameter_verification_results_by_name.get("UUID")
        pwm_result = self._last_parameter_verification_results_by_name.get("PWM")
        uuid_actual = uuid_result.actual_text if uuid_result and uuid_result.actual_text else "-"
        pwm_actual = pwm_result.actual_text if pwm_result and pwm_result.actual_text else "-"
        self._current_programmed_pwm_value = pwm_actual
        self.uuid_section.set_programmed_values(uuid_actual, pwm_actual, "PASS" if passed else "FAIL")

        workbook_ok = True
        if self._ipqc_excel_adapter.has_loaded_workbook():
            for result in results:
                if not result.actual_text:
                    continue
                workbook_ok = self._update_parameter_cells_in_workbook_memory(
                    definition=result.definition,
                    actual_value=result.actual_text,
                    check_result="PASS" if result.passed else "FAIL",
                    silent=True,
                ) and workbook_ok

        all_required_passed = self._all_supported_workbook_parameters_passed()
        self._workbook_verification_passed = passed and workbook_ok and all_required_passed
        self.uuid_section.set_workbook_validation_result(self._workbook_verification_passed, "" if self._workbook_verification_passed else reason)
        self.uuid_section.set_last_workbook_action("Workbook parameter read-back verification completed")
        if self._workbook_verification_passed:
            self._set_status_result("PASS", "Workbook parameter read-back verification")
        else:
            self._set_status_result("FAIL", reason, append_to_log=False)
            for result in results:
                if result.actual_text:
                    actual_text = result.actual_text
                else:
                    actual_text = "timeout"
                self.progress_section.append_step(
                    f"{result.definition.name} read-back verification - expected {result.expected_text}, actual {actual_text}",
                    level="pass" if result.passed else "error",
        )
        self._pending_parameter_requests = []
        self._refresh_workbook_action_states()

    def _cache_parameter_verification_results(self, results: list[ParameterVerificationResult]) -> None:
        for result in results:
            existing = self._last_parameter_verification_results_by_name.get(result.definition.name)
            if existing is not None and existing.passed and not result.passed:
                continue
            self._last_parameter_verification_results_by_name[result.definition.name] = result

    def _clear_parameter_verification_cache(self) -> None:
        self._last_parameter_verification_results_by_name = {}
        self._workbook_verification_passed = False
        if self._ipqc_excel_adapter.has_loaded_workbook():
            self.uuid_section.set_workbook_validation_ready()

    def _invalidate_parameter_verification_cache_for_requests(self, requests: list[ParameterRequest]) -> None:
        invalidated = False
        for request in requests:
            if request.definition.name in self._last_parameter_verification_results_by_name:
                invalidated = True
            self._last_parameter_verification_results_by_name.pop(request.definition.name, None)
        if invalidated:
            self._workbook_verification_passed = False
            if self._ipqc_excel_adapter.has_loaded_workbook():
                self.uuid_section.set_workbook_validation_ready()

    def _filter_verify_requests_by_previous_verification(
        self,
        requests: list[ParameterRequest],
    ) -> tuple[list[ParameterRequest], list[str]]:
        if not self._last_parameter_verification_results_by_name:
            return list(requests), []

        selected_requests: list[ParameterRequest] = []
        skipped_labels: list[str] = []
        for request in requests:
            previous_result = self._last_parameter_verification_results_by_name.get(request.definition.name)
            if previous_result is not None and previous_result.passed:
                skipped_labels.append(self._parameter_write_log_name(request.definition))
                continue
            selected_requests.append(request)
        return selected_requests, skipped_labels

    def _get_cached_parameter_verification_results(self) -> list[ParameterVerificationResult]:
        supported_definitions, validation_error = self._get_supported_workbook_parameter_definitions()
        if validation_error is not None:
            return list(self._last_parameter_verification_results_by_name.values())
        results: list[ParameterVerificationResult] = []
        for definition in supported_definitions:
            result = self._last_parameter_verification_results_by_name.get(definition.name)
            if result is not None:
                results.append(result)
        return results

    def _all_supported_workbook_parameters_passed(self) -> bool:
        supported_definitions, validation_error = self._get_supported_workbook_parameter_definitions()
        if validation_error is not None:
            return False
        if not supported_definitions:
            return False
        return all(
            (self._last_parameter_verification_results_by_name.get(definition.name) is not None)
            and self._last_parameter_verification_results_by_name[definition.name].passed
            for definition in supported_definitions
        )

    def _filter_write_requests_by_previous_verification(
        self,
        requests: list[ParameterRequest],
    ) -> tuple[list[ParameterRequest], list[str]]:
        if not self._last_parameter_verification_results_by_name:
            return list(requests), []

        selected_requests: list[ParameterRequest] = []
        skipped_labels: list[str] = []
        for request in requests:
            previous_result = self._last_parameter_verification_results_by_name.get(request.definition.name)
            if previous_result is not None and previous_result.passed:
                skipped_labels.append(self._parameter_write_log_name(request.definition))
                continue
            selected_requests.append(request)
        return selected_requests, skipped_labels

    @staticmethod
    def _parameter_write_log_name(definition: ParameterDefinition) -> str:
        return "S/N" if definition.name == "UUID" else definition.name

    def _handle_eeprom_save_finished(self, passed: bool, reason: str) -> None:
        if passed:
            self._workbook_write_completed = True
            self._workbook_verification_passed = False
            self._workbook_eeprom_save_pending = False
            self._workbook_eeprom_save_failed = False
            self._workbook_eeprom_settle_active = True
            self.uuid_section.set_workbook_validation_ready()
            self.uuid_section.set_last_workbook_action("EEPROM save completed; ready for read-back verification")
            self.progress_section.append_step("EEPROM save ACK received.", level="info")
            self._set_status_result("READY", "EEPROM save completed; ready for read-back verification.", append_to_log=False)
            if self._pending_runtime_parameter_requests:
                self._workbook_write_completed = False
                self._workbook_runtime_write_pending = True
                runtime_requests = list(self._pending_runtime_parameter_requests)
                node_id, node_name = self.test_control_section.selected_node()
                success, message = self._parameter_controller.write_parameters(runtime_requests)
                if success:
                    self.uuid_section.set_last_workbook_action("Runtime parameters write in progress")
                    self.progress_section.append_step(f"Runtime parameters write requested for Node {node_id} {node_name}")
                else:
                    self._workbook_runtime_write_pending = False
                    self._workbook_write_completed = False
                    self._pending_runtime_parameter_requests = []
                    self._set_status_result("FAIL", message, append_to_log=False)
                    self.console_message.emit(f"[Production] {message}")
            self._eeprom_save_settle_timer.start(EEPROM_SAVE_SETTLE_MS)
        else:
            self._workbook_write_completed = False
            self._workbook_verification_passed = False
            self._workbook_eeprom_save_pending = False
            self._workbook_eeprom_save_failed = True
            self._workbook_eeprom_settle_active = False
            self._eeprom_save_settle_timer.stop()
            self.uuid_section.set_workbook_validation_result(False, reason)
            self.uuid_section.set_last_workbook_action(f"EEPROM save failed: {reason}")
            progress_message = reason
            reason_lower = reason.lower()
            if "ack not received" in reason_lower or "quiet mode" in reason_lower:
                progress_message = "Timed out waiting for EEPROM save ACK."
            self.progress_section.append_step(progress_message, level="error")
            self._set_status_result("FAIL", reason, append_to_log=False)
        self._refresh_workbook_action_states()

    def _handle_eeprom_save_settle_finished(self) -> None:
        self._eeprom_save_settle_timer.stop()
        self._parameter_controller.finish_eeprom_settle()
        self._workbook_eeprom_settle_active = False
        self._refresh_workbook_action_states()

    def _update_uuid_cells_in_workbook_memory(self, actual_value: str | int | None, passed: bool) -> bool:
        """Compatibility wrapper for the UUID workbook row update path."""
        return self._update_parameter_cells_in_workbook_memory(
            definition=WORKBOOK_PARAMETER_DEFINITIONS["UUID"],
            actual_value=actual_value,
            check_result="PASS" if passed else "FAIL",
        )

    def _update_pwm_cells_in_workbook_memory(self, actual_value: str | int | None, passed: bool) -> bool:
        """Compatibility wrapper for the PWM workbook row update path."""
        return self._update_parameter_cells_in_workbook_memory(
            definition=WORKBOOK_PARAMETER_DEFINITIONS["PWM"],
            actual_value=actual_value,
            check_result="PASS" if passed else "FAIL",
        )

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
        self.stage_section.set_stage_status("configuration", "pass")
        self._set_status_result("PASS", reason)
        self.progress_section.append_step(f"Completed test profile for Node {node_id} {node_name}")

    def _handle_test_failed(self, node_id: int, node_name: str, reason: str) -> None:
        is_timeout = "Timed out" in reason
        self.stage_section.set_stage_status("configuration", "fail")
        self._set_status_result("TIMEOUT" if is_timeout else "FAIL", reason)
        self.progress_section.append_step(
            f"{'Timed out' if is_timeout else 'Failed'} test profile for Node {node_id} {node_name}"
        )

    def _handle_test_unsupported(self, node_id: int, node_name: str, reason: str) -> None:
        self.stage_section.set_stage_status("configuration", "neutral")
        self._set_status_result("UNSUPPORTED", reason)
        self.progress_section.append_step(f"Unsupported test for Node {node_id} {node_name}")

    def _handle_test_aborted(self, node_id: int, node_name: str, reason: str) -> None:
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

    @staticmethod
    def _parse_pwm_value(pwm_text: str) -> int:
        return parse_pwm_value(pwm_text)

    def _update_parameter_cells_in_workbook_memory(
        self,
        *,
        definition: ParameterDefinition,
        actual_value: str | int | None,
        check_result: str,
        silent: bool = False,
    ) -> bool:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return False
        try:
            actual_value_or_empty: str | int = "" if actual_value is None else actual_value
            self._ipqc_excel_adapter.write_programming_parameter_result(definition.name, actual_value_or_empty, check_result)
            if not silent:
                self.uuid_section.set_last_workbook_action(f"{definition.name} report row updated in workbook memory")
                self.console_message.emit(
                    f"[Production] IPQC workbook {definition.name}({definition.actual_cell}/{definition.result_cell}) "
                    "report row updated in memory"
                )
            return True
        except Exception as exc:
            self.console_message.emit(f"[Production] Failed to update IPQC workbook {definition.name} report row: {exc}")
            self.progress_section.append_step(f"IPQC workbook {definition.name} result write failed")
            self.uuid_section.set_last_workbook_action(f"{definition.name} report row write failed: {exc}")
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
        except Exception as exc:
            self.uuid_section.set_last_workbook_action(f"Completed workbook save failed: {exc}")
            self._set_status_result("REPORTING ERROR", "Failed to save completed IPQC workbook.")
            self.console_message.emit(f"[Production] Failed to save completed IPQC workbook: {exc}")

    def _refresh_workbook_action_states(self) -> None:
        has_workbook = self._workbook_loaded and self._ipqc_excel_adapter.has_loaded_workbook()
        supported_definitions, validation_error = self._get_supported_workbook_parameter_definitions()
        has_supported_parameters = has_workbook and bool(supported_definitions) and validation_error is None
        connection_model = self._bridge.get_runtime_communication_model(create_if_missing=False)
        serial_connected = bool(connection_model.get("connected", False))
        try:
            self.test_control_section.selected_node()
            node_selected = True
        except RuntimeError:
            node_selected = False

        write_reason = self._get_workbook_action_gate_reason(
            has_workbook=has_workbook,
            has_supported_parameters=has_supported_parameters,
            serial_connected=serial_connected,
            node_selected=node_selected,
            validation_error=validation_error,
            operation_pending=
                self._workbook_parameter_write_pending
                or self._workbook_runtime_write_pending
                or self._workbook_eeprom_save_pending
                or self._workbook_eeprom_settle_active,
        )
        verify_reason = self._get_workbook_action_gate_reason(
            has_workbook=has_workbook,
            has_supported_parameters=has_supported_parameters,
            serial_connected=serial_connected,
            node_selected=node_selected,
            validation_error=validation_error,
            operation_pending=
                self._workbook_parameter_write_pending
                or self._workbook_runtime_write_pending
                or self._workbook_eeprom_save_pending
                or self._workbook_eeprom_save_failed
                or self._workbook_eeprom_settle_active,
        )
        self.uuid_section.load_workbook_button.setEnabled(True)
        write_enabled = (
            has_supported_parameters
            and serial_connected
            and node_selected
            and not self._workbook_parameter_write_pending
            and not self._workbook_runtime_write_pending
            and not self._workbook_eeprom_save_pending
            and not self._workbook_eeprom_settle_active
        )
        verify_enabled = (
            has_supported_parameters
            and serial_connected
            and node_selected
            and not self._workbook_parameter_write_pending
            and not self._workbook_runtime_write_pending
            and not self._workbook_eeprom_save_pending
            and not self._workbook_eeprom_save_failed
            and not self._workbook_eeprom_settle_active
        )
        self.uuid_section.write_button.setEnabled(write_enabled)
        self.uuid_section.write_button.setToolTip(
            "Write supported programming parameters to the connected MCU."
            if write_enabled
            else write_reason or "Write Parameters to MCU is unavailable."
        )
        self.uuid_section.verify_button.setEnabled(verify_enabled)
        self.uuid_section.verify_button.setToolTip(
            "Read back the MCU values and verify them against the workbook."
            if verify_enabled
            else verify_reason or "Read Back / Verify is unavailable."
        )
        self.uuid_section.save_button.setEnabled(has_workbook and self._workbook_verification_passed)
        self.uuid_section.save_button.setToolTip(
            "Save the completed workbook after verification passes."
            if has_workbook and self._workbook_verification_passed
            else "Save / Download Completed Workbook is enabled after verification passes."
        )
        self._refresh_sampling_action_states()

    def _refresh_sampling_action_states(self) -> None:
        connection_model = self._bridge.get_runtime_communication_model(create_if_missing=False)
        serial_connected = bool(connection_model.get("connected", False))
        node_selected = False
        try:
            self.test_control_section.selected_node()
            node_selected = True
        except RuntimeError:
            node_selected = False

        reason = ""
        enabled = (
            self._single_axis_passed
            and self._workbook_loaded
            and self._ipqc_excel_adapter.has_loaded_workbook()
            and serial_connected
            and node_selected
            and not self._sampling_controller.is_active()
            and not self._test_controller.is_active()
        )
        if not self._single_axis_passed:
            reason = "Sampling is available after Single Axis passes."
        elif not self._workbook_loaded or not self._ipqc_excel_adapter.has_loaded_workbook():
            reason = "Load an IPQC workbook first."
        elif not serial_connected:
            reason = "Connect the serial link before starting Sampling."
        elif not node_selected:
            reason = "Select a node before starting Sampling."
        elif self._sampling_controller.is_active():
            reason = "Sampling is already running."
        elif self._test_controller.is_active():
            reason = "Stop the active Production test before starting Sampling."
        else:
            try:
                active_group = self._ipqc_excel_adapter.active_sheet_group
                if not active_group:
                    raise RuntimeError("No active workbook sheet group is selected.")
                layout = self._ipqc_excel_adapter.discover_sampling_layout(active_group)
                reason = f"Sampling will write to {layout.sheet_name}."
            except Exception as exc:
                enabled = False
                reason = f"Sampling workbook is not ready: {exc}"
        self.stage_section.set_stage_enabled("sampling", enabled, reason)
        if self._sampling_popup is not None:
            popup_enabled = bool(enabled and not self._sampling_controller.is_active())
            self._sampling_popup.set_start_available(popup_enabled, reason)
            self._sampling_popup.set_stop_available(self._sampling_controller.is_active())
            self._sampling_popup.set_sampling_configuration_enabled(not self._sampling_controller.is_active())
            try:
                active_group = self._ipqc_excel_adapter.active_sheet_group
                sheet_name = self._ipqc_excel_adapter.resolve_sampling_sheet_name(active_group) if active_group else "-"
            except Exception:
                sheet_name = "-"
            try:
                node_id, node_name = self.test_control_section.selected_node()
            except RuntimeError:
                node_id = self._sampling_session.node_id if self._sampling_session is not None else None
                node_name = self._sampling_session.node_name if self._sampling_session is not None else None
            self._sampling_popup.set_context(node_id, node_name, sheet_name)
            if self._sampling_controller.is_active():
                self._sampling_popup.set_resume_available(False, "Resume unavailable: Sampling is already running.")
                self._sampling_popup.set_resume_hint("Resume unavailable: Sampling is already running.")
            else:
                resume_enabled, resume_reason = self._sampling_controller.resume_availability(
                    node_id=node_id,
                    node_name=node_name,
                    base_group=active_group,
                )
                self._sampling_popup.set_resume_available(resume_enabled, resume_reason)
                self._sampling_popup.set_resume_hint(resume_reason)

    def _get_supported_workbook_parameter_definitions(self) -> tuple[list[ParameterDefinition], str | None]:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return [], "Load an IPQC workbook first."

        discovered_rows, raw_labels = self._ipqc_excel_adapter.discover_programming_parameter_rows()
        supported_definitions: list[ParameterDefinition] = []
        for definition in self._parameter_definitions:
            row = discovered_rows.get(self._normalize_programming_label(definition.name))
            if row is None:
                row = discovered_rows.get(self._normalize_programming_label(definition.label))
            if row is None:
                continue
            expected_text = self._ipqc_excel_adapter.read_cell_text(f"B{row}")
            if not expected_text.strip():
                continue
            try:
                self._parameter_controller.build_parameter_request(definition, 0, "", expected_text)
            except ValueError as exc:
                return [], f"Expected {definition.label} in workbook {definition.expected_cell} is invalid: {exc}"

            supported_definitions.append(definition)

        if not supported_definitions:
            labels_text = ", ".join(raw_labels) if raw_labels else "(none)"
            return [], f"No supported parameter rows found. Labels found: {labels_text}"
        return supported_definitions, None

    def _count_supported_workbook_parameters(self) -> tuple[int, list[str]]:
        supported_definitions, validation_error = self._get_supported_workbook_parameter_definitions()
        if validation_error and validation_error.startswith("No supported parameter rows found. Labels found:"):
            labels_text = validation_error.partition("Labels found: ")[2]
            raw_labels = [label.strip() for label in labels_text.split(",")] if labels_text and labels_text != "(none)" else []
            return len(supported_definitions), raw_labels
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return 0, []
        _discovered_rows, raw_labels = self._ipqc_excel_adapter.discover_programming_parameter_rows()
        return len(supported_definitions), raw_labels

    def _get_workbook_action_gate_reason(
        self,
        *,
        has_workbook: bool,
        has_supported_parameters: bool,
        serial_connected: bool,
        node_selected: bool,
        validation_error: str | None,
        operation_pending: bool,
    ) -> str:
        if not has_workbook:
            return "Load an IPQC workbook before writing or verifying."
        if validation_error is not None:
            return validation_error
        if not has_supported_parameters:
            return "No supported programming parameters are populated in the active IPQC workbook sheet."
        if not serial_connected:
            return "MCU is disconnected."
        if not node_selected:
            return "Select a Production node before writing or verifying."
        if operation_pending:
            return "A workbook parameter operation is already in progress."
        return ""

    @staticmethod
    def _normalize_programming_label(value: str) -> str:
        return " ".join(str(value).strip().casefold().split())

    def _has_valid_workbook_parameter(self, definition: ParameterDefinition) -> bool:
        if not self._ipqc_excel_adapter.has_loaded_workbook():
            return False
        try:
            expected_text = self._read_parameter_expected_text(definition)
            self._parameter_controller.build_parameter_request(definition, 0, "", expected_text)
            return True
        except (RuntimeError, ValueError):
            return False

    @staticmethod
    def _is_valid_uuid_text(serial_text: str) -> bool:
        try:
            parse_uuid_value(serial_text)
            return True
        except ValueError:
            return False

    def _set_status_result(self, status: str, reason: str, *, append_to_log: bool = True) -> None:
        self.result_summary_section.set_result(status, reason)
        normalized = status.strip().upper()
        entry = f"{normalized}|{reason}"
        if append_to_log and entry != self._last_status_entry:
            level = "info"
            log_message = f"{status}: {reason}"
            if normalized == "PASS":
                level = "pass"
                log_message = reason
            elif normalized in {"FAIL", "TIMEOUT", "REPORTING ERROR"}:
                level = "fail"
                log_message = reason
            self.progress_section.append_step(log_message, level=level)
        self._last_status_entry = entry

    def _sampling_node_label(self) -> str:
        if self._sampling_session is not None:
            node_id = self._sampling_session.node_id
            node_name = self._sampling_session.node_name
        else:
            try:
                node_id, node_name = self.test_control_section.selected_node()
            except RuntimeError:
                node_id = None
                node_name = None
        if node_id is None or not node_name:
            return "Node ?"
        return f"Node {int(node_id)} {node_name}"


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
        self._port_combo.setObjectName("ProductionCommPortCombo")
        self._baud_combo = QComboBox()
        self._baud_combo.setObjectName("ProductionCommBaudCombo")
        self._connect_button = QPushButton("Connect")
        self._status_label = QLabel("○ Disconnected")
        self._status_label.setObjectName("DetailValue")
        self._connected = False
        self._firmware_value = "-"
        self._nodes_firmware_value = "-"

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

        self._nodes_firmware_label = QLabel("Nodes Firmware Version: -")
        self._nodes_firmware_label.setObjectName("DetailValue")
        self.body_layout.addWidget(self._nodes_firmware_label)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(190)

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
        rows = list(nodes_model.get("rows", []))
        firmware_values = [str(row.get("firmware", "")).strip() for row in rows if str(row.get("firmware", "")).strip()]
        self._firmware_value = firmware_values[0] if firmware_values else "-"
        if firmware_values:
            unique_versions = sorted({value for value in firmware_values if value})
            self._nodes_firmware_value = ", ".join(unique_versions)
        else:
            self._nodes_firmware_value = "-"
        self._firmware_label.setText(f"MCU Firmware Version: {self._firmware_value}")
        self._nodes_firmware_label.setText(f"Nodes Firmware Version: {self._nodes_firmware_value}")

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
        self._port_combo.setObjectName("ProductionCommPortCombo")
        self._baud_combo = QComboBox()
        self._baud_combo.setObjectName("ProductionCommBaudCombo")
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
        self._actual_pwm_value = "-"
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
    sampling_requested = pyqtSignal()
    performance_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Test Stages", "")
        self._rows: dict[str, tuple[QLabel, QPushButton]] = {}
        self.body_layout.addStretch(1)
        self._add_stage_row("single_axis", "Single Axis Functional Test", self.single_axis_requested.emit)
        self._add_stage_row("sampling", "Sampling Test", self.sampling_requested.emit)
        self._add_stage_row("performance", "Performance Test", self.performance_requested.emit)
        self.body_layout.addStretch(1)
        self.reset_stage_states()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(190)

    def _add_stage_row(self, key: str, label_text: str, handler) -> None:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        dot = QLabel()
        dot.setFixedSize(10, 10)
        dot.setFrameShape(QFrame.Shape.NoFrame)
        row_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(label_text)
        label.setObjectName("DetailValue")
        row_layout.addWidget(label, 1)

        button = QPushButton("Start Test")
        button.setProperty("tone", "secondary")
        button.clicked.connect(handler)
        row_layout.addWidget(button)

        self._rows[key] = (dot, button)
        self.body_layout.addWidget(row)

    def reset_stage_states(self) -> None:
        for key in self._rows:
            self.set_stage_status(key, "neutral")
        self.set_stage_enabled("single_axis", True)
        self.set_stage_enabled("sampling", False, "Sampling is available after Single Axis passes.")
        self.set_stage_enabled("performance", False, "Performance Test is not implemented yet.")

    def set_stage_status(self, key: str, status: str) -> None:
        row = self._rows.get(key)
        if row is None:
            return
        dot, button = row
        normalized = status.strip().lower()
        color = "#B0B7C3"
        if normalized in {"testing", "pending"}:
            color = "#D98732"
        elif normalized in {"pass", "success"}:
            color = "#2E7D32"
        elif normalized in {"fail", "failure", "timeout"}:
            color = "#C62828"
        dot.setStyleSheet(f"border-radius: 5px; background: {color};")

    def set_stage_enabled(self, key: str, enabled: bool, reason: str = "") -> None:
        row = self._rows.get(key)
        if row is None:
            return
        _dot, button = row
        button.setEnabled(bool(enabled))
        if enabled:
            button.setToolTip("Start Test")
        else:
            button.setToolTip(reason or "Stage is not available.")

    def stage_enabled(self, key: str) -> bool:
        row = self._rows.get(key)
        if row is None:
            return False
        return row[1].isEnabled()

    def stage_tooltip(self, key: str) -> str:
        row = self._rows.get(key)
        if row is None:
            return ""
        return row[1].toolTip()


class _NodeStatusSection(PanelFrame):
    update_nodes_requested = pyqtSignal()
    clear_nodes_requested = pyqtSignal()
    robot_power_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Robot Arm Node Status", "")
        self._led_by_node_id: dict[int, QLabel] = {}
        self._connected = False

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        button_row.addStretch(1)
        self._robot_power_button = QPushButton("Robot Power ON/OFF")
        self._robot_power_button.setObjectName("RobotPowerButton")
        self._robot_power_button.setProperty("tone", "secondary")
        self._robot_power_button.clicked.connect(self._handle_robot_power_clicked)
        button_row.addWidget(self._robot_power_button)

        self._update_button = QPushButton("Update Nodes")
        self._update_button.setObjectName("UpdateNodesButton")
        self._update_button.setProperty("tone", "secondary")
        self._update_button.clicked.connect(self.update_nodes_requested.emit)
        button_row.addWidget(self._update_button)

        self._clear_button = QPushButton("Clear")
        self._clear_button.setObjectName("ClearNodesButton")
        self._clear_button.setProperty("tone", "secondary")
        self._clear_button.clicked.connect(self.clear_nodes_requested.emit)
        button_row.addWidget(self._clear_button)
        self.body_layout.addLayout(button_row)

        node_grid = QGridLayout()
        node_grid.setContentsMargins(0, 0, 0, 0)
        node_grid.setHorizontalSpacing(10)
        node_grid.setVerticalSpacing(4)
        node_grid.addWidget(QLabel(""), 0, 0)
        node_grid.addWidget(QLabel("Node"), 1, 0)
        for column, node_id in enumerate(range(2, 17), start=1):
            led = QLabel()
            led.setFixedSize(14, 14)
            led.setFrameShape(QFrame.Shape.NoFrame)
            node_grid.addWidget(led, 0, column, Qt.AlignmentFlag.AlignCenter)
            number_label = QLabel(str(node_id))
            number_label.setObjectName("DetailValue")
            number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            node_grid.addWidget(number_label, 1, column, Qt.AlignmentFlag.AlignCenter)
            self._led_by_node_id[node_id] = led
            self._set_led_state(node_id, False)
        self.body_layout.addLayout(node_grid)

    def set_connected(self, connected: bool) -> None:
        self._connected = bool(connected)
        self._robot_power_button.setEnabled(self._connected)

    def set_robot_power_state(self, power_on: bool | None) -> None:
        return

    def set_nodes(self, nodes_model: dict) -> None:
        connected_nodes = {int(node_id) for node_id in nodes_model.get("connected_nodes", [])}
        for node_id in self._led_by_node_id:
            self._set_led_state(node_id, node_id in connected_nodes)

    def clear_node_states(self) -> None:
        for node_id in self._led_by_node_id:
            self._set_led_state(node_id, False)

    def _handle_robot_power_clicked(self) -> None:
        self.robot_power_requested.emit()

    def _set_led_state(self, node_id: int, connected: bool) -> None:
        led = self._led_by_node_id.get(node_id)
        if led is None:
            return
        color = "#7ED957" if connected else "#1E5E20"
        led.setStyleSheet(f"border-radius: 7px; background: {color};")


class _TestControlSection(PanelFrame):
    run_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    clear_requested = pyqtSignal()
    node_selected = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Test Control", "")
        self._combo = QComboBox()
        self._combo.setObjectName("AxisSelectorCombo")
        for node_id, node_name in get_ml20_testable_nodes():
            self._combo.addItem(f"Node {node_id} - {node_name}", (node_id, node_name))
        self._combo.currentIndexChanged.connect(lambda _index: self.node_selected.emit())
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
        self._workbook_validation_text = "Workbook Validation: -"
        self._last_workbook_action_text = "-"
        self._workbook_output_text = WORKBOOK_OUTPUT_PENDING
        self._sheet_groups: list[str] = []
        self._selected_group = ""
        self._expected_serial_value = "-"
        self._expected_pwm_value = "-"
        self._expected_other_value = "-"
        self._actual_serial_value = "-"
        self._actual_pwm_value = "-"
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

        self._loaded_workbook_label = QLabel("Loaded Workbook: -")
        self._loaded_workbook_label.setObjectName("DetailValue")
        self._loaded_workbook_label.setWordWrap(True)
        self.body_layout.addWidget(self._loaded_workbook_label)

        self._last_workbook_action_label = QLabel("Last Workbook Action: -")
        self._last_workbook_action_label.setObjectName("DetailValue")
        self._last_workbook_action_label.setWordWrap(True)
        self.body_layout.addWidget(self._last_workbook_action_label)

        self._workbook_validation_label = QLabel("Workbook Validation: -")
        self._workbook_validation_label.setObjectName("DetailValue")
        self._workbook_validation_label.setWordWrap(True)
        self.body_layout.addWidget(self._workbook_validation_label)

    def set_workbook_path(self, path: str) -> None:
        display_name = Path(path).name if path else "-"
        self._loaded_workbook_label.setText(f"Loaded Workbook: {display_name}")
        self._loaded_workbook_label.setToolTip(path)

    def set_sheet_groups(self, groups: list[str], selected: str) -> None:
        self._sheet_groups = list(groups)
        self._selected_group = selected
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
        self.set_workbook_validation_result(passed, message)

    def set_workbook_validation_idle(self) -> None:
        self._workbook_validation_text = "Workbook Validation: -"
        self._workbook_validation_label.setText(self._workbook_validation_text)

    def set_workbook_validation_ready(self) -> None:
        self._workbook_validation_text = "Workbook Validation: READY"
        self._workbook_validation_label.setText(self._workbook_validation_text)

    def set_workbook_validation_result(self, passed: bool, message: str) -> None:
        if passed:
            self._workbook_validation_text = "Workbook Validation: PASSED"
            self._workbook_validation_label.setText(self._workbook_validation_text)
            return
        reason = message or "Verify failed"
        self._workbook_validation_text = f"Workbook Validation: FAILED ({reason})"
        self._workbook_validation_label.setText(self._workbook_validation_text)

    def set_workbook_output_path(self, path_or_status: str) -> None:
        self._workbook_output_text = path_or_status

    def set_last_workbook_action(self, status: str) -> None:
        self._last_workbook_action_text = status
        self._last_workbook_action_label.setText(f"Last Workbook Action: {status}")

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
        self._history_plain: list[str] = []
        self._history_html: list[str] = []

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        refresh_button = QPushButton("Refresh")
        refresh_button.setProperty("tone", "secondary")
        refresh_button.clicked.connect(self.refresh_requested.emit)
        controls.addWidget(refresh_button)
        clear_button = QPushButton("Clear")
        clear_button.setProperty("tone", "secondary")
        clear_button.clicked.connect(self.clear_requested.emit)
        controls.addWidget(clear_button)
        controls.addStretch(1)
        self.body_layout.addLayout(controls)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setObjectName("StatusProgressLog")
        self._log_output.setMinimumHeight(220)
        self._log_output.setMaximumHeight(320)
        self._log_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._log_output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._log_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body_layout.addWidget(self._log_output)

    def reset_steps(self, steps: list[str]) -> None:
        self._log_output.clear()
        self._history_plain.clear()
        self._history_html.clear()
        for step in steps:
            self.append_step(step)

    def set_profile_steps(self, step_names: list[str]) -> None:
        if step_names:
            self.append_step(f"Profile loaded with {len(step_names)} steps")

    def mark_profile_step(self, step_name: str, status: str) -> None:
        self.append_step(f"{step_name} - {status}")

    def append_step(self, step: str, *, level: str = "info") -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        color = "#000000"
        level_tag = "INFO"
        normalized = level.strip().lower()
        if normalized in {"success", "pass"}:
            color = "#2E7D32"
            level_tag = "PASS"
        elif normalized in {"error", "fail"}:
            color = "#C62828"
            level_tag = "FAIL"
        plain_text = f"[{timestamp}] [{level_tag}] {step}"
        escaped = html.escape(plain_text)
        self._history_plain.append(plain_text)
        if color:
            self._history_html.append(f"<span style='color:{color};'>{escaped}</span>")
        else:
            self._history_html.append(escaped)
        self._log_output.append(self._history_html[-1])
        scrollbar = self._log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_log(self) -> None:
        self._log_output.clear()
        self._history_plain.clear()
        self._history_html.clear()

    def to_plain_text(self) -> str:
        return "\n".join(self._history_plain)

    def to_html(self) -> str:
        return "<br>".join(self._history_html)

    def set_current_stage(self, text: str) -> None:
        return

    def set_current_node(self, text: str) -> None:
        return

    def set_current_action(self, text: str) -> None:
        return

    def set_overall_result(self, text: str) -> None:
        return
