from __future__ import annotations

import dataclasses
import inspect
import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import gui.workspace.controllers.firmware_integration_controller as firmware_controller_module
import services.firmware_transport_adapter as firmware_transport_adapter_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.models import FirmwareTestCase, FirmwareTestResult


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True, fail_on_send_numbers: set[int] | None = None) -> None:
        self.connected = connected
        self.fail_on_send_numbers = set(fail_on_send_numbers or set())
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.send_count = 0
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.send_count += 1
        if self.send_count in self.fail_on_send_numbers:
            raise RuntimeError(f"Injected send failure #{self.send_count}")
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.writes.append(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True, fail_on_send_numbers: set[int] | None = None) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(
            connected=connected,
            fail_on_send_numbers=fail_on_send_numbers,
        )


class _FakeBridge:
    def __init__(self, *, connected: bool = True, fail_on_send_numbers: set[int] | None = None) -> None:
        self._runtime_window = _FakeRuntimeWindow(
            connected=connected,
            fail_on_send_numbers=fail_on_send_numbers,
        )

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class FirmwareBinaryFitCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_binary_fit_catalog_exists_and_uses_small_proven_subset(self) -> None:
        controller = FirmwareIntegrationController()
        cases = controller.binary_fit_case_definitions()

        self.assertEqual(
            [case.name for case in cases],
            ["GETVER", "GETPOS", "GETVEL", "NODECONFIG Query", "INTERRUPT Query", "MOTOR_I Query"],
        )
        for case in cases:
            self.assertEqual(case.mode, "binary")
            self.assertTrue(case.selected_by_default)

    def test_binary_fit_sequences_cases_one_at_a_time_and_produces_results(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        started: list[dict[str, object]] = []
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.binary_fit_case_started.connect(started.append)
        controller.binary_fit_case_result.connect(results.append)
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(
            controller.start_binary_fit(
                node_id=3,
                selected_case_ids=[
                    "binary-fit-getver",
                    "binary-fit-getpos",
                ],
            )
        )
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["case_id"], "binary-fit-getver")
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [(3, [0xC8, 0x3F])])

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        self.assertEqual(results, [])

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 12, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertEqual(results, [])

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "PASS")
        self.assertEqual(results[0].case_id, "binary-fit-getver")
        self.assertEqual(len(started), 2)
        self.assertEqual(started[1]["case_id"], "binary-fit-getpos")
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands[-1], (3, [0x82]))

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]}
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(isinstance(result, FirmwareTestResult) for result in results))
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertEqual(len(completed[-1]["results"]), 2)
        self.assertFalse(controller.has_pending_firmware_request())

    def test_timeout_creates_result_and_continues(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.binary_fit_case_result.connect(results.append)
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(
            controller.start_binary_fit(
                node_id=3,
                selected_case_ids=["binary-fit-getver", "binary-fit-getpos"],
            )
        )
        controller.handle_timeout()
        self.assertEqual(results[0].status, "TIMEOUT")
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands[-1], (3, [0x82]))

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]}
        )
        self.assertEqual([result.status for result in results], ["TIMEOUT", "PASS"])
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)
        self.assertFalse(controller.has_pending_firmware_request())

    def test_send_failure_creates_error_result_and_continues(self) -> None:
        bridge = _FakeBridge(fail_on_send_numbers={1})
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.binary_fit_case_result.connect(results.append)
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(
            controller.start_binary_fit(
                node_id=3,
                selected_case_ids=["binary-fit-getver", "binary-fit-getpos"],
            )
        )
        self.assertEqual(results[0].status, "ERROR")
        self.assertIn("Injected send failure", results[0].message or "")
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [(3, [0x82])])

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]}
        )
        self.assertEqual([result.status for result in results], ["ERROR", "PASS"])
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)
        self.assertFalse(controller.has_pending_firmware_request())

    def test_manual_verification_pauses_until_submission(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        catalog_case = controller.binary_fit_case_definitions()[0]
        manual_case = dataclasses.replace(
            catalog_case,
            case_id="binary-fit-getver-manual",
            manual_verification=True,
            manual_prompt="Verify firmware label manually.",
        )
        results: list[FirmwareTestResult] = []
        verification_requests: list[dict[str, object]] = []
        completed: list[dict[str, object]] = []
        controller.binary_fit_case_result.connect(results.append)
        controller.binary_fit_manual_verification_requested.connect(verification_requests.append)
        controller.binary_fit_completed.connect(completed.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[manual_case]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )

        self.assertEqual(results, [])
        self.assertEqual(len(verification_requests), 1)
        self.assertEqual(verification_requests[0]["case_id"], manual_case.case_id)
        self.assertEqual(controller.pending_request_mode(), "binary_fit")
        self.assertTrue(controller.has_pending_firmware_request())

        self.assertTrue(controller.submit_binary_fit_manual_verification(True, "Observed expected firmware string."))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "PASS")
        self.assertEqual(results[0].manual_verification_outcome, "passed")
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller.has_pending_firmware_request())

    def test_cancellation_works_while_waiting_and_while_awaiting_verification(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        waiting_results: list[FirmwareTestResult] = []
        waiting_completed: list[dict[str, object]] = []
        controller.binary_fit_case_result.connect(waiting_results.append)
        controller.binary_fit_completed.connect(waiting_completed.append)

        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        self.assertTrue(controller.cancel_binary_fit())
        self.assertEqual(waiting_results[-1].status, "CANCELLED")
        self.assertEqual(waiting_completed[-1]["status"], "CANCELLED")
        self.assertFalse(controller.has_pending_firmware_request())

        manual_case = dataclasses.replace(
            controller.binary_fit_case_definitions()[0],
            case_id="binary-fit-getver-awaiting",
            manual_verification=True,
            manual_prompt="Verify manually.",
        )
        verification_results: list[FirmwareTestResult] = []
        verification_completed: list[dict[str, object]] = []
        second_controller = FirmwareIntegrationController(_FakeBridge())
        second_controller.binary_fit_case_result.connect(verification_results.append)
        second_controller.binary_fit_completed.connect(verification_completed.append)

        self.assertTrue(second_controller.start_binary_fit(node_id=3, cases=[manual_case]))
        second_controller._bridge._runtime_window.packet_received.emit(  # type: ignore[union-attr]
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertTrue(second_controller.cancel_binary_fit())
        self.assertEqual(verification_results[-1].status, "CANCELLED")
        self.assertEqual(verification_completed[-1]["status"], "CANCELLED")
        self.assertFalse(second_controller.has_pending_firmware_request())

    def test_workflow_and_adapter_remain_isolated(self) -> None:
        workflow_source = inspect.getsource(firmware_controller_module._BinaryFitWorkflow)
        adapter_source = inspect.getsource(firmware_transport_adapter_module.FirmwareTransportAdapter)

        self.assertNotIn("backend_client", workflow_source)
        self.assertNotIn("packet_received", workflow_source)
        self.assertNotIn("QWidget", workflow_source)
        self.assertNotIn("current_index", adapter_source)
        self.assertNotIn("manual_prompt", adapter_source)
        self.assertNotIn("FirmwareTestResult", adapter_source)

    def test_controller_remains_single_public_owner(self) -> None:
        class_names = {
            name
            for name, value in vars(firmware_controller_module).items()
            if inspect.isclass(value) and value.__module__ == firmware_controller_module.__name__
        }
        self.assertIn("FirmwareIntegrationController", class_names)
        self.assertNotIn("BinaryFITController", class_names)
        self.assertNotIn("ManualBinaryController", class_names)
        self.assertNotIn("ManualTextController", class_names)


if __name__ == "__main__":
    unittest.main()
