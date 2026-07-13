from __future__ import annotations

import dataclasses
import os
import unittest
from dataclasses import FrozenInstanceError

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs import BinaryFitReportDialog, TextFitReportDialog
from gui.workspace.models import FirmwareTestResult


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(
        self,
        *,
        connected: bool = True,
        fail_on_send_numbers: set[int] | None = None,
        fail_on_write_numbers: set[int] | None = None,
    ) -> None:
        self.connected = connected
        self.fail_on_send_numbers = set(fail_on_send_numbers or set())
        self.fail_on_write_numbers = set(fail_on_write_numbers or set())
        self.send_count = 0
        self.write_count = 0
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.send_count += 1
        if self.send_count in self.fail_on_send_numbers:
            raise RuntimeError(f"Injected binary send failure #{self.send_count}")
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.write_count += 1
        if self.write_count in self.fail_on_write_numbers:
            raise RuntimeError(f"Injected text send failure #{self.write_count}")
        self.writes.append(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(
        self,
        *,
        connected: bool = True,
        fail_on_send_numbers: set[int] | None = None,
        fail_on_write_numbers: set[int] | None = None,
    ) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(
            connected=connected,
            fail_on_send_numbers=fail_on_send_numbers,
            fail_on_write_numbers=fail_on_write_numbers,
        )


class _FakeBridge:
    def __init__(
        self,
        *,
        connected: bool = True,
        fail_on_send_numbers: set[int] | None = None,
        fail_on_write_numbers: set[int] | None = None,
    ) -> None:
        self._runtime_window = _FakeRuntimeWindow(
            connected=connected,
            fail_on_send_numbers=fail_on_send_numbers,
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


class FirmwareResultContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in list(self._app.topLevelWidgets()):
            widget.close()
        self._app.processEvents()

    def test_result_model_contains_shared_context_and_remains_data_only(self) -> None:
        result = FirmwareTestResult(
            case_id="binary-fit-getver",
            status="PASS",
            mode="binary",
            case_name="GETVER",
            command_key="GETVER",
            command_display="GETVER (0xC8)",
            target_node_id=3,
        )

        self.assertTrue(dataclasses.is_dataclass(result))
        with self.assertRaises(FrozenInstanceError):
            result.status = "FAIL"  # type: ignore[misc]
        for field in dataclasses.fields(result):
            value = getattr(result, field.name)
            self.assertNotIsInstance(value, QObject)
            self.assertFalse(hasattr(value, "send_command_bytes"))
            self.assertFalse(hasattr(value, "packet_received"))

    def test_binary_fit_result_paths_populate_shared_context(self) -> None:
        pass_result = self._binary_pass_result()
        timeout_result = self._binary_timeout_result()
        error_result = self._binary_send_failure_result()
        cancelled_result = self._binary_cancel_result()
        verification_result = self._binary_manual_verification_result()

        for result in (pass_result, timeout_result, error_result, cancelled_result, verification_result):
            self.assertEqual(result.mode, "binary")
            self.assertEqual(result.case_name, "GETVER")
            self.assertEqual(result.command_key, "GETVER")
            self.assertEqual(result.command_display, "GETVER (0xC8)")
            self.assertEqual(result.target_node_id, 3)

        self.assertEqual(pass_result.status, "PASS")
        self.assertEqual(timeout_result.status, "TIMEOUT")
        self.assertEqual(error_result.status, "ERROR")
        self.assertEqual(cancelled_result.status, "CANCELLED")
        self.assertEqual(verification_result.status, "PASS")
        self.assertEqual(verification_result.manual_verification_outcome, "passed")

    def test_text_fit_result_paths_populate_shared_context(self) -> None:
        pass_result = self._text_pass_result()
        timeout_result = self._text_timeout_result()
        error_result = self._text_send_failure_result()
        cancelled_result = self._text_cancel_result()
        verification_result = self._text_manual_verification_result()

        for result in (pass_result, timeout_result, error_result, cancelled_result, verification_result):
            self.assertEqual(result.mode, "text")
            self.assertEqual(result.case_name, "Version Query")
            self.assertEqual(result.command_key, "Version Query")
            self.assertEqual(result.command_display, "ver?")
            self.assertIsNone(result.target_node_id)

        self.assertEqual(pass_result.status, "PASS")
        self.assertEqual(timeout_result.status, "TIMEOUT")
        self.assertEqual(error_result.status, "ERROR")
        self.assertEqual(cancelled_result.status, "CANCELLED")
        self.assertEqual(verification_result.status, "FAIL")
        self.assertEqual(verification_result.manual_verification_outcome, "failed")

    def test_result_can_render_future_report_row_without_controller_or_dialog_state(self) -> None:
        result = self._binary_pass_result()

        row = {
            "mode": result.mode,
            "case": result.case_name,
            "command": result.command_display,
            "target_node": result.target_node_id,
            "status": result.status,
            "expected": result.expected,
            "actual": result.actual,
            "latency_ms": result.latency_ms,
            "message": result.message,
        }

        self.assertEqual(row["mode"], "binary")
        self.assertEqual(row["case"], "GETVER")
        self.assertEqual(row["command"], "GETVER (0xC8)")
        self.assertEqual(row["target_node"], 3)
        self.assertEqual(row["status"], "PASS")

    def test_existing_report_dialogs_continue_rendering_results(self) -> None:
        binary_bridge = _FakeBridge()
        binary_controller = FirmwareIntegrationController(binary_bridge)
        self.assertTrue(binary_controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        binary_dialog = BinaryFitReportDialog(binary_controller)
        binary_bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self._app.processEvents()
        self.assertEqual(binary_dialog.results_table.rowCount(), 1)
        self.assertEqual(binary_dialog.results_table.item(0, 6).text(), "PASS")

        text_bridge = _FakeBridge()
        text_controller = FirmwareIntegrationController(text_bridge)
        self.assertTrue(text_controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        text_dialog = TextFitReportDialog(text_controller)
        text_bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        self._app.processEvents()
        self.assertEqual(text_dialog.results_table.rowCount(), 1)
        self.assertEqual(text_dialog.results_table.item(0, 7).text(), "PASS")

    def _binary_pass_result(self) -> FirmwareTestResult:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        controller.binary_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertEqual(len(results), 1)
        return results[0]

    def _binary_timeout_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge())
        results: list[FirmwareTestResult] = []
        controller.binary_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        controller.handle_timeout()
        return results[0]

    def _binary_send_failure_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge(fail_on_send_numbers={1}))
        results: list[FirmwareTestResult] = []
        controller.binary_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        return results[0]

    def _binary_cancel_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge())
        results: list[FirmwareTestResult] = []
        controller.binary_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        self.assertTrue(controller.cancel_binary_fit())
        return results[0]

    def _binary_manual_verification_result(self) -> FirmwareTestResult:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.binary_fit_case_definitions()[0],
            manual_verification=True,
            manual_prompt="Verify firmware manually.",
        )
        results: list[FirmwareTestResult] = []
        controller.binary_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_binary_fit(node_id=3, cases=[manual_case]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertEqual(results, [])
        self.assertTrue(controller.submit_binary_fit_manual_verification(True, "Confirmed."))
        return results[0]

    def _text_pass_result(self) -> FirmwareTestResult:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        return results[0]

    def _text_timeout_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge())
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        controller.handle_timeout()
        return results[0]

    def _text_send_failure_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge(fail_on_write_numbers={1}))
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        return results[0]

    def _text_cancel_result(self) -> FirmwareTestResult:
        controller = FirmwareIntegrationController(_FakeBridge())
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        self.assertTrue(controller.cancel_text_fit())
        return results[0]

    def _text_manual_verification_result(self) -> FirmwareTestResult:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        manual_case = dataclasses.replace(
            controller.text_fit_case_definitions()[0],
            manual_verification=True,
            manual_prompt="Verify text manually.",
        )
        results: list[FirmwareTestResult] = []
        controller.text_fit_case_result.connect(results.append)
        self.assertTrue(controller.start_text_fit(cases=[manual_case]))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        self.assertEqual(results, [])
        self.assertTrue(controller.submit_text_fit_manual_verification(False, "Mismatch."))
        return results[0]


if __name__ == "__main__":
    unittest.main()
