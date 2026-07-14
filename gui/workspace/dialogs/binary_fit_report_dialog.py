"""Binary FIT live report dialog for Firmware Integration."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareBinaryFitSnapshot, FirmwareTestResult
from services.firmware_report_builder import FirmwareReportBuilder
from services.firmware_report_export_service import FirmwareReportExportService


class BinaryFitReportDialog(QDialog):
    """UI-only report surface for a running or completed Binary FIT session."""

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._signals_connected = False

        self.setWindowTitle("Automated Binary Integration Test")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1150, 500)
        self.setMinimumSize(980, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self.status_label = QLabel("Preparing to run 0 tests...")
        self.status_label.setObjectName("BinaryFitReportStatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.status_label)
        self.target_node_label = QLabel("--", self)
        self.target_node_label.setObjectName("BinaryFitReportTargetNodeLabel")
        self.target_node_label.hide()
        self.current_case_label = QLabel("--", self)
        self.current_case_label.setObjectName("BinaryFitReportCurrentCaseLabel")
        self.current_case_label.hide()
        self.progress_label = QLabel("0 / 0", self)
        self.progress_label.setObjectName("BinaryFitReportProgressLabel")
        self.progress_label.hide()

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("BinaryFitReportProgressBar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.results_table = QTableWidget(0, 7)
        self.results_table.setObjectName("BinaryFitReportResultsTable")
        self.results_table.setHorizontalHeaderLabels(
            ["Command/Feature", "Expected Response", "Actual Response", "TX (Hex)", "RX (Hex)", "Latency (ms)", "Test Status"]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setColumnWidth(0, 170)
        self.results_table.setColumnWidth(1, 250)
        self.results_table.setColumnWidth(2, 160)
        self.results_table.setColumnWidth(3, 120)
        self.results_table.setColumnWidth(4, 120)
        self.results_table.setColumnWidth(5, 85)
        root.addWidget(self.results_table, 1)

        self.manual_prompt_container = QWidget()
        self.manual_prompt_container.setObjectName("BinaryFitReportManualPromptContainer")
        manual_layout = QVBoxLayout(self.manual_prompt_container)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(6)

        self.manual_prompt_label = QLabel("")
        self.manual_prompt_label.setObjectName("BinaryFitReportManualPromptLabel")
        self.manual_prompt_label.setWordWrap(True)
        manual_layout.addWidget(self.manual_prompt_label)

        self.manual_note_input = QLineEdit()
        self.manual_note_input.setObjectName("BinaryFitReportManualNoteInput")
        self.manual_note_input.setPlaceholderText("Optional note")
        manual_layout.addWidget(self.manual_note_input)

        manual_actions = QHBoxLayout()
        manual_actions.setContentsMargins(0, 0, 0, 0)
        manual_actions.setSpacing(8)
        self.manual_pass_button = QPushButton("Pass")
        self.manual_pass_button.setObjectName("BinaryFitReportManualPassButton")
        self.manual_pass_button.setProperty("tone", "primary")
        self.manual_pass_button.clicked.connect(lambda: self._submit_manual_verification(True))
        self.manual_fail_button = QPushButton("Fail")
        self.manual_fail_button.setObjectName("BinaryFitReportManualFailButton")
        self.manual_fail_button.setProperty("tone", "danger")
        self.manual_fail_button.clicked.connect(lambda: self._submit_manual_verification(False))
        manual_actions.addWidget(self.manual_pass_button)
        manual_actions.addWidget(self.manual_fail_button)
        manual_actions.addStretch(1)
        manual_layout.addLayout(manual_actions)
        root.addWidget(self.manual_prompt_container)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        footer.addStretch(1)
        self.cancel_button = QPushButton("Cancel Run")
        self.cancel_button.setObjectName("BinaryFitReportCancelButton")
        self.cancel_button.setProperty("tone", "danger")
        self.cancel_button.clicked.connect(self._handle_cancel_clicked)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("BinaryFitReportCloseButton")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)
        self.export_button = QPushButton("Export Report")
        self.export_button.setObjectName("BinaryFitReportExportButton")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_report)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.export_button)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self._connect_controller_signals()

        self._refresh_from_snapshot(self._controller.binary_fit_status_snapshot())

    def closeEvent(self, event) -> None:  # noqa: N802
        snapshot = self._controller.binary_fit_status_snapshot()
        if snapshot.running:
            self._controller.cancel_binary_fit()
        self._disconnect_controller_signals()
        super().closeEvent(event)

    def _connect_controller_signals(self) -> None:
        if self._signals_connected:
            return
        self._controller.status_changed.connect(self._handle_controller_signal)
        self._controller.binary_fit_case_started.connect(self._handle_controller_signal)
        self._controller.binary_fit_case_result.connect(self._handle_controller_signal)
        self._controller.binary_fit_manual_verification_requested.connect(self._handle_manual_verification_requested)
        self._controller.binary_fit_completed.connect(self._handle_controller_signal)
        self._signals_connected = True

    def _disconnect_controller_signals(self) -> None:
        if not self._signals_connected:
            return
        connections = (
            (self._controller.status_changed, self._handle_controller_signal),
            (self._controller.binary_fit_case_started, self._handle_controller_signal),
            (self._controller.binary_fit_case_result, self._handle_controller_signal),
            (self._controller.binary_fit_manual_verification_requested, self._handle_manual_verification_requested),
            (self._controller.binary_fit_completed, self._handle_controller_signal),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._signals_connected = False

    def _handle_cancel_clicked(self) -> None:
        self._controller.cancel_binary_fit()

    def _submit_manual_verification(self, passed: bool) -> None:
        note = self.manual_note_input.text().strip() or None
        self._controller.submit_binary_fit_manual_verification(passed, note)

    def _handle_manual_verification_requested(self, _event: object) -> None:
        self._refresh_from_snapshot(self._controller.binary_fit_status_snapshot())

    def _handle_controller_signal(self, _event: object = None) -> None:
        self._refresh_from_snapshot(self._controller.binary_fit_status_snapshot())

    def _refresh_from_snapshot(self, snapshot: FirmwareBinaryFitSnapshot) -> None:
        if snapshot.running and snapshot.current_index < snapshot.total_cases:
            self.status_label.setText(f"Running test {snapshot.current_index + 1} of {snapshot.total_cases}...")
        elif snapshot.total_cases:
            self.status_label.setText(f"Test run completed. Passed {self._pass_count(snapshot.results)} of {snapshot.total_cases} test cases.")
        else:
            self.status_label.setText("Preparing to run 0 tests...")
        self.progress_bar.setRange(0, max(1, snapshot.total_cases))
        self.progress_bar.setValue(min(snapshot.completed_cases, snapshot.total_cases))
        self.target_node_label.setText("--" if snapshot.target_node_id is None else f"Node {snapshot.target_node_id:02d}")
        self.current_case_label.setText("--" if snapshot.current_case is None else snapshot.current_case.name)
        self.progress_label.setText(f"{snapshot.completed_cases} / {snapshot.total_cases}")
        self.cancel_button.setEnabled(snapshot.running)
        self.close_button.setEnabled(not snapshot.running)
        self.export_button.setEnabled((not snapshot.running) and bool(snapshot.results))

        awaiting = snapshot.awaiting_manual_verification
        self.manual_prompt_container.setVisible(awaiting)
        if awaiting:
            prompt = snapshot.manual_verification_prompt or "Manual verification required."
            case_name = snapshot.current_case.name if snapshot.current_case is not None else "Current case"
            self.manual_prompt_label.setText(f"{case_name}\n{prompt}")
            self.manual_pass_button.setEnabled(True)
            self.manual_fail_button.setEnabled(True)
        else:
            self.manual_prompt_label.setText("")
            self.manual_note_input.clear()
            self.manual_pass_button.setEnabled(False)
            self.manual_fail_button.setEnabled(False)

        self._populate_results(snapshot.results)

    def _populate_results(self, results: tuple[FirmwareTestResult, ...]) -> None:
        self.results_table.setRowCount(len(results))
        for row, result in enumerate(results):
            self.results_table.setItem(row, 0, QTableWidgetItem(str(result.case_name or result.command_display or result.case_id)))
            self.results_table.setItem(row, 1, QTableWidgetItem(str(result.expected or "--")))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(result.actual or result.message or "--")))
            latency = "--" if result.latency_ms is None else f"{float(result.latency_ms):.1f} ms"
            tx_hex = "--" if result.tx_bytes is None else " ".join(f"{byte:02X}" for byte in result.tx_bytes)
            rx_hex = "--" if result.rx_bytes is None else " ".join(f"{byte:02X}" for byte in result.rx_bytes)
            self.results_table.setItem(row, 3, QTableWidgetItem(tx_hex))
            self.results_table.setItem(row, 4, QTableWidgetItem(rx_hex))
            self.results_table.setItem(row, 5, QTableWidgetItem(latency))
            self.results_table.setItem(row, 6, QTableWidgetItem(result.status))
        self.results_table.resizeColumnsToContents()

    def _export_report(self) -> None:
        report = self._controller.latest_binary_fit_report()
        if report is None:
            QMessageBox.warning(self, "Export Report", "No completed Binary FIT report is available.")
            return
        service = FirmwareReportExportService()
        html = FirmwareReportBuilder().build_html(report)
        result = service.export_html(html, service.last_export_directory(), service.suggest_filename(report))
        if result.success:
            QMessageBox.information(self, "Success", f"Report exported successfully!\n{result.path}")
        else:
            QMessageBox.critical(self, "Error", f"Failed to export report: {result.error or result.message}")

    @staticmethod
    def _pass_count(results: tuple[FirmwareTestResult, ...]) -> int:
        return sum(1 for result in results if str(result.status).upper() == "PASS")
