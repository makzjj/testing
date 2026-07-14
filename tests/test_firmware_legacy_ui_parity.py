from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QPushButton, QTableWidget

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs.binary_fit_config_dialog import BinaryFitConfigDialog
from gui.workspace.dialogs.binary_fit_report_dialog import BinaryFitReportDialog
from gui.workspace.dialogs.manual_binary_command_dialog import ManualBinaryCommandDialog
from gui.workspace.dialogs.manual_text_command_dialog import ManualTextCommandDialog
from gui.workspace.dialogs.text_fit_config_dialog import TextFitConfigDialog
from gui.workspace.dialogs.text_fit_report_dialog import TextFitReportDialog
from gui.workspace.sections.firmware.firmware_sections import FirmwareIntegrationSection


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)


class _FakeBridge:
    raw_config = {"robot": {"axes": {"x": {"node_id": 3}}}}

    def __init__(self) -> None:
        self._runtime_window = _FakeRuntimeWindow()
        self.sent: list[tuple[int, list[int]]] = []

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        return True, True

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def send_firmware_text_command(self, frame: bytearray) -> bytearray:
        return bytearray(frame)

    def get_manual_binary_node_options(self, *, create_if_missing: bool = False):
        return [(3, "X")]

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        return [(3, "X")]

    def get_frame_loss_items(self):
        return []


def _headers(table: QTableWidget) -> list[str]:
    return [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())]


class FirmwareLegacyUiParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_main_module_uses_legacy_action_row_and_manual_stack(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        section = FirmwareIntegrationSection(
            controller,
            open_manual_binary_dialog=lambda: "binary",
            open_manual_text_dialog=lambda: "text",
            open_binary_fit_dialog=lambda: "binary fit",
            open_text_fit_dialog=lambda: "text fit",
            open_reports_dialog=lambda: "reports",
        )
        buttons = [button.text() for button in section.findChildren(QPushButton)]
        self.assertIn("Run Binary Tests", buttons)
        self.assertIn("Run Text-based Tests", buttons)
        self.assertIn("Save Location", buttons)
        self.assertIn("Send Text", buttons)
        self.assertIn("Send Binary", buttons)
        combo = section.findChild(QComboBox, "FirmwareFitManualModeCombo")
        self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Text Command Mode", "Binary Command Mode"])
        self.assertIsNotNone(section.findChild(QCheckBox, "FirmwareFitDiagnosticModeCheck"))

    def test_binary_config_dialog_matches_legacy_columns_and_buttons(self) -> None:
        dialog = BinaryFitConfigDialog(FirmwareIntegrationController(_FakeBridge()))
        self.assertEqual(dialog.windowTitle(), "Binary Command Suite Configuration")
        self.assertEqual(_headers(dialog.case_table), ["Test?", "Hex Code", "Command Name", "Parameters (Hex bytes)", "Param Type"])
        self.assertEqual([dialog.select_all_button.text(), dialog.deselect_all_button.text(), dialog.reset_defaults_button.text()], ["Select All", "Deselect All", "Reset Defaults"])
        self.assertEqual([dialog.node_combo.itemText(i) for i in range(dialog.node_combo.count())], [str(i) for i in range(2, 18)])
        self.assertEqual(dialog.node_combo.currentText(), "3")
        self.assertEqual(dialog.run_button.text(), "Start Test Run")
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        self.assertEqual(dialog.case_table.rowCount(), len(dialog._controller.binary_fit_case_definitions()))

    def test_text_config_dialog_matches_legacy_columns_and_buttons(self) -> None:
        dialog = TextFitConfigDialog(FirmwareIntegrationController(_FakeBridge()))
        self.assertEqual(dialog.windowTitle(), "Text Command Suite Configuration")
        self.assertEqual(_headers(dialog.case_table), ["Test?", "Command Format", "Value/Param", "Type"])
        self.assertEqual([dialog.select_all_button.text(), dialog.deselect_all_button.text(), dialog.reset_defaults_button.text()], ["Select All", "Deselect All", "Reset Defaults"])
        self.assertEqual(dialog.run_button.text(), "Start Test Run")
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        self.assertEqual(dialog.case_table.rowCount(), len(dialog._controller.text_fit_case_definitions()))

    def test_report_dialogs_match_legacy_result_table_and_controls(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        binary = BinaryFitReportDialog(controller)
        text = TextFitReportDialog(controller)
        expected_headers = ["Command/Feature", "Expected Response", "Actual Response", "TX (Hex)", "RX (Hex)", "Latency (ms)", "Test Status"]
        self.assertEqual(binary.windowTitle(), "Automated Binary Integration Test")
        self.assertEqual(text.windowTitle(), "Automated Text Integration Test")
        self.assertEqual(_headers(binary.results_table), expected_headers)
        self.assertEqual(_headers(text.results_table), expected_headers)
        self.assertEqual(binary.export_button.text(), "Export Report")
        self.assertEqual(text.export_button.text(), "Export Report")
        self.assertEqual(binary.close_button.text(), "Close")
        self.assertEqual(text.close_button.text(), "Close")

    def test_manual_dialog_fields_match_legacy_labels(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        text = ManualTextCommandDialog(controller)
        binary = ManualBinaryCommandDialog(controller)
        self.assertTrue(text.command_combo.isEditable())
        self.assertEqual(text.send_button.text(), "Send Text")
        self.assertEqual(binary.send_button.text(), "Send Binary")
        self.assertEqual(binary.raw_hex_toggle.text(), "Raw Hex")

    def test_dialog_architecture_boundaries_remain_clean(self) -> None:
        dialog_paths = [
            Path("gui/workspace/dialogs/binary_fit_config_dialog.py"),
            Path("gui/workspace/dialogs/text_fit_config_dialog.py"),
            Path("gui/workspace/dialogs/binary_fit_report_dialog.py"),
            Path("gui/workspace/dialogs/text_fit_report_dialog.py"),
            Path("gui/workspace/dialogs/manual_binary_command_dialog.py"),
            Path("gui/workspace/dialogs/manual_text_command_dialog.py"),
        ]
        for path in dialog_paths:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("legacy_reference", source)
            self.assertNotIn("binary_cmd_builders", source)
            self.assertNotIn("binary_cmd_parser", source)
            self.assertNotIn("backend_client", source)
            self.assertNotIn("packet_received", source)
        self.assertEqual(len([name for name, obj in inspect.getmembers(__import__("gui.workspace.controllers.firmware_integration_controller", fromlist=["FirmwareIntegrationController"])) if name == "FirmwareIntegrationController"]), 1)


if __name__ == "__main__":
    unittest.main()
