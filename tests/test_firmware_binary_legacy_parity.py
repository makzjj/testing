from __future__ import annotations

import inspect
import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import data.binary_cmd_builders as binary_builders
import data.binary_cmd_parser as binary_parser
import gui.workspace.controllers.firmware_integration_controller as firmware_controller_module
import gui.workspace.dialogs.binary_fit_config_dialog as binary_fit_config_dialog_module
import gui.workspace.dialogs.manual_binary_command_dialog as manual_binary_dialog_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []

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


def _response_params_for(cmd: int) -> list[int]:
    responses = {
        0x81: [0x53, 0x00, 0x00, 0x00, 0x00],
        0x82: [0x3A, 0x00, 0x00, 0x00, 0x00],
        0x84: [0x53, 0x00, 0x1E],
        0x85: [0x3A, 0x00, 0x1E],
        0x88: [0x53, 0x00, 0x1E],
        0xC3: [0x41],
        0xC4: [0x3A, 0x01],
        0xC8: [0x3A, 0x12, 0x30, 0x01],
        0xC9: [0x3A, 0x09],
        0xCA: [0x3A, 0x09],
        0xCD: [0x3A, 0x01],
        0xCF: [0x3A, 0x00, 0x64],
        0xD3: [0x3A, 0x03, 0xE8],
        0xD8: [0x3A, 0x01, 0x01],
        0xE4: [0x3A, 0x00, 0x64],
    }
    return responses.get(int(cmd) & 0xFF, [0x3A, 0x00])


class FirmwareBinaryLegacyParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_full_catalog_has_execution_capability_and_only_contract_unknown_is_non_sending(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())
        cases = controller.binary_fit_case_definitions()

        self.assertEqual(len(cases), 83)
        capabilities = {case.execution_capability for case in cases}
        self.assertIn("RESPONSE_MATCH", capabilities)
        self.assertIn("RESPONSE_DECODE", capabilities)
        self.assertIn("MANUAL_VERIFICATION", capabilities)
        self.assertIn("LOGGING_STREAM", capabilities)
        self.assertIn("NO_RESPONSE", capabilities)
        self.assertIn("REBOOT_RECOVERY", capabilities)
        self.assertFalse([case for case in cases if case.unsupported_reason and case.execution_capability != "CONTRACT_UNKNOWN"])

    def test_response_match_passes_without_semantic_decode(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        case = next(case for case in controller.binary_fit_case_definitions() if case.execution_capability == "RESPONSE_MATCH")
        results = []
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[case]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": int(case.command_key.split("0x")[-1], 16) if "0x" in case.command_key else bridge._runtime_window.backend_client.sent_commands[-1][1][0], "params": [0x3A, 0x00]}
        )

        self.assertEqual(results[-1].status, "PASS")
        self.assertFalse(results[-1].semantic_decode_available)
        self.assertEqual(results[-1].execution_capability, "RESPONSE_MATCH")

    def test_semantic_decoding_is_used_when_available(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        case = next(case for case in controller.binary_fit_case_definitions() if case.case_id == "binary-fit-getver")
        results = []
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[case]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": _response_params_for(0xC8)}
        )

        self.assertEqual(results[-1].status, "PASS")
        self.assertTrue(results[-1].semantic_decode_available)
        self.assertEqual(results[-1].execution_capability, "RESPONSE_DECODE")

    def test_manual_verification_sends_command_and_waits_for_operator(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        case = next(case for case in controller.binary_fit_case_definitions() if case.execution_capability == "MANUAL_VERIFICATION")
        prompts = []
        results = []
        controller.binary_fit_manual_verification_requested.connect(prompts.append)
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[case]))
        self.assertTrue(bridge._runtime_window.backend_client.sent_commands)
        cmd = bridge._runtime_window.backend_client.sent_commands[-1][1][0]
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": cmd, "params": _response_params_for(cmd)}
        )
        self.assertTrue(prompts)
        self.assertTrue(controller.submit_binary_fit_manual_verification(True, "Observed."))
        self.assertEqual(results[-1].manual_verification_outcome, "passed")

    def test_logging_cleanup_runs_after_response(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        case = next(case for case in controller.binary_fit_case_definitions() if case.execution_capability == "LOGGING_STREAM")
        results = []
        controller.binary_fit_case_result.connect(results.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[case]))
        cmd = bridge._runtime_window.backend_client.sent_commands[-1][1][0]
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": cmd, "params": _response_params_for(cmd)}
        )
        self.assertTrue(bridge._runtime_window.backend_client.sent_commands[-1][1][2:])
        self.assertTrue(all(value == 0x00 for value in bridge._runtime_window.backend_client.sent_commands[-1][1][2:]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": cmd, "params": [0x3A, 0x00, 0x00]}
        )
        self.assertEqual(results[-1].cleanup, "completed")

    def test_no_parser_fallback_and_no_ui_packet_building(self) -> None:
        self.assertFalse(hasattr(binary_builders, "build_binary_command_payload"))
        self.assertEqual(binary_parser.decode_command(0x86, [0x3A, 0x03]), (None, None))
        for source in (
            inspect.getsource(binary_fit_config_dialog_module),
            inspect.getsource(manual_binary_dialog_module),
        ):
            self.assertNotIn("binary_cmd_builders", source)
            self.assertNotIn("decode_command", source)
        controller_source = inspect.getsource(firmware_controller_module.FirmwareIntegrationController)
        self.assertNotIn("build_binary_command_payload", controller_source)

    def test_full_select_all_run_produces_result_for_every_case(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        cases = controller.binary_fit_case_definitions()
        completed = []
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=cases))
        for _ in range(300):
            snapshot = controller.binary_fit_status_snapshot()
            if completed:
                break
            if snapshot.awaiting_manual_verification:
                self.assertTrue(controller.submit_binary_fit_manual_verification(True, "Observed."))
                continue
            request = controller._binary_fit_workflow.current_request()
            if request is None:
                self._app.processEvents()
                continue
            cmd = request.expected_opcode
            bridge._runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": cmd, "params": _response_params_for(cmd)}
            )
            self._app.processEvents()

        self.assertTrue(completed)
        self.assertEqual(completed[-1]["completed_count"], len(cases))
        self.assertEqual(len(controller.latest_binary_fit_report().results), len(cases))


if __name__ == "__main__":
    unittest.main()
