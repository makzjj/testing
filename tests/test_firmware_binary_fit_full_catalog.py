from __future__ import annotations

import os
import unittest
from dataclasses import replace

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QLineEdit

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs.binary_fit_config_dialog import BinaryFitConfigDialog


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self) -> None:
        self.connected = True
        self.sent_commands: list[tuple[int, list[int]]] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient()


class _FakeBridge:
    def __init__(self) -> None:
        self._runtime_window = _FakeRuntimeWindow()
        self.raw_config = {"robot": {"axes": {"x": {"node_id": 3}}}}

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return [(3, "X")]

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return True, True

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def get_frame_loss_items(self) -> list[object]:
        return []


class FirmwareBinaryFitFullCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_manual_binary_and_fit_config_show_complete_catalog(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = BinaryFitConfigDialog(controller)

        self.assertEqual(len(controller.manual_binary_command_definitions()), 83)
        self.assertEqual(dialog.case_table.rowCount(), 83)
        self.assertEqual(dialog.case_table.columnCount(), 5)

        dialog._select_all()
        self.assertEqual(len(dialog.selected_cases()), 83)
        dialog._deselect_all()
        self.assertEqual(dialog.selected_cases(), [])
        dialog._reset_defaults()
        self.assertEqual(
            [case.case_id for case in dialog.selected_cases()],
            [case.case_id for case in controller.binary_fit_case_definitions() if case.selected_by_default],
        )

    def test_binary_fit_defaults_match_requested_opcode_forms_and_reset_restores_nodetype_value(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        dialog = BinaryFitConfigDialog(controller)
        definitions = {definition.name: definition for definition in controller.manual_binary_command_definitions()}
        by_case_id = {case.case_id: case for case in controller.binary_fit_case_definitions()}

        expected_defaults = {
            (0x82, "query"),
            (0x83, "query"),
            (0x85, "query"),
            (0x97, "action"),
            (0x9D, "action"),
            (0xA0, "action"),
            (0xC5, "action"),
            (0xC8, "query"),
            (0xCB, "raw"),
            (0xCD, "query"),
            (0xCD, "set"),
            (0xCE, "query"),
            (0xD8, "query"),
            (0xDB, "action"),
            (0xDC, "action"),
            (0xDD, "action"),
            (0xDE, "query"),
        }

        selected_defaults = {
            (int(definitions[case.command_key].opcode or 0), str(definitions[case.command_key].command_form or ""))
            for case in controller.binary_fit_case_definitions()
            if case.selected_by_default
        }
        self.assertEqual(selected_defaults, expected_defaults)

        nodetype_query = next(case for case in controller.binary_fit_case_definitions() if case.command_key == "NODETYPE - Get node type")
        nodetype_set = next(case for case in controller.binary_fit_case_definitions() if case.command_key == "NODETYPE - Set node type")
        self.assertTrue(nodetype_query.selected_by_default)
        self.assertTrue(nodetype_set.selected_by_default)
        self.assertIsNone(nodetype_query.parameter_value)
        self.assertEqual(nodetype_set.parameter_value, "09")

        nodetype_set_row = next(
            row for row in range(dialog.case_table.rowCount()) if dialog.case_table.item(row, 1).data(0x0100) == nodetype_set.case_id
        )
        nodetype_set_input = dialog.case_table.cellWidget(nodetype_set_row, 3)
        assert isinstance(nodetype_set_input, QLineEdit)
        nodetype_set_input.setText("7")
        dialog._deselect_all()
        dialog._reset_defaults()
        self.assertEqual(nodetype_set_input.text(), "09")
        self.assertEqual(
            [case.case_id for case in dialog.selected_cases()],
            [case.case_id for case in controller.binary_fit_case_definitions() if case.selected_by_default],
        )

    def test_config_dialog_emits_edited_case_values_and_sends_nothing(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = BinaryFitConfigDialog(controller)
        dialog._deselect_all()

        target_row = next(
            row
            for row in range(dialog.case_table.rowCount())
            if dialog.case_table.item(row, 1).data(0x0100) == "binary-fit-nodeidref-set-id-reference-86-set"
        )
        checkbox = dialog.case_table.cellWidget(target_row, 0).findChild(QCheckBox)
        assert checkbox is not None
        checkbox.setChecked(True)
        value_input = dialog.case_table.cellWidget(target_row, 3)
        self.assertIsInstance(value_input, QLineEdit)
        assert isinstance(value_input, QLineEdit)
        value_input.setText("02")

        emitted: list[tuple[int, object]] = []
        dialog.run_requested.connect(lambda node_id, cases: emitted.append((node_id, cases)))
        dialog.run_button.click()
        self._app.processEvents()

        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertEqual(len(emitted), 1)
        selected = list(emitted[0][1])
        self.assertEqual(selected[0].parameter_value, "02")

    def test_no_response_binary_case_sends_and_completes(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        no_response_case = next(
            case for case in controller.binary_fit_case_definitions() if case.execution_policy == "NO_RESPONSE"
        )
        results = []
        completed = []
        controller.binary_fit_case_result.connect(results.append)
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[no_response_case]))

        self.assertEqual(bridge._runtime_window.backend_client.sent_commands[-1][0], 3)
        self.assertEqual(results[-1].status, "PASS")
        self.assertEqual(results[-1].execution_capability, "NO_RESPONSE")
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller.has_pending_firmware_request())

    def test_logging_policy_sends_cleanup_stop_value_before_result(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        logging_case = next(
            case for case in controller.binary_fit_case_definitions() if case.command_key.startswith("LOGMOTOR_I")
        )
        results = []
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[logging_case]))
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands[-1], (3, [0xD3, 0x3D, 0x03, 0xE8]))

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xD3, "params": [0x3A, 0x03, 0xE8]}
        )
        self.assertEqual(results, [])
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands[-1], (3, [0xD3, 0x3D, 0x00, 0x00]))

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xD3, "params": [0x3A, 0x00, 0x00]}
        )
        self.assertEqual(results[-1].status, "PASS")
        self.assertIn("Cleanup command completed", results[-1].message or "")
        self.assertFalse(controller.has_pending_firmware_request())

    def test_edited_binary_value_validation_failure_sends_nothing(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        nodeid_case = next(
            case for case in controller.binary_fit_case_definitions() if case.case_id == "binary-fit-nodeidref-set-id-reference-86-set"
        )
        bad_case = replace(nodeid_case, parameter_value="01 02")
        results = []
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[bad_case]))

        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertEqual(results[-1].status, "ERROR")
        self.assertIn("Expected 1 byte", results[-1].message or "")


if __name__ == "__main__":
    unittest.main()
