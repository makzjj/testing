from __future__ import annotations

import dataclasses
import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit

from data.text_cmd_builders import build_text_command_payload
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs import ManualTextCommandDialog, TextFitConfigDialog
from gui.workspace.models import FirmwareTestResult


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Backend:
    def __init__(self) -> None:
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return True

    def write(self, payload: bytearray) -> None:
        self.writes.append(payload)


class _Runtime(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.backend_client = _Backend()


class _Bridge:
    def __init__(self) -> None:
        self.runtime = _Runtime()

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return True, True

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self.runtime

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self.runtime.backend_client.write(payload)
        return payload


def _case_for(controller: FirmwareIntegrationController, command_text: str):
    definitions = {definition.name: definition for definition in controller.manual_text_command_definitions()}
    for case in controller.text_fit_case_definitions():
        definition = definitions[case.command_key]
        if definition.text_command == command_text:
            return case
    raise AssertionError(f"Missing case for {command_text}")


class FirmwareTextFitFullCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_manual_text_dialog_exposes_complete_catalog(self) -> None:
        controller = FirmwareIntegrationController(_Bridge())
        dialog = ManualTextCommandDialog(controller)

        self.assertEqual(dialog.command_combo.count(), 70)
        commands = [
            controller.manual_text_command_definitions()[index].text_command
            for index in range(len(controller.manual_text_command_definitions()))
        ]
        self.assertIn("reset!", commands)
        self.assertIn("logPC=", commands)

        reset_index = commands.index("reset!")
        dialog.command_combo.setCurrentIndex(reset_index)
        self._app.processEvents()
        self.assertFalse(dialog.value_input.isEnabled())

        onrb_index = commands.index("onRB=")
        dialog.command_combo.setCurrentIndex(onrb_index)
        self._app.processEvents()
        self.assertTrue(dialog.value_input.isEnabled())
        self.assertEqual(dialog.value_input.text(), "1")

    def test_text_fit_config_selects_all_and_emits_editable_case_values(self) -> None:
        controller = FirmwareIntegrationController(_Bridge())
        dialog = TextFitConfigDialog(controller)
        emitted: list[object] = []
        dialog.run_requested.connect(emitted.append)

        self.assertEqual(dialog.case_table.rowCount(), 70)
        dialog._select_all()
        self.assertEqual(len(dialog.selected_case_ids()), 70)

        opmode_case = _case_for(controller, "opmode=")
        row = next(row for row in range(dialog.case_table.rowCount()) if dialog.case_table.item(row, 1).data(0x0100) == opmode_case.case_id)
        value_widget = dialog.case_table.cellWidget(row, 2)
        self.assertIsInstance(value_widget, QLineEdit)
        assert isinstance(value_widget, QLineEdit)
        value_widget.setText("3")
        dialog.run_button.click()
        self._app.processEvents()

        selected_cases = emitted[-1]
        edited = next(case for case in selected_cases if case.case_id == opmode_case.case_id)
        self.assertEqual(edited.parameter_value, "3")

    def test_setter_case_uses_edited_value_and_prefix_response(self) -> None:
        bridge = _Bridge()
        controller = FirmwareIntegrationController(bridge)
        case = dataclasses.replace(_case_for(controller, "opmode="), parameter_value="3")
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_text_fit(cases=[case]))
        self.assertEqual(list(bridge.runtime.backend_client.writes[0]), list(build_text_command_payload("opmode=", "3")))
        bridge.runtime.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"opmode:3\r\n")})

        self.assertEqual(results[-1].status, "PASS")
        self.assertEqual(results[-1].command_display, "opmode=3")
        self.assertEqual(results[-1].actual, "opmode:3")

    def test_invalid_case_value_records_error_and_sends_nothing(self) -> None:
        bridge = _Bridge()
        controller = FirmwareIntegrationController(bridge)
        case = dataclasses.replace(_case_for(controller, "onRB="), parameter_value="2")
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.text_fit_case_result.connect(results.append)
        controller.text_fit_completed.connect(completed.append)

        self.assertTrue(controller.start_text_fit(cases=[case]))

        self.assertEqual(bridge.runtime.backend_client.writes, [])
        self.assertEqual(results[-1].status, "ERROR")
        self.assertIn("accepts only", results[-1].message or "")
        self.assertEqual(completed[-1]["status"], "COMPLETED")

    def test_unsupported_reboot_case_produces_result_without_sending(self) -> None:
        bridge = _Bridge()
        controller = FirmwareIntegrationController(bridge)
        case = _case_for(controller, "reset!")
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_text_fit(cases=[case]))

        self.assertEqual(bridge.runtime.backend_client.writes, [])
        self.assertEqual(results[-1].status, "UNSUPPORTED")
        self.assertIn("recovery validation", results[-1].message or "")

    def test_logging_policy_sends_cleanup_stop_value_before_result(self) -> None:
        bridge = _Bridge()
        controller = FirmwareIntegrationController(bridge)
        case = dataclasses.replace(_case_for(controller, "logPC="), parameter_value="1000")
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_text_fit(cases=[case]))
        self.assertEqual(list(bridge.runtime.backend_client.writes[0]), list(build_text_command_payload("logPC=", "1000")))
        bridge.runtime.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"logPC:1000\r\n")})
        self.assertEqual(len(bridge.runtime.backend_client.writes), 2)
        self.assertEqual(list(bridge.runtime.backend_client.writes[1]), list(build_text_command_payload("logPC=", "0")))
        self.assertEqual(results, [])

        bridge.runtime.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"logPC:0\r\n")})
        self.assertEqual(results[-1].status, "PASS")
        self.assertIn("cleanup", results[-1].message or "")

    def test_select_all_checkbox_helper_still_reaches_every_case(self) -> None:
        controller = FirmwareIntegrationController(_Bridge())
        dialog = TextFitConfigDialog(controller)
        dialog._select_all()

        checked = 0
        for row in range(dialog.case_table.rowCount()):
            host = dialog.case_table.cellWidget(row, 0)
            assert host is not None
            checkbox = host.findChild(QCheckBox)
            assert checkbox is not None
            checked += int(checkbox.isChecked())
        self.assertEqual(checked, 70)


if __name__ == "__main__":
    unittest.main()
