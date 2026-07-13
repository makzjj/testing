from __future__ import annotations

import dataclasses
import inspect
import os
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import gui.workspace.controllers.firmware_integration_controller as firmware_controller_module
import services.firmware_transport_adapter as firmware_transport_adapter_module
from data.text_cmd_builders import build_text_command_payload
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.models import FirmwareTextFitSnapshot, FirmwareTestCase, FirmwareTestResult


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True, fail_on_write_numbers: set[int] | None = None) -> None:
        self.connected = connected
        self.fail_on_write_numbers = set(fail_on_write_numbers or set())
        self.write_count = 0
        self.writes: list[bytearray] = []
        self.sent_commands: list[tuple[int, list[int]]] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.write_count += 1
        if self.write_count in self.fail_on_write_numbers:
            raise RuntimeError(f"Injected text send failure #{self.write_count}")
        self.writes.append(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True, fail_on_write_numbers: set[int] | None = None) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(
            connected=connected,
            fail_on_write_numbers=fail_on_write_numbers,
        )


class _FakeBridge:
    def __init__(self, *, connected: bool = True, fail_on_write_numbers: set[int] | None = None) -> None:
        self._runtime_window = _FakeRuntimeWindow(
            connected=connected,
            fail_on_write_numbers=fail_on_write_numbers,
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


class FirmwareTextFitCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_text_fit_catalog_exists_and_uses_small_query_subset(self) -> None:
        controller = FirmwareIntegrationController()
        cases = controller.text_fit_case_definitions()
        definitions = {definition.name: definition for definition in controller.manual_text_command_definitions()}

        self.assertEqual(
            [case.name for case in cases],
            [
                "Version Query",
                "UART Status Query",
                "Operating Mode Query",
                "Robot Power Query",
            ],
        )
        for case in cases:
            self.assertEqual(case.mode, "text")
            self.assertTrue(case.selected_by_default)
            self.assertIsNone(case.parameter_value)
            self.assertIn(case.command_key, definitions)
        self.assertNotIn("Robot Power Set", [case.name for case in cases])

    def test_text_fit_snapshot_is_immutable_and_read_only(self) -> None:
        controller = FirmwareIntegrationController()
        snapshot = controller.text_fit_status_snapshot()

        self.assertTrue(dataclasses.is_dataclass(snapshot))
        self.assertIsInstance(snapshot, FirmwareTextFitSnapshot)
        self.assertIsInstance(snapshot.results, tuple)
        with self.assertRaises(FrozenInstanceError):
            snapshot.running = True  # type: ignore[misc]

    def test_start_rejects_empty_unknown_and_busy_states(self) -> None:
        controller = FirmwareIntegrationController(_FakeBridge())

        self.assertFalse(controller.start_text_fit(selected_case_ids=[]))
        self.assertFalse(controller.start_text_fit(selected_case_ids=["missing-case-id"]))

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertFalse(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        controller.cancel_active_operation()

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertFalse(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        controller.cancel_active_operation()

        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        self.assertFalse(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))

    def test_text_fit_sequences_cases_and_produces_results_in_order(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        started: list[dict[str, object]] = []
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.text_fit_case_started.connect(started.append)
        controller.text_fit_case_result.connect(results.append)
        controller.text_fit_completed.connect(completed.append)

        runtime_window = bridge.get_runtime_window(create_if_missing=False)
        baseline = runtime_window.receivers(runtime_window.packet_received)
        self.assertTrue(
            controller.start_text_fit(
                selected_case_ids=[
                    "text-fit-version-query",
                    "text-fit-uart-status-query",
                ]
            )
        )

        self.assertEqual(controller.pending_request_mode(), "text_fit")
        self.assertTrue(controller._transport_adapter.is_attached)
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0]["case_id"], "text-fit-version-query")
        self.assertEqual(list(bridge._runtime_window.backend_client.writes[0]), list(build_text_command_payload("ver?")))

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3F]})
        self.assertEqual(results, [])
        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"uartstat:ok\r\n")})
        self.assertEqual(results, [])

        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].case_id, "text-fit-version-query")
        self.assertEqual(results[0].status, "PASS")
        self.assertEqual(len(started), 2)
        self.assertEqual(started[1]["case_id"], "text-fit-uart-status-query")

        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:stale\r\n")})
        self.assertEqual(len(results), 1)
        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"uartstat:ok\r\n")})
        self.assertEqual([result.case_id for result in results], ["text-fit-version-query", "text-fit-uart-status-query"])
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

    def test_timeout_creates_result_and_continues_with_timer_reset(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.text_fit_case_result.connect(results.append)
        controller.text_fit_completed.connect(completed.append)

        self.assertTrue(
            controller.start_text_fit(
                selected_case_ids=["text-fit-version-query", "text-fit-uart-status-query"]
            )
        )
        self.assertTrue(controller._timeout_timer.isActive())
        controller.handle_timeout()
        self.assertEqual(results[0].status, "TIMEOUT")
        self.assertTrue(controller._timeout_timer.isActive())
        self.assertEqual(list(bridge._runtime_window.backend_client.writes[-1]), list(build_text_command_payload("uartstat?")))

        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"uartstat:ok\r\n")})
        self.assertEqual([result.status for result in results], ["TIMEOUT", "PASS"])
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)
        self.assertFalse(controller.has_pending_firmware_request())

    def test_send_failure_creates_error_result_and_continues(self) -> None:
        bridge = _FakeBridge(fail_on_write_numbers={1})
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        completed: list[dict[str, object]] = []
        controller.text_fit_case_result.connect(results.append)
        controller.text_fit_completed.connect(completed.append)

        self.assertTrue(
            controller.start_text_fit(
                selected_case_ids=["text-fit-version-query", "text-fit-uart-status-query"]
            )
        )
        self.assertEqual(results[0].status, "ERROR")
        self.assertIn("Injected text send failure", results[0].message or "")
        self.assertEqual(bridge._runtime_window.backend_client.write_count, 2)

        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"uartstat:ok\r\n")})
        self.assertEqual([result.status for result in results], ["ERROR", "PASS"])
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller._timeout_timer.isActive())
        self.assertFalse(controller._transport_adapter.is_attached)
        self.assertFalse(controller.has_pending_firmware_request())

    def test_manual_verification_pauses_until_submission(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.text_fit_case_definitions()[0],
            case_id="text-fit-version-query-manual",
            manual_verification=True,
            manual_prompt="Verify version text manually.",
        )
        results: list[FirmwareTestResult] = []
        requests: list[dict[str, object]] = []
        completed: list[dict[str, object]] = []
        controller.text_fit_case_result.connect(results.append)
        controller.text_fit_manual_verification_requested.connect(requests.append)
        controller.text_fit_completed.connect(completed.append)

        self.assertTrue(controller.start_text_fit(cases=[manual_case]))
        bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})

        self.assertEqual(results, [])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["case_id"], manual_case.case_id)
        self.assertEqual(controller.pending_request_mode(), "text_fit")
        self.assertTrue(controller.has_pending_firmware_request())

        self.assertTrue(controller.submit_text_fit_manual_verification(False, "Display mismatch."))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "FAIL")
        self.assertEqual(results[0].manual_verification_outcome, "failed")
        self.assertEqual(completed[-1]["status"], "COMPLETED")
        self.assertFalse(controller.has_pending_firmware_request())

    def test_cancellation_works_waiting_awaiting_verification_and_repeated_cancel_is_safe(self) -> None:
        waiting_controller = FirmwareIntegrationController(_FakeBridge())
        waiting_results: list[FirmwareTestResult] = []
        waiting_completed: list[dict[str, object]] = []
        waiting_controller.text_fit_case_result.connect(waiting_results.append)
        waiting_controller.text_fit_completed.connect(waiting_completed.append)

        self.assertTrue(waiting_controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        self.assertTrue(waiting_controller.cancel_text_fit())
        self.assertEqual(waiting_results[-1].status, "CANCELLED")
        self.assertEqual(waiting_completed[-1]["status"], "CANCELLED")
        self.assertFalse(waiting_controller._timeout_timer.isActive())
        self.assertFalse(waiting_controller._transport_adapter.is_attached)
        self.assertFalse(waiting_controller.has_pending_firmware_request())
        self.assertFalse(waiting_controller.cancel_text_fit())

        second_bridge = _FakeBridge()
        second_controller = FirmwareIntegrationController(second_bridge)
        manual_case = dataclasses.replace(
            second_controller.text_fit_case_definitions()[0],
            case_id="text-fit-version-query-awaiting",
            manual_verification=True,
            manual_prompt="Verify manually.",
        )
        verification_results: list[FirmwareTestResult] = []
        verification_completed: list[dict[str, object]] = []
        second_controller.text_fit_case_result.connect(verification_results.append)
        second_controller.text_fit_completed.connect(verification_completed.append)
        self.assertTrue(second_controller.start_text_fit(cases=[manual_case]))
        second_bridge._runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self.assertTrue(second_controller.cancel_text_fit())
        self.assertEqual(verification_results[-1].status, "CANCELLED")
        self.assertEqual(verification_completed[-1]["status"], "CANCELLED")
        self.assertFalse(second_controller._timeout_timer.isActive())
        self.assertFalse(second_controller._transport_adapter.is_attached)
        self.assertFalse(second_controller.has_pending_firmware_request())

    def test_architecture_remains_private_and_ui_free(self) -> None:
        workflow_source = inspect.getsource(firmware_controller_module._TextFitWorkflow)
        adapter_source = inspect.getsource(firmware_transport_adapter_module.FirmwareTransportAdapter)

        self.assertNotIn("backend_client", workflow_source)
        self.assertNotIn("packet_received", workflow_source)
        self.assertNotIn("QWidget", workflow_source)
        self.assertNotIn("expected_prefix", adapter_source)
        self.assertNotIn("startswith", adapter_source)
        self.assertIn("FirmwareIntegrationController", {
            name
            for name, value in vars(firmware_controller_module).items()
            if inspect.isclass(value) and value.__module__ == firmware_controller_module.__name__
        })
        self.assertNotIn("TextFITController", inspect.getsource(firmware_controller_module))
        self.assertNotIn("legacy_reference.firmware_integration_test", sys.modules)


if __name__ == "__main__":
    unittest.main()
