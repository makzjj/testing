from __future__ import annotations

import dataclasses
import inspect
import os
import unittest
from dataclasses import FrozenInstanceError

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QTableWidget

import gui.workspace.dialogs.text_fit_config_dialog as text_fit_config_dialog_module
import gui.workspace.dialogs.text_fit_report_dialog as text_fit_report_dialog_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs import TextFitConfigDialog, TextFitReportDialog
from gui.workspace.models import FirmwareTestResult
from gui.workspace.pages.firmware_page import FirmwarePage


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.writes.append(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)


class _FakeBridge:
    def __init__(self, *, connected: bool = True) -> None:
        self.raw_config = {
            "robot": {
                "axes": {
                    "x": {"node_id": 3},
                    "z": {"node_id": 12},
                }
            }
        }
        self._runtime_window = _FakeRuntimeWindow(connected=connected)
        self.runtime_window_requests = 0

    def get_frame_loss_items(self) -> list[object]:
        return []

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return [(3, "X"), (12, "Z")]

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        self.runtime_window_requests += 1
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class FirmwareTextFitUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_run_text_fit_button_opens_config_dialog_and_sends_nothing(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        receiver_count_before = bridge._runtime_window.receivers(bridge._runtime_window.packet_received)

        button = page.findChild(QPushButton, "FirmwareFitRunTextButton")
        self.assertIsNotNone(button)
        assert button is not None
        button.click()
        self._app.processEvents()

        dialog = page._text_fit_config_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        self.assertTrue(dialog.isVisible())
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertEqual(bridge._runtime_window.backend_client.writes, [])
        self.assertEqual(bridge._runtime_window.receivers(bridge._runtime_window.packet_received), receiver_count_before)

    def test_config_dialog_uses_controller_cases_and_has_no_node_selector(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = TextFitConfigDialog(controller)

        case_table = dialog.findChild(QTableWidget, "TextFitConfigCaseTable")
        node_combo = dialog.findChild(QComboBox, "TextFitConfigNodeCombo")
        self.assertIsNotNone(case_table)
        assert case_table is not None
        self.assertIsNone(node_combo)
        self.assertEqual(case_table.rowCount(), len(controller.text_fit_case_definitions()))
        self.assertEqual(case_table.item(0, 1).text(), controller.text_fit_case_definitions()[0].name)
        self.assertEqual(case_table.item(0, 2).text(), "ver?")
        self.assertEqual(case_table.item(0, 3).text(), "--")
        self.assertEqual(case_table.item(0, 4).text(), "Query")

    def test_config_dialog_select_all_deselect_all_reset_defaults_and_accept_values(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = TextFitConfigDialog(controller)
        emitted: list[object] = []
        dialog.run_requested.connect(emitted.append)

        dialog._deselect_all()
        self.assertEqual(dialog.selected_case_ids(), [])
        self.assertFalse(dialog.run_button.isEnabled())

        dialog._select_all()
        self.assertEqual(len(dialog.selected_case_ids()), len(controller.text_fit_case_definitions()))
        self.assertTrue(dialog.run_button.isEnabled())

        dialog._deselect_all()
        dialog._reset_defaults()
        expected_defaults = [case.case_id for case in controller.text_fit_case_definitions() if case.selected_by_default]
        self.assertEqual(dialog.selected_case_ids(), expected_defaults)

        dialog._deselect_all()
        checkbox_host = dialog.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        self._app.processEvents()
        dialog.run_button.click()
        self._app.processEvents()

        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(emitted, [[controller.text_fit_case_definitions()[0].case_id]])

    def test_page_launch_flow_opens_report_dialog_and_starts_controller_after_run_confirmation(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)

        page._open_text_fit_dialog()
        config = page._text_fit_config_dialog
        self.assertIsNotNone(config)
        assert config is not None
        config._deselect_all()
        checkbox_host = config.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)

        config.run_button.click()
        self._app.processEvents()

        report = page._text_fit_report_dialog
        self.assertIsNotNone(report)
        assert report is not None
        self.assertTrue(report.isVisible())
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), 1)
        self.assertEqual(report.findChild(QLabel, "TextFitReportCurrentCaseLabel").text(), "Version Query")

    def test_report_dialog_renders_snapshot_and_live_case_progress(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query", "text-fit-uart-status-query"]))
        dialog = TextFitReportDialog(controller)
        self._app.processEvents()

        self.assertEqual(dialog.current_case_label.text(), "Version Query")
        self.assertEqual(dialog.progress_label.text(), "0 / 2")

        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()

        self.assertEqual(dialog.results_table.rowCount(), 1)
        self.assertEqual(dialog.results_table.item(0, 0).text(), "Version Query")
        self.assertEqual(dialog.results_table.item(0, 1).text(), "ver?")
        self.assertEqual(dialog.results_table.item(0, 7).text(), "PASS")
        self.assertEqual(dialog.current_case_label.text(), "UART Status Query")
        self.assertEqual(dialog.progress_label.text(), "1 / 2")

    def test_report_dialog_completion_and_cancelled_state_preserve_results(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query", "text-fit-uart-status-query"]))
        dialog = TextFitReportDialog(controller)

        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()
        dialog.cancel_button.click()
        self._app.processEvents()

        self.assertEqual(dialog.results_table.rowCount(), 2)
        self.assertEqual(dialog.results_table.item(1, 7).text(), "CANCELLED")
        self.assertFalse(dialog.cancel_button.isEnabled())
        self.assertTrue(dialog.close_button.isEnabled())

        second_bridge = _FakeBridge()
        second_controller = FirmwareIntegrationController(second_bridge)
        self.assertTrue(second_controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        second_dialog = TextFitReportDialog(second_controller)
        second_bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()
        self.assertEqual(second_dialog.results_table.rowCount(), 1)
        self.assertEqual(second_dialog.results_table.item(0, 7).text(), "PASS")
        self.assertFalse(second_dialog.cancel_button.isEnabled())
        self.assertTrue(second_dialog.close_button.isEnabled())

    def test_manual_verification_prompt_delegates_back_to_controller(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.text_fit_case_definitions()[0],
            case_id="text-fit-version-query-manual-ui",
            manual_verification=True,
            manual_prompt="Confirm version is visible.",
        )
        self.assertTrue(controller.start_text_fit(cases=[manual_case]))
        dialog = TextFitReportDialog(controller)
        dialog.show()
        self._app.processEvents()
        calls: list[tuple[bool, str | None]] = []
        original_submit = controller.submit_text_fit_manual_verification

        def _wrapped_submit(passed: bool, message: str | None = None) -> bool:
            calls.append((passed, message))
            return original_submit(passed, message)

        controller.submit_text_fit_manual_verification = _wrapped_submit  # type: ignore[method-assign]
        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()

        self.assertTrue(dialog.manual_prompt_container.isVisible())
        dialog.manual_note_input.setText("Operator confirmed output.")
        dialog.manual_pass_button.click()
        self._app.processEvents()

        self.assertEqual(calls, [(True, "Operator confirmed output.")])
        self.assertEqual(dialog.results_table.rowCount(), 1)
        self.assertEqual(dialog.results_table.item(0, 7).text(), "PASS")
        self.assertFalse(dialog.manual_prompt_container.isVisible())

    def test_config_cancel_close_lifecycle_and_reopen_are_clean(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = TextFitConfigDialog(controller)
        dialog.show()
        self._app.processEvents()
        dialog.reject()
        self._app.processEvents()

        snapshot = controller.text_fit_status_snapshot()
        self.assertFalse(snapshot.running)
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        page._open_text_fit_dialog()
        config = page._text_fit_config_dialog
        assert config is not None
        config._deselect_all()
        checkbox_host = config.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        config.run_button.click()
        self._app.processEvents()

        report = page._text_fit_report_dialog
        assert report is not None
        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()
        report.close()
        self._app.processEvents()
        self.assertIsNone(page._text_fit_report_dialog)
        self.assertEqual(page._open_text_fit_dialog(), "Opened Text Firmware Integration Test configuration dialog.")

    def test_report_close_active_completed_and_awaiting_verification_behaviors(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query", "text-fit-uart-status-query"]))
        dialog = TextFitReportDialog(controller)

        calls = 0
        original_cancel = controller.cancel_text_fit

        def _wrapped_cancel() -> bool:
            nonlocal calls
            calls += 1
            return original_cancel()

        controller.cancel_text_fit = _wrapped_cancel  # type: ignore[method-assign]
        dialog.close()
        self._app.processEvents()

        snapshot = controller.text_fit_status_snapshot()
        self.assertEqual(calls, 1)
        self.assertFalse(snapshot.running)
        self.assertEqual(snapshot.overall_status, "CANCELLED")
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

        second_bridge = _FakeBridge()
        second_controller = FirmwareIntegrationController(second_bridge)
        self.assertTrue(second_controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        second_dialog = TextFitReportDialog(second_controller)
        second_bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()

        second_calls = 0
        second_original_cancel = second_controller.cancel_text_fit

        def _wrapped_cancel_second() -> bool:
            nonlocal second_calls
            second_calls += 1
            return second_original_cancel()

        second_controller.cancel_text_fit = _wrapped_cancel_second  # type: ignore[method-assign]
        second_dialog.close()
        self._app.processEvents()
        self.assertEqual(second_calls, 0)
        self.assertEqual(second_controller.text_fit_status_snapshot().overall_status, "COMPLETED")

        third_bridge = _FakeBridge()
        third_controller = FirmwareIntegrationController(third_bridge)
        manual_case = dataclasses.replace(
            third_controller.text_fit_case_definitions()[0],
            case_id="text-fit-version-query-awaiting-ui",
            manual_verification=True,
            manual_prompt="Confirm version is visible.",
        )
        self.assertTrue(third_controller.start_text_fit(cases=[manual_case]))
        third_dialog = TextFitReportDialog(third_controller)
        third_dialog.show()
        self._app.processEvents()
        third_bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self._app.processEvents()
        self.assertTrue(third_dialog.manual_prompt_container.isVisible())

        third_dialog.close()
        self._app.processEvents()
        third_snapshot = third_controller.text_fit_status_snapshot()
        self.assertFalse(third_snapshot.running)
        self.assertEqual(third_snapshot.overall_status, "CANCELLED")
        self.assertFalse(third_controller._timeout_timer.isActive())
        self.assertFalse(third_controller._transport_adapter.is_attached)

    def test_snapshot_result_and_dialog_architecture_constraints_hold(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        snapshot = controller.text_fit_status_snapshot()
        self.assertTrue(dataclasses.is_dataclass(snapshot))
        self.assertIsInstance(snapshot.results, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.running = True  # type: ignore[misc]

        result_fields = {field.name for field in dataclasses.fields(FirmwareTestResult)}
        self.assertTrue({"case_id", "status", "expected", "actual", "tx_bytes", "rx_bytes", "latency_ms", "message", "manual_verification_outcome"} <= result_fields)

        config_source = inspect.getsource(text_fit_config_dialog_module)
        report_source = inspect.getsource(text_fit_report_dialog_module)
        for source in (config_source, report_source):
            self.assertNotIn("_TextFitWorkflow", source)
            self.assertNotIn("_active_operation", source)
            self.assertNotIn("text_cmd_builders", source)
            self.assertNotIn("decode_text_command_response", source)
            self.assertNotIn("backend_client", source)
            self.assertNotIn("packet_received", source)
            self.assertNotIn(".decode(", source)
            self.assertNotIn(".startswith(", source)
        self.assertNotIn("Export", config_source)
        self.assertNotIn("save_location", report_source)


if __name__ == "__main__":
    unittest.main()
