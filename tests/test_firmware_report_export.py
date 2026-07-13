from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from gui.workspace.dialogs import FirmwareReportExportDialog
from gui.workspace.models import FirmwareFitReport, FirmwareTestResult
from gui.workspace.pages.firmware_page import FirmwarePage
from services.firmware_report_builder import FirmwareReportBuilder
from services.firmware_report_export_service import (
    REPORT_SAVE_LOCATION_KEY,
    FirmwareReportExportResult,
    FirmwareReportExportService,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _result(*, mode: str = "binary", target_node_id: int | None = 7) -> FirmwareTestResult:
    return FirmwareTestResult(
        case_id=f"{mode}-case",
        status="PASS",
        mode=mode,
        case_name=f"{mode.title()} Case",
        command_key="GETVER" if mode == "binary" else "Version Query",
        command_display="GETVER" if mode == "binary" else "ver?",
        target_node_id=target_node_id,
        expected="version",
        actual="version 1.2.3",
        tx_bytes=b"\x01\x02",
        rx_bytes=b"\x03\x04",
        latency_ms=12.5,
        message="ok",
    )


def _report(*, mode: str = "binary", target_node_id: int | None = 7) -> FirmwareFitReport:
    result = _result(mode=mode, target_node_id=target_node_id)
    return FirmwareFitReport(
        run_id=f"{mode}-run-1",
        mode=mode,
        started_at="2026-07-13T14:25:00",
        completed_at="2026-07-13T14:25:30",
        duration_ms=30000.0,
        overall_status="PASSED",
        selected_case_count=1,
        completed_case_count=1,
        target_node_id=target_node_id,
        results=(result,),
        passed_count=1,
    )


class _FakeBuilder:
    def __init__(self) -> None:
        self.reports: list[FirmwareFitReport] = []

    def build_html(self, report: FirmwareFitReport) -> str:
        self.reports.append(report)
        return f"<html>{report.run_id}</html>"


class _FakeExportService:
    def __init__(self, directory: Path, result: FirmwareReportExportResult | None = None) -> None:
        self._directory = directory
        self.result = result
        self.filenames: list[str] = []
        self.exports: list[tuple[str, str, str]] = []

    def last_export_directory(self) -> Path:
        return self._directory

    def suggest_filename(self, report: FirmwareFitReport, wall_clock_time: datetime | None = None) -> str:
        _ = wall_clock_time
        filename = f"FIT_{report.mode}_fake.html"
        self.filenames.append(filename)
        return filename

    def export_html(self, html: str, directory_or_path: str | Path, filename: str | None = None) -> FirmwareReportExportResult:
        self.exports.append((html, str(directory_or_path), str(filename or "")))
        if self.result is not None:
            return self.result
        return FirmwareReportExportResult(
            success=True,
            path=Path(directory_or_path) / str(filename),
            message=f"Exported report to {Path(directory_or_path) / str(filename)}",
        )


class _ReportController:
    def __init__(
        self,
        *,
        binary_report: FirmwareFitReport | None = None,
        text_report: FirmwareFitReport | None = None,
    ) -> None:
        self.binary_report = binary_report
        self.text_report = text_report
        self.requested_modes: list[str] = []

    def latest_fit_report(self, mode: str) -> FirmwareFitReport | None:
        self.requested_modes.append(mode)
        if mode == "binary":
            return self.binary_report
        if mode == "text":
            return self.text_report
        return None


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((node_id, list(payload)))
        return bytearray(payload)

    def write(self, payload: bytearray) -> None:
        self.writes.append(bytearray(payload))

    def is_connected(self) -> bool:
        return True


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient()


class _FakeBridge:
    def __init__(self) -> None:
        self.raw_config = {"robot": {"axes": {"x": {"node_id": 7}}}}
        self._runtime_window = _FakeRuntimeWindow()
        self.runtime_window_requests = 0

    def get_frame_loss_items(self) -> list[object]:
        return []

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return [(7, "X")]

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return True, True

    def get_runtime_window(self, *, create_if_missing: bool = False):
        self.runtime_window_requests += 1
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class FirmwareReportExportServiceTests(unittest.TestCase):
    def _settings(self, path: Path) -> QSettings:
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        settings.clear()
        settings.sync()
        return settings

    def test_suggest_filename_uses_wall_clock_mode_and_binary_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "settings.ini")
            service = FirmwareReportExportService(
                settings=settings,
                wall_clock=lambda: datetime(2026, 7, 13, 14, 25, 30),
            )

            self.assertEqual(service.suggest_filename(_report()), "FIT_binary_node7_20260713_142530.html")
            self.assertEqual(
                service.suggest_filename(_report(mode="text", target_node_id=None)),
                "FIT_text_20260713_142530.html",
            )

    def test_resolve_available_path_adds_collision_suffixes_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            service = FirmwareReportExportService(settings=self._settings(directory / "settings.ini"))
            first = directory / "FIT_binary_node7_20260713_142530.html"
            second = directory / "FIT_binary_node7_20260713_142530_1.html"
            first.write_text("first", encoding="utf-8")
            self.assertEqual(
                service.resolve_available_path(directory, first.name),
                second,
            )
            second.write_text("second", encoding="utf-8")
            self.assertEqual(
                service.resolve_available_path(directory, first.name),
                directory / "FIT_binary_node7_20260713_142530_2.html",
            )
            self.assertEqual(first.read_text(encoding="utf-8"), "first")

    def test_invalid_saved_directory_falls_back_to_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings = self._settings(Path(temp_dir) / "settings.ini")
            settings.setValue(REPORT_SAVE_LOCATION_KEY, str(Path(temp_dir) / "missing"))
            service = FirmwareReportExportService(settings=settings)

            self.assertTrue(service.last_export_directory().exists())
            self.assertNotEqual(service.last_export_directory(), Path(temp_dir) / "missing")

    def test_successful_export_writes_html_and_persists_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "exports"
            settings = self._settings(Path(temp_dir) / "settings.ini")
            service = FirmwareReportExportService(settings=settings)

            result = service.export_html("<html>report</html>", directory, "FIT_binary.html")

            self.assertTrue(result.success)
            self.assertIsNotNone(result.path)
            assert result.path is not None
            self.assertEqual(result.path.read_text(encoding="utf-8"), "<html>report</html>")
            self.assertEqual(Path(str(settings.value(REPORT_SAVE_LOCATION_KEY))), directory)

    def test_failed_export_returns_error_and_does_not_persist_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir) / "exports"
            settings = self._settings(Path(temp_dir) / "settings.ini")
            service = FirmwareReportExportService(settings=settings)

            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                result = service.export_html("<html>report</html>", directory, "FIT_binary.html")

            self.assertFalse(result.success)
            self.assertIn("disk full", str(result.error))
            self.assertEqual(settings.value(REPORT_SAVE_LOCATION_KEY, ""), "")

    def test_exporting_same_filename_twice_does_not_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            service = FirmwareReportExportService(settings=self._settings(directory / "settings.ini"))

            first = service.export_html("one", directory, "FIT_binary.html")
            second = service.export_html("two", directory, "FIT_binary.html")

            self.assertTrue(first.success)
            self.assertTrue(second.success)
            self.assertIsNotNone(first.path)
            self.assertIsNotNone(second.path)
            assert first.path is not None and second.path is not None
            self.assertNotEqual(first.path, second.path)
            self.assertEqual(first.path.read_text(encoding="utf-8"), "one")
            self.assertEqual(second.path.read_text(encoding="utf-8"), "two")


class FirmwareReportExportDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dialog_disables_export_when_selected_report_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = _ReportController()
            dialog = FirmwareReportExportDialog(
                controller,
                report_builder=_FakeBuilder(),
                export_service=_FakeExportService(Path(temp_dir)),
            )

            self.assertFalse(dialog.export_button.isEnabled())
            self.assertIn("No completed Binary FIT report available", dialog.summary_output.toPlainText())

    def test_dialog_reads_latest_reports_and_renders_binary_and_text_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller = _ReportController(
                binary_report=_report(),
                text_report=_report(mode="text", target_node_id=None),
            )
            dialog = FirmwareReportExportDialog(
                controller,
                report_builder=_FakeBuilder(),
                export_service=_FakeExportService(Path(temp_dir)),
            )

            self.assertTrue(dialog.export_button.isEnabled())
            self.assertEqual(dialog.target_node_label.text(), "Node 07")
            self.assertIn("binary", controller.requested_modes)

            dialog.report_type_combo.setCurrentIndex(1)
            self._app.processEvents()

            self.assertEqual(dialog.target_node_label.text(), "N/A")
            self.assertIn("text", controller.requested_modes)

    def test_browse_updates_selected_directory_without_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = str(Path(temp_dir) / "selected")
            export_service = _FakeExportService(Path(temp_dir))
            dialog = FirmwareReportExportDialog(
                _ReportController(binary_report=_report()),
                report_builder=_FakeBuilder(),
                export_service=export_service,
            )

            with patch(
                "gui.workspace.dialogs.firmware_report_export_dialog.QFileDialog.getExistingDirectory",
                return_value=selected,
            ):
                dialog.browse_button.click()
                self._app.processEvents()

            self.assertEqual(dialog.directory_input.text(), selected)
            self.assertEqual(export_service.exports, [])

    def test_export_calls_builder_and_service_and_displays_success_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = _report()
            builder = _FakeBuilder()
            export_service = _FakeExportService(Path(temp_dir))
            dialog = FirmwareReportExportDialog(
                _ReportController(binary_report=report),
                report_builder=builder,
                export_service=export_service,
            )

            dialog.export_button.click()
            self._app.processEvents()

            self.assertEqual(builder.reports, [report])
            self.assertEqual(len(export_service.exports), 1)
            html, directory, filename = export_service.exports[0]
            self.assertEqual(html, "<html>binary-run-1</html>")
            self.assertEqual(directory, str(Path(temp_dir)))
            self.assertEqual(filename, "FIT_binary_fake.html")
            self.assertIn("Exported report to", dialog.status_label.text())

    def test_export_failure_displays_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            export_service = _FakeExportService(
                Path(temp_dir),
                FirmwareReportExportResult(success=False, error="permission denied"),
            )
            dialog = FirmwareReportExportDialog(
                _ReportController(binary_report=_report()),
                report_builder=_FakeBuilder(),
                export_service=export_service,
            )

            dialog.export_button.click()
            self._app.processEvents()

            self.assertIn("permission denied", dialog.status_label.text())

    def test_reports_launcher_opens_export_dialog_without_sending_commands(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        button = page.findChild(QPushButton, "FirmwareFitReportsButton")
        self.assertIsNotNone(button)
        assert button is not None
        button.click()
        self._app.processEvents()

        dialog = page._report_export_dialog
        self.assertIsInstance(dialog, FirmwareReportExportDialog)
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.backend_client.writes, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)
        self.assertEqual(bridge.runtime_window_requests, 0)


