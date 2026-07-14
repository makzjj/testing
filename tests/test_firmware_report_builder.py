from __future__ import annotations

import dataclasses
import os
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.models import FirmwareFitReport, FirmwareTestResult
from services.firmware_report_builder import FirmwareReportBuilder, derive_fit_overall_status


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return True

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.writes.append(payload)


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

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class FirmwareReportBuilderTests(unittest.TestCase):
    def test_report_model_is_immutable_data_only_and_counts_results(self) -> None:
        report = self._sample_report()

        self.assertTrue(dataclasses.is_dataclass(report))
        with self.assertRaises(FrozenInstanceError):
            report.overall_status = "FAILED"  # type: ignore[misc]
        for field in dataclasses.fields(report):
            value = getattr(report, field.name)
            self.assertNotIsInstance(value, QObject)
            self.assertFalse(hasattr(value, "packet_received"))
            self.assertFalse(hasattr(value, "send_command_bytes"))
        self.assertEqual(report.passed_count, 1)
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.target_node_id, 3)

    def test_status_policy(self) -> None:
        passed = (self._result(status="PASS"),)
        failed = (self._result(status="PASS"), self._result(status="FAIL"))
        timeout = (self._result(status="TIMEOUT"),)
        error = (self._result(status="ERROR"),)

        self.assertEqual(derive_fit_overall_status(passed), "PASSED")
        self.assertEqual(derive_fit_overall_status(failed), "FAILED")
        self.assertEqual(derive_fit_overall_status(timeout), "FAILED")
        self.assertEqual(derive_fit_overall_status(error), "FAILED")
        self.assertEqual(derive_fit_overall_status(passed, cancelled=True), "CANCELLED")
        self.assertEqual(derive_fit_overall_status((self._result(status="CANCELLED"),)), "CANCELLED")

    def test_builder_returns_complete_deterministic_html_and_formats_values(self) -> None:
        report = self._sample_report()
        builder = FirmwareReportBuilder()

        first = builder.build_html(report)
        second = builder.build_html(report)

        self.assertEqual(first, second)
        self.assertIn("<!DOCTYPE html>", first)
        self.assertIn("<h1>BioBot Firmware Integration Test Report</h1>", first)
        self.assertIn("Test Type", first)
        self.assertIn("Target Node ID", first)
        self.assertIn("Overall Result", first)
        for heading in ["Command Name", "Status", "Expected", "Actual Response", "Latency"]:
            self.assertIn(f">{heading}</th>", first)
        self.assertIn("25.0 ms", first)
        self.assertIn("Target Node ID", first)
        self.assertIn("<span class='meta-value'>3</span>", first)
        self.assertIn("C8 3F", first)
        self.assertIn("C8 3A 12 30 01", first)
        self.assertIn("#f47c20", first)

    def test_builder_escapes_dynamic_content(self) -> None:
        report = FirmwareFitReport(
            run_id="run-<unsafe>",
            mode="text",
            started_at="1.000",
            completed_at="2.000",
            duration_ms=1000.0,
            overall_status="FAILED",
            selected_case_count=1,
            completed_case_count=1,
            results=(
                self._result(
                    mode="text",
                    case_name="<script>alert(1)</script>",
                    command_display="ver?<b>",
                    actual="ver:<bad>",
                    message='operator "note" & response',
                    target_node_id=None,
                ),
            ),
            error_count=1,
        )

        html = FirmwareReportBuilder().build_html(report)

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("ver:&lt;bad&gt;", html)
        self.assertIn("operator &quot;note&quot; &amp; response", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_builder_has_no_filesystem_side_effects_or_qt_dependency(self) -> None:
        before = {path for path in Path(".").iterdir()}

        FirmwareReportBuilder().build_html(self._sample_report())

        after = {path for path in Path(".").iterdir()}
        self.assertEqual(before, after)
        source = Path("services/firmware_report_builder.py").read_text(encoding="utf-8")
        self.assertNotIn("PyQt", source)
        self.assertNotIn("QSettings", source)
        self.assertNotIn("open(", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("write_bytes", source)

    def test_controller_assembles_completed_binary_and_text_reports(self) -> None:
        binary_clock = _Clock(10.0)
        binary_bridge = _FakeBridge()
        binary_controller = FirmwareIntegrationController(binary_bridge, clock=binary_clock)
        self.assertTrue(binary_controller.start_binary_fit(node_id=3, selected_case_ids=["binary-fit-getver"]))
        binary_clock.value = 10.050
        binary_bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        binary_report = binary_controller.latest_binary_fit_report()
        self.assertIsNotNone(binary_report)
        assert binary_report is not None
        self.assertEqual(binary_report.mode, "binary")
        self.assertEqual(binary_report.run_id, "binary-fit-10.000")
        self.assertEqual(binary_report.started_at, "10.000")
        self.assertEqual(binary_report.completed_at, "10.050")
        self.assertAlmostEqual(binary_report.duration_ms or 0.0, 50.0, delta=0.001)
        self.assertEqual(binary_report.overall_status, "PASSED")
        self.assertEqual(binary_report.target_node_id, 3)
        self.assertEqual(binary_report.results[0].case_name, "GETVER")

        text_clock = _Clock(20.0)
        text_bridge = _FakeBridge()
        text_controller = FirmwareIntegrationController(text_bridge, clock=text_clock)
        self.assertTrue(text_controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        text_clock.value = 20.025
        text_bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        text_report = text_controller.latest_text_fit_report()
        self.assertIsNotNone(text_report)
        assert text_report is not None
        self.assertEqual(text_report.mode, "text")
        self.assertEqual(text_report.run_id, "text-fit-20.000")
        self.assertEqual(text_report.overall_status, "PASSED")
        self.assertIsNone(text_report.target_node_id)
        self.assertEqual(text_report.results[0].command_display, "ver?")

    def test_controller_assembles_cancelled_report(self) -> None:
        clock = _Clock(50.0)
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge, clock=clock)
        self.assertTrue(controller.start_text_fit(selected_case_ids=["text-fit-version-query"]))
        clock.value = 51.0
        self.assertTrue(controller.cancel_text_fit())

        report = controller.latest_text_fit_report()
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(report.overall_status, "CANCELLED")
        self.assertEqual(report.cancelled_count, 1)
        self.assertEqual(report.results[0].status, "CANCELLED")

    def test_architecture_contains_no_export_ui_or_legacy_import(self) -> None:
        report_builder_source = Path("services/firmware_report_builder.py").read_text(encoding="utf-8")
        controller_source = Path("gui/workspace/controllers/firmware_integration_controller.py").read_text(encoding="utf-8")

        self.assertNotIn("QFileDialog", report_builder_source)
        self.assertNotIn("QSettings", report_builder_source)
        self.assertNotIn("legacy_reference.firmware_integration_test", controller_source)
        self.assertNotIn("legacy_reference.firmware_integration_test", report_builder_source)

    def _sample_report(self) -> FirmwareFitReport:
        results = (
            self._result(status="PASS"),
            self._result(status="FAIL", case_id="binary-fit-getpos", case_name="GETPOS", command_display="GETPOS (0x82)"),
        )
        return FirmwareFitReport(
            run_id="binary-fit-100.000",
            mode="binary",
            started_at="100.000",
            completed_at="100.100",
            duration_ms=100.0,
            overall_status="FAILED",
            selected_case_count=2,
            completed_case_count=2,
            target_node_id=3,
            results=results,
            passed_count=1,
            failed_count=1,
        )

    def _result(
        self,
        *,
        status: str = "PASS",
        mode: str = "binary",
        case_id: str = "binary-fit-getver",
        case_name: str = "GETVER",
        command_key: str = "GETVER",
        command_display: str = "GETVER (0xC8)",
        target_node_id: int | None = 3,
        actual: str | None = "firmware: v1.2.3",
        message: str | None = "ok",
    ) -> FirmwareTestResult:
        return FirmwareTestResult(
            case_id=case_id,
            status=status,
            mode=mode,
            case_name=case_name,
            command_key=command_key,
            command_display=command_display,
            target_node_id=target_node_id,
            expected="firmware",
            actual=actual,
            tx_bytes=b"\xC8\x3F",
            rx_bytes=b"\xC8\x3A\x12\x30\x01",
            latency_ms=25.0,
            message=message,
        )


if __name__ == "__main__":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    unittest.main()
