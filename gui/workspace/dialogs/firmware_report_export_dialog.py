"""Shared Firmware Integration report export dialog."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.firmware_report_builder import FirmwareReportBuilder
from services.firmware_report_export_service import FirmwareReportExportService

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareFitReport


class FirmwareReportExportDialog(QDialog):
    """UI-only selector and export surface for latest FIT reports."""

    def __init__(
        self,
        controller: FirmwareIntegrationController,
        parent: QWidget | None = None,
        *,
        report_builder: FirmwareReportBuilder | None = None,
        export_service: FirmwareReportExportService | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._report_builder = report_builder or FirmwareReportBuilder()
        self._export_service = export_service or FirmwareReportExportService()

        self.setWindowTitle("Firmware Reports / Export")
        self.setModal(False)
        self.resize(720, 520)
        self.setMinimumSize(640, 460)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.report_type_combo = QComboBox()
        self.report_type_combo.setObjectName("FirmwareReportExportTypeCombo")
        self.report_type_combo.addItem("Latest Binary FIT", "binary")
        self.report_type_combo.addItem("Latest Text FIT", "text")
        self.report_type_combo.currentIndexChanged.connect(self._refresh_summary)
        root.addWidget(self.report_type_combo)

        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(8)
        summary_grid.setVerticalSpacing(6)
        self.mode_label = QLabel("--")
        self.mode_label.setObjectName("FirmwareReportExportModeLabel")
        self.status_value_label = QLabel("--")
        self.status_value_label.setObjectName("FirmwareReportExportOverallStatusLabel")
        self.run_id_label = QLabel("--")
        self.run_id_label.setObjectName("FirmwareReportExportRunIdLabel")
        self.completed_label = QLabel("--")
        self.completed_label.setObjectName("FirmwareReportExportCompletedLabel")
        self.target_node_label = QLabel("--")
        self.target_node_label.setObjectName("FirmwareReportExportTargetNodeLabel")
        self.counts_label = QLabel("--")
        self.counts_label.setObjectName("FirmwareReportExportCountsLabel")
        for row, (label, widget) in enumerate(
            (
                ("Mode", self.mode_label),
                ("Overall Status", self.status_value_label),
                ("Run ID", self.run_id_label),
                ("Completed", self.completed_label),
                ("Target Node", self.target_node_label),
                ("Counts", self.counts_label),
            )
        ):
            summary_grid.addWidget(QLabel(label), row, 0)
            summary_grid.addWidget(widget, row, 1)
        root.addLayout(summary_grid)

        self.summary_output = QTextEdit()
        self.summary_output.setObjectName("FirmwareReportExportSummaryOutput")
        self.summary_output.setReadOnly(True)
        root.addWidget(self.summary_output, 1)

        directory_row = QHBoxLayout()
        directory_row.setContentsMargins(0, 0, 0, 0)
        directory_row.setSpacing(8)
        self.directory_input = QLineEdit(str(self._export_service.last_export_directory()))
        self.directory_input.setObjectName("FirmwareReportExportDirectoryInput")
        self.browse_button = QPushButton("Browse")
        self.browse_button.setObjectName("FirmwareReportExportBrowseButton")
        self.browse_button.clicked.connect(self._browse_directory)
        directory_row.addWidget(self.directory_input, 1)
        directory_row.addWidget(self.browse_button)
        root.addLayout(directory_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("FirmwareReportExportStatusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        self.export_button = QPushButton("Export HTML")
        self.export_button.setObjectName("FirmwareReportExportHtmlButton")
        self.export_button.setProperty("tone", "primary")
        self.export_button.clicked.connect(self._export_selected_report)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("FirmwareReportExportCloseButton")
        self.close_button.clicked.connect(self.close)
        actions.addWidget(self.export_button)
        actions.addWidget(self.close_button)
        root.addLayout(actions)

        self._refresh_summary()

    def selected_report(self) -> FirmwareFitReport | None:
        mode = str(self.report_type_combo.currentData() or "")
        return self._controller.latest_fit_report(mode)

    def _browse_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Firmware Report Export Folder",
            self.directory_input.text().strip() or str(self._export_service.last_export_directory()),
        )
        if selected:
            self.directory_input.setText(selected)
            self._refresh_summary()

    def _export_selected_report(self) -> None:
        report = self.selected_report()
        if report is None:
            self.status_label.setText(self._empty_report_message())
            self.export_button.setEnabled(False)
            return
        html = self._report_builder.build_html(report)
        filename = self._export_service.suggest_filename(report)
        result = self._export_service.export_html(html, self.directory_input.text().strip(), filename)
        if result.success:
            self.status_label.setText(str(result.message or f"Exported report to {result.path}"))
            if result.path is not None:
                self.directory_input.setText(str(Path(result.path).parent))
            return
        self.status_label.setText(str(result.error or result.message or "Failed to export report."))

    def _refresh_summary(self) -> None:
        report = self.selected_report()
        if report is None:
            self.mode_label.setText("--")
            self.status_value_label.setText("--")
            self.run_id_label.setText("--")
            self.completed_label.setText("--")
            self.target_node_label.setText("--")
            self.counts_label.setText("--")
            self.summary_output.setPlainText(self._empty_report_message())
            self.export_button.setEnabled(False)
            self.status_label.setText("")
            return

        self.mode_label.setText("Binary FIT" if report.mode == "binary" else "Text FIT")
        self.status_value_label.setText(report.overall_status)
        self.run_id_label.setText(report.run_id)
        self.completed_label.setText(str(report.completed_at or "N/A"))
        self.target_node_label.setText("N/A" if report.target_node_id is None else f"Node {int(report.target_node_id):02d}")
        self.counts_label.setText(
            f"PASS {report.passed_count} / FAIL {report.failed_count} / "
            f"TIMEOUT {report.timeout_count} / ERROR {report.error_count} / CANCELLED {report.cancelled_count}"
        )
        self.summary_output.setPlainText(
            "\n".join(
                [
                    f"Selected cases: {report.selected_case_count}",
                    f"Completed cases: {report.completed_case_count}",
                    f"Duration: {'N/A' if report.duration_ms is None else f'{report.duration_ms:.1f} ms'}",
                    f"Results: {len(report.results)}",
                ]
            )
        )
        self.export_button.setEnabled(True)
        self.status_label.setText("")

    def _empty_report_message(self) -> str:
        mode = str(self.report_type_combo.currentData() or "")
        if mode == "binary":
            return "No completed Binary FIT report available."
        if mode == "text":
            return "No completed Text FIT report available."
        return "No completed FIT report available."
