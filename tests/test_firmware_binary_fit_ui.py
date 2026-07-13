from __future__ import annotations

import dataclasses
import inspect
import os
import unittest
from dataclasses import FrozenInstanceError

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QTableWidget

import gui.workspace.dialogs.binary_fit_config_dialog as binary_fit_config_dialog_module
import gui.workspace.dialogs.binary_fit_report_dialog as binary_fit_report_dialog_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs import BinaryFitConfigDialog, BinaryFitReportDialog
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


class FirmwareBinaryFitUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_run_binary_fit_button_opens_config_dialog_and_sends_nothing(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        receiver_count_before = bridge._runtime_window.receivers(bridge._runtime_window.packet_received)

        button = page.findChild(QPushButton, "FirmwareFitRunBinaryButton")
        self.assertIsNotNone(button)
        assert button is not None
        button.click()
        self._app.processEvents()

        dialog = page._binary_fit_config_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        self.assertTrue(dialog.isVisible())
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertEqual(bridge._runtime_window.backend_client.writes, [])
        self.assertEqual(bridge._runtime_window.receivers(bridge._runtime_window.packet_received), receiver_count_before)

    def test_config_dialog_uses_canonical_node_options_and_controller_case_definitions(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = BinaryFitConfigDialog(controller)

        node_combo = dialog.findChild(QComboBox, "BinaryFitConfigNodeCombo")
        case_table = dialog.findChild(QTableWidget, "BinaryFitConfigCaseTable")
        self.assertIsNotNone(node_combo)
        self.assertIsNotNone(case_table)
        assert node_combo is not None and case_table is not None
        self.assertEqual([node_combo.itemData(i) for i in range(node_combo.count())], [3, 12])
        self.assertEqual(case_table.rowCount(), len(controller.binary_fit_case_definitions()))
        self.assertEqual(case_table.item(0, 1).text(), controller.binary_fit_case_definitions()[0].name)

    def test_config_dialog_select_all_deselect_all_and_reset_defaults_work(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = BinaryFitConfigDialog(controller)

        dialog._deselect_all()
        self.assertEqual(dialog.selected_case_ids(), [])
        self.assertFalse(dialog.run_button.isEnabled())

        dialog._select_all()
        self.assertEqual(len(dialog.selected_case_ids()), len(controller.binary_fit_case_definitions()))
        self.assertTrue(dialog.run_button.isEnabled())

        dialog._deselect_all()
        dialog._reset_defaults()
        expected_defaults = [case.case_id for case in controller.binary_fit_case_definitions() if case.selected_by_default]
        self.assertEqual(dialog.selected_case_ids(), expected_defaults)

    def test_config_dialog_opening_and_editing_send_nothing_and_accepts_selected_values(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = BinaryFitConfigDialog(controller)
        emitted: list[tuple[int, object]] = []
        dialog.run_requested.connect(lambda node_id, case_ids: emitted.append((node_id, case_ids)))

        dialog.show()
        self._app.processEvents()
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])

        dialog._deselect_all()
        self._app.processEvents()
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertFalse(dialog.run_button.isEnabled())

        checkbox_host = dialog.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        dialog.node_combo.setCurrentIndex(1)
        self._app.processEvents()
        self.assertTrue(dialog.run_button.isEnabled())

        dialog.run_button.click()
        self._app.processEvents()
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)
        self.assertEqual(emitted, [(12, [controller.binary_fit_case_definitions()[0].case_id])])
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])

    def test_page_launch_flow_opens_report_dialog_and_starts_controller_after_run_confirmation(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)

        page._open_binary_fit_dialog()
        config = page._binary_fit_config_dialog
        self.assertIsNotNone(config)
        assert config is not None
        config._deselect_all()
        checkbox_host = config.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        config.node_combo.setCurrentIndex(0)

        config.run_button.click()
        self._app.processEvents()

        report = page._binary_fit_report_dialog
        self.assertIsNotNone(report)
        assert report is not None
        self.assertTrue(report.isVisible())
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [(3, [0xC8, 0x3F])])
        self.assertEqual(report.findChild(QLabel, "BinaryFitReportCurrentCaseLabel").text(), "GETVER")

    def test_report_dialog_renders_snapshot_and_live_case_progress(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver", "binary-fit-getpos"]))
        dialog = BinaryFitReportDialog(controller)
        self._app.processEvents()

        self.assertEqual(dialog.target_node_label.text(), "Node 03")
        self.assertEqual(dialog.current_case_label.text(), "GETVER")
        self.assertEqual(dialog.progress_label.text(), "0 / 2")

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()

        self.assertEqual(dialog.results_table.rowCount(), 1)
        self.assertEqual(dialog.results_table.item(0, 0).text(), "binary-fit-getver")
        self.assertEqual(dialog.results_table.item(0, 6).text(), "PASS")
        self.assertEqual(dialog.current_case_label.text(), "GETPOS")
        self.assertEqual(dialog.progress_label.text(), "1 / 2")

    def test_report_dialog_completion_and_cancelled_state_preserve_results(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver", "binary-fit-getpos"]))
        dialog = BinaryFitReportDialog(controller)

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()
        dialog.cancel_button.click()
        self._app.processEvents()

        self.assertEqual(dialog.results_table.rowCount(), 2)
        self.assertEqual(dialog.results_table.item(1, 6).text(), "CANCELLED")
        self.assertFalse(dialog.cancel_button.isEnabled())
        self.assertTrue(dialog.close_button.isEnabled())

        second_bridge = _FakeBridge()
        second_controller = FirmwareIntegrationController(second_bridge)
        self.assertTrue(second_controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        second_dialog = BinaryFitReportDialog(second_controller)
        second_bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()
        self.assertEqual(second_dialog.results_table.rowCount(), 1)
        self.assertEqual(second_dialog.results_table.item(0, 6).text(), "PASS")
        self.assertFalse(second_dialog.cancel_button.isEnabled())
        self.assertTrue(second_dialog.close_button.isEnabled())

    def test_manual_verification_prompt_delegates_back_to_controller(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.binary_fit_case_definitions()[0],
            case_id="binary-fit-getver-manual-ui",
            manual_verification=True,
            manual_prompt="Confirm version is visible.",
        )
        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[manual_case]))
        dialog = BinaryFitReportDialog(controller)
        dialog.show()
        self._app.processEvents()
        calls: list[tuple[bool, str | None]] = []
        original_submit = controller.submit_binary_fit_manual_verification

        def _wrapped_submit(passed: bool, message: str | None = None) -> bool:
            calls.append((passed, message))
            return original_submit(passed, message)

        controller.submit_binary_fit_manual_verification = _wrapped_submit  # type: ignore[method-assign]
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()

        self.assertTrue(dialog.manual_prompt_container.isVisible())
        dialog.manual_note_input.setText("Operator confirmed output.")
        dialog.manual_pass_button.click()
        self._app.processEvents()

        self.assertEqual(calls, [(True, "Operator confirmed output.")])
        self.assertEqual(dialog.results_table.rowCount(), 1)
        self.assertEqual(dialog.results_table.item(0, 6).text(), "PASS")
        self.assertFalse(dialog.manual_prompt_container.isVisible())

    def test_report_dialog_close_while_awaiting_manual_verification_cancels_cleanly(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.binary_fit_case_definitions()[0],
            case_id="binary-fit-getver-awaiting-ui",
            manual_verification=True,
            manual_prompt="Confirm version is visible.",
        )
        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[manual_case]))
        dialog = BinaryFitReportDialog(controller)
        dialog.show()
        self._app.processEvents()

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()
        self.assertTrue(dialog.manual_prompt_container.isVisible())

        dialog.close()
        self._app.processEvents()

        snapshot = controller.binary_fit_status_snapshot()
        self.assertFalse(snapshot.running)
        self.assertEqual(snapshot.overall_status, "CANCELLED")
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

    def test_config_dialog_cancel_leaves_controller_idle(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = BinaryFitConfigDialog(controller)

        dialog.show()
        self._app.processEvents()
        dialog.reject()
        self._app.processEvents()

        snapshot = controller.binary_fit_status_snapshot()
        self.assertFalse(snapshot.running)
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

    def test_report_dialog_close_while_active_cancels_once_and_cleans_up(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver", "binary-fit-getpos"]))
        dialog = BinaryFitReportDialog(controller)

        calls = 0
        original_cancel = controller.cancel_binary_fit

        def _wrapped_cancel() -> bool:
            nonlocal calls
            calls += 1
            return original_cancel()

        controller.cancel_binary_fit = _wrapped_cancel  # type: ignore[method-assign]
        dialog.close()
        self._app.processEvents()

        snapshot = controller.binary_fit_status_snapshot()
        self.assertEqual(calls, 1)
        self.assertFalse(snapshot.running)
        self.assertEqual(snapshot.overall_status, "CANCELLED")
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

    def test_report_dialog_close_after_completion_does_not_cancel(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        dialog = BinaryFitReportDialog(controller)

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()

        calls = 0
        original_cancel = controller.cancel_binary_fit

        def _wrapped_cancel() -> bool:
            nonlocal calls
            calls += 1
            return original_cancel()

        controller.cancel_binary_fit = _wrapped_cancel  # type: ignore[method-assign]
        dialog.close()
        self._app.processEvents()

        snapshot = controller.binary_fit_status_snapshot()
        self.assertEqual(calls, 0)
        self.assertFalse(snapshot.running)
        self.assertEqual(snapshot.overall_status, "COMPLETED")
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)

    def test_page_clears_report_dialog_reference_after_close_and_reopen(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)

        self.assertEqual(page._open_binary_fit_dialog(), "Opened Binary Firmware Integration Test configuration dialog.")
        config = page._binary_fit_config_dialog
        assert config is not None
        config._deselect_all()
        checkbox_host = config.case_table.cellWidget(0, 0)
        assert checkbox_host is not None
        checkbox = checkbox_host.findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        config.run_button.click()
        self._app.processEvents()

        first_report = page._binary_fit_report_dialog
        assert first_report is not None
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()
        first_report.close()
        self._app.processEvents()

        self.assertIsNone(page._binary_fit_report_dialog)
        self.assertEqual(page._open_binary_fit_dialog(), "Opened Binary Firmware Integration Test configuration dialog.")

    def test_snapshot_is_read_only_and_dialogs_do_not_import_core_internals_or_protocol(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        snapshot = controller.binary_fit_status_snapshot()
        self.assertTrue(dataclasses.is_dataclass(snapshot))
        self.assertIsInstance(snapshot.results, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.running = True  # type: ignore[misc]

        config_source = inspect.getsource(binary_fit_config_dialog_module)
        report_source = inspect.getsource(binary_fit_report_dialog_module)
        for source in (config_source, report_source):
            self.assertNotIn("_BinaryFitWorkflow", source)
            self.assertNotIn("_active_operation", source)
            self.assertNotIn("binary_cmd_builders", source)
            self.assertNotIn("binary_cmd_parser", source)
            self.assertNotIn("send_command_bytes", source)
            self.assertNotIn("backend_client", source)
            self.assertNotIn("packet_received", source)
        self.assertNotIn("Export", config_source)
        self.assertNotIn("save_location", report_source)


if __name__ == "__main__":
    unittest.main()
