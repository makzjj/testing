"""Sampling Test popup for monitoring the IPQC sampling run."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class SamplingTestPopup(QDialog):
    """Modeless Sampling Test dialog that mirrors controller state."""

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sampling Test")
        self.setModal(False)
        self.resize(1024, 640)
        self.setMinimumSize(900, 560)

        self._selected_node_id = "-"
        self._selected_node_name = "-"
        self._sampling_sheet_name = "-"
        self._start_available = False
        self._stop_available = False
        self._current_total_samples = 32

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        summary_frame, summary_body = self._build_card("Sampling Summary")
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(10)

        left_summary = QWidget()
        left_summary_layout = QGridLayout(left_summary)
        left_summary_layout.setContentsMargins(0, 0, 0, 0)
        left_summary_layout.setHorizontalSpacing(8)
        left_summary_layout.setVerticalSpacing(6)

        self.selected_node_value = self._make_value_label("-")
        self.state_value = self._make_value_label("IDLE")
        self.final_status_value = self._make_value_label("IDLE")

        left_summary_layout.addWidget(QLabel("Selected Node"), 0, 0)
        left_summary_layout.addWidget(self.selected_node_value, 0, 1)
        left_summary_layout.addWidget(QLabel("Current State"), 1, 0)
        left_summary_layout.addWidget(self.state_value, 1, 1)
        left_summary_layout.addWidget(QLabel("Final Status"), 2, 0)
        left_summary_layout.addWidget(self.final_status_value, 2, 1)
        left_summary_layout.setColumnStretch(1, 1)

        middle_summary = QWidget()
        middle_summary_layout = QGridLayout(middle_summary)
        middle_summary_layout.setContentsMargins(0, 0, 0, 0)
        middle_summary_layout.setHorizontalSpacing(8)
        middle_summary_layout.setVerticalSpacing(6)

        self.sampling_sheet_value = self._make_value_label("-")
        self.status_value = self._make_value_label("Idle")
        self.reason_value = self._make_value_label("-")
        self.range_mode_combo = QComboBox()
        self.range_mode_combo.addItems(["Full Range", "Half Range", "Quarter Range"])
        self.range_mode_combo.setEnabled(False)
        self.range_mode_combo.setToolTip("TODO: range mode behavior is not implemented yet.")

        self.samples_per_pwm_combo = QComboBox()
        self.samples_per_pwm_combo.addItems(["1", "2", "4", "8", "16", "32"])
        self.samples_per_pwm_combo.setCurrentIndex(5)

        self.pwm_selection_combo = QComboBox()
        self.pwm_selection_combo.addItems(["All", "100", "90", "80", "70", "60"])
        self.pwm_selection_combo.setCurrentIndex(0)

        middle_summary_layout.addWidget(QLabel("Sampling Sheet"), 0, 0)
        middle_summary_layout.addWidget(self.sampling_sheet_value, 0, 1)
        middle_summary_layout.addWidget(QLabel("Current Status"), 1, 0)
        middle_summary_layout.addWidget(self.status_value, 1, 1)
        middle_summary_layout.addWidget(QLabel("Reason"), 2, 0)
        middle_summary_layout.addWidget(self.reason_value, 2, 1)
        middle_summary_layout.addWidget(QLabel("Range Mode"), 3, 0)
        middle_summary_layout.addWidget(self.range_mode_combo, 3, 1)
        middle_summary_layout.addWidget(QLabel("Samples per PWM"), 4, 0)
        middle_summary_layout.addWidget(self.samples_per_pwm_combo, 4, 1)
        middle_summary_layout.addWidget(QLabel("PWM Selection"), 5, 0)
        middle_summary_layout.addWidget(self.pwm_selection_combo, 5, 1)
        middle_summary_layout.setColumnStretch(1, 1)

        button_column = QVBoxLayout()
        button_column.setContentsMargins(0, 0, 0, 0)
        button_column.setSpacing(6)
        button_column.addStretch(1)

        self.start_button = QPushButton("Start Sampling")
        self.start_button.setProperty("tone", "primary")
        self.start_button.clicked.connect(lambda: self.start_requested.emit())
        button_column.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop Sampling")
        self.stop_button.setProperty("tone", "danger")
        self.stop_button.clicked.connect(lambda: self.stop_requested.emit())
        self.stop_button.setEnabled(False)
        button_column.addWidget(self.stop_button)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.hide)
        button_column.addWidget(self.close_button)

        summary_row.addWidget(left_summary, 1)
        summary_row.addWidget(middle_summary, 1)
        summary_row.addLayout(button_column)
        summary_body.addLayout(summary_row)
        root_layout.addWidget(summary_frame)

        measurement_row = QHBoxLayout()
        measurement_row.setContentsMargins(0, 0, 0, 0)
        measurement_row.setSpacing(10)

        progress_frame, progress_body = self._build_card("Sampling Progress")
        progress_grid = QGridLayout()
        progress_grid.setContentsMargins(0, 0, 0, 0)
        progress_grid.setHorizontalSpacing(8)
        progress_grid.setVerticalSpacing(6)

        self.current_pwm_value = self._make_value_label("-")
        self.current_direction_value = self._make_value_label("Setup")
        self.current_sample_value = self._make_value_label("Setup / 32")
        self.completed_count_value = self._make_value_label("0 / 320")

        progress_grid.addWidget(QLabel("Current PWM"), 0, 0)
        progress_grid.addWidget(self.current_pwm_value, 0, 1)
        progress_grid.addWidget(QLabel("Current Direction"), 0, 2)
        progress_grid.addWidget(self.current_direction_value, 0, 3)
        progress_grid.addWidget(QLabel("Sample Index"), 1, 0)
        progress_grid.addWidget(self.current_sample_value, 1, 1)
        progress_grid.addWidget(QLabel("Completed Movements"), 1, 2)
        progress_grid.addWidget(self.completed_count_value, 1, 3)
        progress_grid.setColumnStretch(1, 1)
        progress_grid.setColumnStretch(3, 1)
        progress_body.addLayout(progress_grid)

        last_sample_frame, last_sample_body = self._build_card("Last Sample")
        last_sample_grid = QGridLayout()
        last_sample_grid.setContentsMargins(0, 0, 0, 0)
        last_sample_grid.setHorizontalSpacing(8)
        last_sample_grid.setVerticalSpacing(6)

        self.latest_range_value = self._make_value_label("-")
        self.latest_time_value = self._make_value_label("-")
        self.latest_speed_value = self._make_value_label("-")
        self.latest_cell_value = self._make_value_label("-")

        last_sample_grid.addWidget(QLabel("Latest Range"), 0, 0)
        last_sample_grid.addWidget(self.latest_range_value, 0, 1)
        last_sample_grid.addWidget(QLabel("Latest Time"), 0, 2)
        last_sample_grid.addWidget(self.latest_time_value, 0, 3)
        last_sample_grid.addWidget(QLabel("Latest Speed"), 1, 0)
        last_sample_grid.addWidget(self.latest_speed_value, 1, 1)
        last_sample_grid.setColumnStretch(1, 1)
        last_sample_grid.setColumnStretch(3, 1)
        last_sample_body.addLayout(last_sample_grid)

        measurement_row.addWidget(progress_frame, 1)
        measurement_row.addWidget(last_sample_frame, 1)
        root_layout.addLayout(measurement_row)

        logs_row = QHBoxLayout()
        logs_row.setContentsMargins(0, 0, 0, 0)
        logs_row.setSpacing(10)

        logs_header_row = QHBoxLayout()
        logs_header_row.setContentsMargins(0, 0, 0, 0)
        logs_header_row.addStretch(1)

        self.clear_logs_button = QPushButton("Clear Logs")
        self.clear_logs_button.setProperty("tone", "secondary")
        self.clear_logs_button.setMinimumWidth(120)
        self.clear_logs_button.clicked.connect(self.clear_logs)
        logs_header_row.addWidget(self.clear_logs_button)
        root_layout.addLayout(logs_header_row)

        operator_frame, operator_body = self._build_card("Operator Log")
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setObjectName("SamplingOperatorLog")
        self.log_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.log_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_output.setMinimumHeight(120)
        operator_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        operator_body.addWidget(self.log_output, 1)

        packet_frame, packet_body = self._build_card("Packet Log")
        self.packet_log_output = QTextEdit()
        self.packet_log_output.setReadOnly(True)
        self.packet_log_output.setObjectName("SamplingPacketLog")
        self.packet_log_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.packet_log_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.packet_log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.packet_log_output.setMinimumHeight(120)
        packet_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        packet_body.addWidget(self.packet_log_output, 1)

        logs_row.addWidget(operator_frame, 1)
        logs_row.addWidget(packet_frame, 1)
        root_layout.addLayout(logs_row, 1)

        self.reset_flags()

    # Public API used by controller/state-machine integration
    def append_log(self, message: str, *, level: str = "info") -> None:
        self.append_operator_log(message, level=level)

    def append_operator_log(self, message: str, *, level: str = "info") -> None:
        _ = level
        self._append_timestamped_line(self.log_output, message)

    def append_packet_log(self, message: str, *, level: str = "info") -> None:
        _ = level
        self._append_timestamped_line(self.packet_log_output, message)

    def update_position(self, value: object) -> None:
        if hasattr(self, "position_field"):
            self.position_field.setText(str(value))

    def update_range(self, value: object) -> None:
        if hasattr(self, "range_field"):
            self.range_field.setText(str(value))

    def set_left_flag_active(self, active: bool) -> None:
        self._set_led_state(None, active)

    def set_right_flag_active(self, active: bool) -> None:
        self._set_led_state(None, active)

    def reset_flags(self) -> None:
        self.set_left_flag_active(False)
        self.set_right_flag_active(False)

    def set_context(self, node_id: int | None, node_name: str | None, sheet_name: str | None) -> None:
        self._selected_node_id = "-" if node_id is None else str(int(node_id))
        self._selected_node_name = "-" if not node_name else str(node_name)
        self._sampling_sheet_name = sheet_name or "-"
        self.selected_node_value.setText(f"Node {self._selected_node_id} - {self._selected_node_name}")
        self.sampling_sheet_value.setText(self._sampling_sheet_name)

    def prepare_for_run(self, *, total_samples: int, total_measurements: int) -> None:
        self._current_total_samples = int(total_samples)
        self.set_state_text("HOME_WAIT_RUN_ACK")
        self.set_status_text("Sampling started")
        self.set_final_status("RUNNING")
        self.set_reason_text("-", tone="neutral")
        self.set_current_pwm("-")
        self.set_current_direction("Setup")
        self.set_current_sample("Setup")
        self.set_completed_counts(0, int(total_measurements))
        self.set_latest_measurement("-")
        self.set_latest_workbook_cell("-")
        self.set_start_available(False, "Sampling is already running.")
        self.set_stop_available(True)
        self.set_sampling_configuration_enabled(False)

    def set_state_text(self, text: str) -> None:
        self.state_value.setText(str(text))

    def set_status_text(self, text: str) -> None:
        self.status_value.setText(str(text))
        self._apply_status_style(self.status_value, text)

    def set_final_status(self, text: str) -> None:
        self.final_status_value.setText(str(text))
        self._apply_status_style(self.final_status_value, text)

    def set_reason_text(self, text: str, *, tone: str = "neutral") -> None:
        self.reason_value.setText(text or "-")
        self._apply_tone_style(self.reason_value, tone)

    def set_current_pwm(self, pwm: object) -> None:
        self.current_pwm_value.setText(str(pwm))

    def set_current_direction(self, direction: object) -> None:
        value = str(direction)
        normalized = value.strip().upper()
        if normalized in {"HOME", "SETUP"}:
            display = "Setup"
        elif normalized in {"+", "POS", "POSITIVE"}:
            display = "Positive"
        elif normalized in {"-", "NEG", "NEGATIVE"}:
            display = "Negative"
        else:
            display = value
        self.current_direction_value.setText(display)

    def set_current_sample(self, sample_index: object, total_samples: int | None = None) -> None:
        total = int(total_samples) if isinstance(total_samples, int) and total_samples > 0 else self._current_total_samples
        if isinstance(sample_index, int) and sample_index > 0:
            value = f"Sample {int(sample_index)} / {total}"
        else:
            value = f"Setup / {total}"
        self.current_sample_value.setText(value)

    def set_completed_counts(self, completed: int, total: int) -> None:
        self.completed_count_value.setText(f"{int(completed)} / {int(total)}")

    def set_latest_measurement(self, value: object) -> None:
        if isinstance(value, tuple) and len(value) == 3:
            range_value, elapsed_seconds, speed = value
            self.set_latest_measurement_details(range_value, elapsed_seconds, speed)
        else:
            self.latest_range_value.setText(str(value))
            self.latest_time_value.setText(str(value))
            self.latest_speed_value.setText(str(value))

    def set_latest_measurement_details(self, range_value: object, elapsed_seconds: object, speed: object) -> None:
        self.latest_range_value.setText(f"{int(range_value)} counts")
        self.latest_time_value.setText(f"{float(elapsed_seconds):.3f} s")
        self.latest_speed_value.setText(f"{float(speed):.2f} counts/s")

    def set_latest_workbook_cell(self, cell_ref: str) -> None:
        self.latest_cell_value.setText(cell_ref or "-")

    def set_failure_details(
        self,
        *,
        pwm: object,
        direction: object,
        sample_index: object,
        reason: str,
        completed_count: int,
        total_count: int,
    ) -> None:
        _ = (pwm, direction, sample_index, completed_count, total_count)
        self.set_reason_text(reason, tone="red")
        self.set_final_status("FAILED")

    def set_aborted_details(
        self,
        *,
        pwm: object,
        direction: object,
        sample_index: object,
        reason: str,
        completed_count: int,
        total_count: int,
    ) -> None:
        _ = (pwm, direction, sample_index, completed_count, total_count)
        self.set_reason_text(reason, tone="orange")
        self.set_final_status("ABORTED")

    def clear_failure_details(self) -> None:
        self.set_reason_text("-", tone="neutral")

    def clear_logs(self) -> None:
        self.log_output.clear()
        self.packet_log_output.clear()

    def selected_pwm_values(self) -> tuple[int, ...]:
        selection = self.pwm_selection_combo.currentText().strip()
        if selection == "All":
            return (100, 90, 80, 70, 60)
        return (int(selection),)

    def selected_samples_per_pwm(self) -> int:
        return int(self.samples_per_pwm_combo.currentText())

    def set_sampling_configuration_enabled(self, enabled: bool) -> None:
        self.samples_per_pwm_combo.setEnabled(bool(enabled))
        self.pwm_selection_combo.setEnabled(bool(enabled))

    def set_start_available(self, enabled: bool, reason: str = "") -> None:
        self._start_available = bool(enabled)
        self.start_button.setEnabled(bool(enabled))
        self.start_button.setToolTip(
            "Start Sampling after Single Axis passes."
            if enabled
            else (reason or "Sampling is available after Single Axis passes.")
        )

    def set_stop_available(self, enabled: bool) -> None:
        self._stop_available = bool(enabled)
        self.stop_button.setEnabled(bool(enabled))

    def set_selected_context_text(self, text: str) -> None:
        self.selected_node_value.setText(text)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.hide()
        event.ignore()

    @staticmethod
    def _make_value_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("DetailValue")
        label.setWordWrap(True)
        return label

    @staticmethod
    def _build_card(title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("SamplingCard")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(8, 6, 8, 8)
        frame_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        frame_layout.addWidget(title_label)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        body_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        frame_layout.addLayout(body_layout)
        return frame, body_layout

    @staticmethod
    def _set_led_state(_widget: object, _active: bool) -> None:
        _ = (_widget, _active)

    @staticmethod
    def _append_timestamped_line(target: QTextEdit, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        target.append(f"[{timestamp}] {message}")
        scrollbar = target.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _apply_status_style(self, label: QLabel, text: str) -> None:
        self._apply_tone_style(label, self._status_tone(text))

    @staticmethod
    def _status_tone(text: str) -> str:
        normalized = str(text).strip().lower()
        if not normalized or normalized in {"-", "idle", "ready"}:
            return "neutral"
        if "failed" in normalized or normalized == "fail":
            return "red"
        if "aborted" in normalized:
            return "orange"
        if "complete" in normalized or "passed" in normalized or normalized == "pass":
            return "green"
        if "running" in normalized or "started" in normalized or "testing" in normalized:
            return "blue"
        return "neutral"

    @staticmethod
    def _apply_tone_style(label: QLabel, tone: str) -> None:
        colors = {
            "neutral": "#374151",
            "blue": "#2563eb",
            "green": "#15803d",
            "red": "#dc2626",
            "orange": "#d97706",
        }
        color = colors.get(tone, colors["neutral"])
        label.setStyleSheet(f"color: {color}; font-weight: 600;")