class FirmwareReportExportArchitectureTests(unittest.TestCase):
    def test_report_model_remains_immutable(self) -> None:
        report = _report()
        with self.assertRaises(FrozenInstanceError):
            report.run_id = "changed"  # type: ignore[misc]

    def test_builder_remains_filesystem_free(self) -> None:
        source = inspect.getsource(FirmwareReportBuilder)
        self.assertNotIn("QFileDialog", source)
        self.assertNotIn("QSettings", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("open(", source)

    def test_export_service_contains_no_html_formatting_or_controller_access(self) -> None:
        source = inspect.getsource(FirmwareReportExportService)
        self.assertNotIn("build_html", source)
        self.assertNotIn("<table", source)
        self.assertNotIn("<html", source)
        self.assertNotIn("FirmwareIntegrationController", source)
        self.assertNotIn("_BinaryFitWorkflow", source)
        self.assertNotIn("_TextFitWorkflow", source)

    def test_controller_contains_no_file_writing_or_settings_ownership(self) -> None:
        source = Path("gui/workspace/controllers/firmware_integration_controller.py").read_text(encoding="utf-8")
        self.assertNotIn("QFileDialog", source)
        self.assertNotIn("QSettings", source)
        self.assertNotIn("write_text", source)
        self.assertNotIn("FirmwareReportExportService", source)

    def test_binary_and_text_report_dialogs_remain_export_free(self) -> None:
        for path in (
            Path("gui/workspace/dialogs/binary_fit_report_dialog.py"),
            Path("gui/workspace/dialogs/text_fit_report_dialog.py"),
        ):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("FirmwareReportExportService", source)
            self.assertNotIn("Export HTML", source)
            self.assertNotIn("QFileDialog", source)

    def test_export_dialog_uses_public_report_access_only(self) -> None:
        source = Path("gui/workspace/dialogs/firmware_report_export_dialog.py").read_text(encoding="utf-8")
        self.assertIn("latest_fit_report", source)
        self.assertNotIn("_BinaryFitWorkflow", source)
        self.assertNotIn("_TextFitWorkflow", source)
        self.assertNotIn("_active_operation", source)
        self.assertNotIn("FirmwareTransportAdapter", source)
        self.assertNotIn("backend_client", source)

    def test_legacy_widget_not_imported(self) -> None:
        sources = [
            Path("gui/workspace/dialogs/firmware_report_export_dialog.py").read_text(encoding="utf-8"),
            Path("services/firmware_report_export_service.py").read_text(encoding="utf-8"),
        ]
        self.assertFalse(any("legacy_reference.firmware_integration_test" in source for source in sources))


if __name__ == "__main__":
    unittest.main()
