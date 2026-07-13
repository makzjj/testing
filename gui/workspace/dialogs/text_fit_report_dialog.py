"""Text FIT live report dialog for Firmware Integration."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareTestCase, FirmwareTestResult, FirmwareTextFitSnapshot


class TextFitReportDialog(QDialog):
    """UI-only report surface for a running or completed Text FIT session."""

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._signals_connected = False
        self._case_names_by_id = {case.case_id: case.name for case in controller.text_fit_case_definitions()}
        self._command_by_case_id = {
            case.case_id: str(definition.text_command or "--")
            for case in controller.text_fit_case_definitions()
            for definition in controller.manual_text_command_definitions()
            if definition.name == case.command_key
        }

        self.setWindowTitle("Text FIT Report")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(980, 700)
        self.setMinimumSize(860, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        summary_grid = QGridLayout()
        summary_grid.setContentsMargins(0, 0, 0, 0)
        summary_grid.setHorizontalSpacing(8)
        summary_grid.setVerticalSpacing(6)

        self.current_case_label = QLabel("--")
        self.current_case_label.setObjectName("TextFitReportCurrentCaseLabel")
        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("TextFitReportStatusLabel")
        self.status_label.setWordWrap(True)
        self.progress_label = QLabel("0 / 0")
        self.progress_label.setObjectName("TextFitReportProgressLabel")

        summary_grid.addWidget(QLabel("Current Case"), 0, 0)
        summary_grid.addWidget(self.current_case_label, 0, 1)
        summary_grid.addWidget(QLabel("Status"), 1, 0)
        summary_grid.addWidget(self.status_label, 1, 1)
        summary_grid.addWidget(QLabel("Progress"), 2, 0)
        summary_grid.addWidget(self.progress_label, 2, 1)
        root.addLayout(summary_grid)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("TextFitReportProgressBar")
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        self.results_table = QTableWidget(0, 9)
        self.results_table.setObjectName("TextFitReportResultsTable")
        self.results_table.setHorizontalHeaderLabels(
            ["Case", "Command", "Expected", "Actual", "Latency", "TX", "RX", "Result", "Message"]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.results_table, 1)

        self.manual_prompt_container = QWidget()
        self.manual_prompt_container.setObjectName("TextFitReportManualPromptContainer")
        manual_layout = QVBoxLayout(self.manual_prompt_container)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(6)

        self.manual_prompt_label = QLabel("")
        self.manual_prompt_label.setObjectName("TextFitReportManualPromptLabel")
        self.manual_prompt_label.setWordWrap(True)
        manual_layout.addWidget(self.manual_prompt_label)

        self.manual_note_input = QLineEdit()
        self.manual_note_input.setObjectName("TextFitReportManualNoteInput")
        self.manual_note_input.setPlaceholderText("Optional note")
        manual_layout.addWidget(self.manual_note_input)

        manual_actions = QHBoxLayout()
        manual_actions.setContentsMargins(0, 0, 0, 0)
        manual_actions.setSpacing(8)
        self.manual_pass_button = QPushButton("Pass")
        self.manual_pass_button.setObjectName("TextFitReportManualPassButton")
        self.manual_pass_button.setProperty("tone", "primary")
        self.manual_pass_button.clicked.connect(lambda: self._submit_manual_verification(True))
        self.manual_fail_button = QPushButton("Fail")
        self.manual_fail_button.setObjectName("TextFitReportManualFailButton")
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
        self.cancel_button.setObjectName("TextFitReportCancelButton")
        self.cancel_button.setProperty("tone", "danger")
        self.cancel_button.clicked.connect(self._handle_cancel_clicked)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("TextFitReportCloseButton")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self._connect_controller_signals()
        self._refresh_from_snapshot(self._controller.text_fit_status_snapshot())

    def closeEvent(self, event) -> None:  # noqa: N802
        snapshot = self._controller.text_fit_status_snapshot()
        if snapshot.running:
            self._controller.cancel_text_fit()
        self._disconnect_controller_signals()
        super().closeEvent(event)

    def _connect_controller_signals(self) -> None:
        if self._signals_connected:
            return
        self._controller.status_changed.connect(self._handle_controller_signal)
        self._controller.text_fit_case_started.connect(self._handle_controller_signal)
        self._controller.text_fit_case_result.connect(self._handle_controller_signal)
        self._controller.text_fit_manual_verification_requested.connect(self._handle_manual_verification_requested)
        self._controller.text_fit_completed.connect(self._handle_controller_signal)
        self._signals_connected = True

    def _disconnect_controller_signals(self) -> None:
        if not self._signals_connected:
            return
        connections = (
            (self._controller.status_changed, self._handle_controller_signal),
            (self._controller.text_fit_case_started, self._handle_controller_signal),
            (self._controller.text_fit_case_result, self._handle_controller_signal),
            (self._controller.text_fit_manual_verification_requested, self._handle_manual_verification_requested),
            (self._controller.text_fit_completed, self._handle_controller_signal),
        )
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._signals_connected = False

    def _handle_cancel_clicked(self) -> None:
        self._controller.cancel_text_fit()

    def _submit_manual_verification(self, passed: bool) -> None:
        note = self.manual_note_input.text().strip() or None
        self._controller.submit_text_fit_manual_verification(passed, note)

    def _handle_manual_verification_requested(self, _event: object) -> None:
        self._refresh_from_snapshot(self._controller.text_fit_status_snapshot())

    def _handle_controller_signal(self, _event: object = None) -> None:
        self._refresh_from_snapshot(self._controller.text_fit_status_snapshot())

    def _refresh_from_snapshot(self, snapshot: FirmwareTextFitSnapshot) -> None:
        self.current_case_label.setText("--" if snapshot.current_case is None else snapshot.current_case.name)
        status_parts = [snapshot.state.replace("_", " ").title()]
        if snapshot.overall_status:
            status_parts.append(f"({snapshot.overall_status})")
        self.status_label.setText(" ".join(status_parts))
        self.progress_label.setText(f"{snapshot.completed_cases} / {snapshot.total_cases}")
        self.progress_bar.setRange(0, max(1, snapshot.total_cases))
        self.progress_bar.setValue(min(snapshot.completed_cases, snapshot.total_cases))
        self.cancel_button.setEnabled(snapshot.running)
        self.close_button.setEnabled(not snapshot.running)

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
            case_name = self._case_names_by_id.get(result.case_id, result.case_id)
            command_text = self._command_by_case_id.get(result.case_id, "--")
            self.results_table.setItem(row, 0, QTableWidgetItem(case_name))
            self.results_table.setItem(row, 1, QTableWidgetItem(command_text))
            self.results_table.setItem(row, 2, QTableWidgetItem(str(result.expected or "--")))
            self.results_table.setItem(row, 3, QTableWidgetItem(str(result.actual or "--")))
            latency = "--" if result.latency_ms is None else f"{float(result.latency_ms):.1f} ms"
            self.results_table.setItem(row, 4, QTableWidgetItem(latency))
            tx_hex = "--" if result.tx_bytes is None else " ".join(f"{byte:02X}" for byte in result.tx_bytes)
            rx_hex = "--" if result.rx_bytes is None else " ".join(f"{byte:02X}" for byte in result.rx_bytes)
            self.results_table.setItem(row, 5, QTableWidgetItem(tx_hex))
            self.results_table.setItem(row, 6, QTableWidgetItem(rx_hex))
            self.results_table.setItem(row, 7, QTableWidgetItem(result.status))
            self.results_table.setItem(row, 8, QTableWidgetItem(str(result.message or "--")))
        self.results_table.resizeColumnsToContents()
