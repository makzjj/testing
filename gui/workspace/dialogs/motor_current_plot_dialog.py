"""Live Motor Current plot dialog with bounded polling."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from data.binary_cmd_builders import build_motor_current_log_rate_payload, build_position_log_rate_payload
from ..bridges import WorkspaceRuntimeBridge


class MotorCurrentPlotDialog(QDialog):
    """Render runtime-backed motor current samples while owning polling lifecycle only."""

    DEFAULT_RENDER_INTERVAL_MS = 200
    DEFAULT_LOG_RATE_HZ = 10
    DISPLAY_WINDOW_SAMPLES = 1000
    DEFAULT_X_MAX = 50
    DEFAULT_Y_MIN = -50
    DEFAULT_Y_MAX = 1200
    MIN_VISIBLE_Y_SPAN = 200

    def __init__(
        self,
        bridge: WorkspaceRuntimeBridge,
        *,
        node_provider: Callable[[], tuple[int | None, str]],
        send_query: Callable[[int, list[int]], None],
        query_payload_builder: Callable[[], list[int]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Motor Current Plot")
        self.setModal(False)
        self.resize(960, 620)

        self._bridge = bridge
        self._node_provider = node_provider
        self._send_query = send_query
        self._query_payload_builder = query_payload_builder
        self._polling_active = False
        self._display_min_index = 0
        self._display_start_index = 0
        self._display_node_id: int | None = None
        self._selected_node_id: int | None = None
        self._cleanup_sent_for_stop = False
        self._window_start_offset = 0
        self._stopped_session_sample_count: int | None = None
        self._debug_state: dict[str, object] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel("Motor Current Plot")
        title_label.setObjectName("PanelTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        root.addLayout(header_row)

        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(16)

        self.selected_node_label = QLabel("Selected Node")
        self.selected_node_label.setObjectName("DetailValue")
        summary_row.addWidget(self.selected_node_label, 0)

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("MotorCurrentNodeCombo")
        self.node_combo.currentIndexChanged.connect(self._handle_node_selection_changed)
        summary_row.addWidget(self.node_combo, 1)

        self.latest_current_label = QLabel("Latest Current: Unknown")
        self.latest_current_label.setObjectName("DetailValue")
        summary_row.addWidget(self.latest_current_label, 1)
        root.addLayout(summary_row)

        self._figure = Figure(figsize=(7.5, 4.2))
        self._figure.patch.set_facecolor("#dbeefc")
        self._axes = self._figure.add_subplot(111)
        self._axes.set_facecolor("#dbeefc")
        self._line, = self._axes.plot([], [], color="#c62828", linewidth=2)
        self._axes.set_title("Motor Current")
        self._axes.set_xlabel("Samples")
        self._axes.set_ylabel("mA")
        self._axes.grid(True, linestyle="--", alpha=0.45)
        self._canvas = FigureCanvas(self._figure)
        root.addWidget(self._canvas, 1)

        window_row = QHBoxLayout()
        window_row.setContentsMargins(0, 0, 0, 0)
        window_row.setSpacing(8)

        self.window_label = QLabel("Window: latest")
        self.window_label.setObjectName("DetailValue")
        window_row.addWidget(self.window_label, 0)

        self.window_slider = QSlider(Qt.Orientation.Horizontal)
        self.window_slider.setObjectName("MotorCurrentWindowSlider")
        self.window_slider.setMinimumHeight(24)
        self.window_slider.setEnabled(False)
        self.window_slider.valueChanged.connect(self._handle_window_slider_changed)
        window_row.addWidget(self.window_slider, 1)
        root.addLayout(window_row)

        control_row = QHBoxLayout()
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(8)

        self.start_button = QPushButton("Start")
        self.start_button.setProperty("tone", "primary")
        self.start_button.clicked.connect(self._handle_start_clicked)
        control_row.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.setProperty("tone", "danger")
        self.stop_button.clicked.connect(self._handle_stop_clicked)
        self.stop_button.setEnabled(False)
        control_row.addWidget(self.stop_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("tone", "secondary")
        self.clear_button.clicked.connect(self._handle_clear_clicked)
        control_row.addWidget(self.clear_button)

        control_row.addStretch(1)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)
        control_row.addWidget(self.close_button)
        root.addLayout(control_row)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setObjectName("DetailValue")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(self.DEFAULT_RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._handle_render_tick)

        self.sync_selected_node_from_provider()
        self.refresh_display()

    def showEvent(self, event) -> None:  # noqa: N802
        self.sync_selected_node_from_provider()
        self.refresh_display()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_polling("Status: Polling stopped.")
        super().closeEvent(event)

    def sync_selected_node_from_provider(self) -> None:
        preferred_node_id, preferred_label = self._node_provider()
        self._reload_node_options(preferred_node_id=preferred_node_id, preferred_label=preferred_label)
        self._selected_node_id, _ = self._current_node_context()

    def refresh_display(self) -> None:
        node_id, _node_label = self._current_node_context()
        if node_id != self._display_node_id:
            self._display_node_id = node_id
            self._reset_display_session(node_id, baseline_to_next_sample=False)
        self._refresh_latest_current_label(node_id)
        self._refresh_plot(node_id)

    def _handle_start_clicked(self) -> None:
        if self._polling_active:
            self.status_label.setText("Status: Polling already active.")
            return

        node_id, node_label = self._current_node_context()
        if node_id is None:
            self.status_label.setText("Status: No selected node available for motor-current polling.")
            return

        serial_connected, _mcu_connected = self._bridge.get_runtime_connection_state(create_if_missing=False)
        if not serial_connected:
            self.status_label.setText("Status: Runtime transport is not connected.")
            return

        self._reset_display_session(node_id, baseline_to_next_sample=True)
        self._cleanup_sent_for_stop = False
        self._stopped_session_sample_count = None
        self._polling_active = True
        self._render_timer.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        try:
            self._send_query(int(node_id), build_motor_current_log_rate_payload(self.DEFAULT_LOG_RATE_HZ))
        except Exception as exc:
            self._polling_active = False
            self._render_timer.stop()
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText(f"Status: Unable to start motor-current logging: {exc}")
            return
        self.status_label.setText(
            f"Status: Streaming {self._format_selected_node_text(node_id, node_label)} at {self.DEFAULT_LOG_RATE_HZ} Hz."
        )
        self.refresh_display()

    def _handle_stop_clicked(self) -> None:
        self._stop_polling("Status: Polling stopped by user.")

    def _handle_clear_clicked(self) -> None:
        node_id, _node_label = self._current_node_context()
        if node_id is None:
            self._display_min_index = 0
            self._display_start_index = 0
            self._window_start_offset = 0
            self._clear_plot()
            self._update_window_controls(0, 0, 0)
            self.status_label.setText("Status: Plot display cleared.")
            return

        self._reset_display_session(node_id, baseline_to_next_sample=True)
        self._clear_plot()
        self._update_window_controls(0, 0, 0)
        suffix = " Polling remains active." if self._polling_active else ""
        self.status_label.setText(f"Status: Plot display cleared.{suffix}")
        self._refresh_latest_current_label(node_id)

    def _handle_render_tick(self) -> None:
        if not self._polling_active:
            return

        node_id, node_label = self._current_node_context()
        if node_id is None:
            self._stop_polling("Status: Polling stopped because no selected node is available.")
            return

        serial_connected, _mcu_connected = self._bridge.get_runtime_connection_state(create_if_missing=False)
        if not serial_connected:
            self._stop_polling("Status: Polling stopped because runtime transport disconnected.")
            return

        self._refresh_latest_current_label(node_id)
        self._refresh_plot(node_id)

    def _handle_node_selection_changed(self) -> None:
        previous_node_id = self._selected_node_id
        node_id, node_label = self._current_node_context()
        if self._polling_active and previous_node_id != node_id:
            try:
                if previous_node_id is not None:
                    self._send_logging_disable(int(previous_node_id))
            except Exception:
                pass
            self._reset_display_session(node_id, baseline_to_next_sample=True)
            self._cleanup_sent_for_stop = False
            self._stopped_session_sample_count = None
            self._selected_node_id = node_id
            self._display_node_id = node_id
            if node_id is not None:
                try:
                    self._send_query(int(node_id), build_motor_current_log_rate_payload(self.DEFAULT_LOG_RATE_HZ))
                except Exception as exc:
                    self._stop_polling(f"Status: Polling stopped because MOTOR_I logging start failed: {exc}")
                    return
            self.status_label.setText(
                f"Status: Streaming {self._format_selected_node_text(node_id, node_label)} at {self.DEFAULT_LOG_RATE_HZ} Hz."
            )
            self.refresh_display()
            return
        self._selected_node_id = node_id
        self._display_node_id = node_id
        self._reset_display_session(node_id, baseline_to_next_sample=False)
        self.status_label.setText(f"Status: Viewing {self._format_selected_node_text(node_id, node_label)}.")
        self.refresh_display()

    def _refresh_latest_current_label(self, node_id: int | None) -> None:
        if node_id is None:
            self.latest_current_label.setText("Latest Current: Unknown")
            return

        latest = self._bridge.get_runtime_node_motor_current(node_id, create_if_missing=False)
        current_mA = latest.get("current_mA")
        current_A = latest.get("current_A")
        if current_mA is None or current_A is None:
            self.latest_current_label.setText("Latest Current: Unknown")
            return
        self.latest_current_label.setText(f"Latest Current: {int(current_mA)} mA / {float(current_A):.3f} A")

    def _refresh_plot(self, node_id: int | None) -> None:
        if node_id is None:
            self._clear_plot()
            self._update_window_controls(0, 0, 0)
            return

        session_samples = self._session_samples(node_id)
        total_session_samples = len(session_samples)
        if not session_samples:
            self._clear_plot()
            self._update_window_controls(0, 0, 0)
            return

        visible_samples, window_start_offset = self._visible_window_samples(session_samples)
        visible_count = len(visible_samples)
        self._window_start_offset = window_start_offset
        x_values = list(range(visible_count))
        y_values = [int(sample["current_mA"]) for sample in visible_samples]
        self._line.set_data(x_values, y_values)
        self._apply_plot_bounds(x_values, y_values)
        self._update_window_controls(total_session_samples, window_start_offset, visible_count)
        self._update_debug_state(total_session_samples, x_values, y_values)
        self._canvas.draw_idle()

    def _clear_plot(self) -> None:
        self._line.set_data([], [])
        self._axes.set_xlim(0, self.DEFAULT_X_MAX)
        self._axes.set_ylim(self.DEFAULT_Y_MIN, self.DEFAULT_Y_MAX)
        self._canvas.draw_idle()

    def _stop_polling(self, status_text: str) -> None:
        node_id, _node_label = self._current_node_context()
        should_send_disable = self._polling_active or self._render_timer.isActive()
        if node_id is not None:
            total_session_samples = len(self._session_samples(int(node_id)))
            self._stopped_session_sample_count = total_session_samples
            self._window_start_offset = max(0, total_session_samples - self.DISPLAY_WINDOW_SAMPLES)
        self._polling_active = False
        self._render_timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText(status_text)
        if should_send_disable and node_id is not None and not self._cleanup_sent_for_stop:
            try:
                # Nodes may continue unsolicited CF/GETPOS streaming if LOGMOTOR_I was enabled earlier.
                # Position logging can also remain active independently, so stop both.
                self._send_logging_disable(int(node_id))
                self._cleanup_sent_for_stop = True
            except Exception:
                pass
        self.refresh_display()

    def _send_logging_disable(self, node_id: int) -> None:
        self._send_query(int(node_id), build_motor_current_log_rate_payload(0))
        self._send_query(int(node_id), build_position_log_rate_payload(0))

    def _reset_display_session(self, node_id: int | None, *, baseline_to_next_sample: bool) -> None:
        self._window_start_offset = 0
        self._stopped_session_sample_count = None
        self.window_slider.blockSignals(True)
        self.window_slider.setValue(0)
        self.window_slider.blockSignals(False)
        if node_id is None:
            self._display_min_index = 0
            self._display_start_index = 0
            return
        series = self._bridge.get_runtime_node_motor_current_series(node_id, create_if_missing=False)
        if baseline_to_next_sample and series:
            next_index = int(series[-1]["index"]) + 1
            self._display_min_index = next_index
            self._display_start_index = next_index
            return
        self._display_min_index = 0
        self._display_start_index = 0

    def _reload_node_options(
        self,
        preferred_node_id: int | None = None,
        preferred_label: str | None = None,
    ) -> None:
        current_node_id, current_label = self._current_node_context()
        target_node_id = preferred_node_id if preferred_node_id is not None else current_node_id
        target_label = preferred_label if preferred_node_id is not None else current_label
        options = self._bridge.get_plot_node_options(create_if_missing=False)

        self.node_combo.blockSignals(True)
        self.node_combo.clear()
        for node_id, node_label in options:
            self.node_combo.addItem(self._format_selected_node_text(int(node_id), str(node_label)), (int(node_id), str(node_label)))
        if self.node_combo.count() == 0:
            self.node_combo.addItem("Unknown", (None, "Unknown"))

        if target_node_id is not None:
            for index in range(self.node_combo.count()):
                data = self.node_combo.itemData(index)
                if isinstance(data, tuple) and len(data) == 2 and data[0] == int(target_node_id):
                    self.node_combo.setCurrentIndex(index)
                    break
        elif target_label:
            for index in range(self.node_combo.count()):
                data = self.node_combo.itemData(index)
                if isinstance(data, tuple) and len(data) == 2 and str(data[1]) == str(target_label):
                    self.node_combo.setCurrentIndex(index)
                    break
        self.node_combo.blockSignals(False)

    def _current_node_context(self) -> tuple[int | None, str]:
        data = self.node_combo.currentData()
        if not isinstance(data, tuple) or len(data) != 2:
            return None, "Unknown"
        node_id, node_label = data
        if node_id is None:
            return None, str(node_label)
        return int(node_id), str(node_label)

    def _apply_plot_bounds(self, x_values: list[int], y_values: list[int]) -> None:
        if not x_values or not y_values:
            self._axes.set_xlim(0, self.DEFAULT_X_MAX)
            self._axes.set_ylim(self.DEFAULT_Y_MIN, self.DEFAULT_Y_MAX)
            return

        x_max = max(self.DEFAULT_X_MAX, max(x_values) + 1)
        self._axes.set_xlim(0, x_max)

        minimum = float(min(y_values))
        maximum = float(max(y_values))
        lower = minimum - 25.0
        upper = maximum + 25.0
        if (upper - lower) < float(self.MIN_VISIBLE_Y_SPAN):
            midpoint = (upper + lower) / 2.0
            half_span = float(self.MIN_VISIBLE_Y_SPAN) / 2.0
            lower = midpoint - half_span
            upper = midpoint + half_span
        self._axes.set_ylim(lower, upper)

    def _handle_window_slider_changed(self, value: int) -> None:
        if self._polling_active:
            return
        self._window_start_offset = max(0, int(value))
        node_id, _node_label = self._current_node_context()
        self._refresh_latest_current_label(node_id)
        self._refresh_plot(node_id)

    def _session_samples(self, node_id: int) -> list[dict[str, object]]:
        series = self._bridge.get_runtime_node_motor_current_series(node_id, create_if_missing=False)
        session_samples = [sample for sample in series if int(sample.get("index", 0)) >= self._display_min_index]
        if not self._polling_active and self._stopped_session_sample_count is not None:
            return session_samples[: max(0, int(self._stopped_session_sample_count))]
        return session_samples

    def _visible_window_samples(self, session_samples: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
        total = len(session_samples)
        if total <= self.DISPLAY_WINDOW_SAMPLES:
            return session_samples, 0

        if self._polling_active:
            start_offset = total - self.DISPLAY_WINDOW_SAMPLES
        else:
            max_start = total - self.DISPLAY_WINDOW_SAMPLES
            start_offset = max(0, min(int(self._window_start_offset), max_start))
        end_offset = start_offset + self.DISPLAY_WINDOW_SAMPLES
        return session_samples[start_offset:end_offset], start_offset

    def _update_window_controls(self, total_session_samples: int, window_start_offset: int, visible_count: int) -> None:
        if self._polling_active:
            self.window_slider.blockSignals(True)
            self.window_slider.setEnabled(False)
            self.window_slider.setRange(0, max(0, total_session_samples - self.DISPLAY_WINDOW_SAMPLES))
            self.window_slider.setValue(max(0, total_session_samples - self.DISPLAY_WINDOW_SAMPLES))
            self.window_slider.blockSignals(False)
            self.window_label.setText("Window: latest")
            return

        max_start = max(0, total_session_samples - self.DISPLAY_WINDOW_SAMPLES)
        self.window_slider.blockSignals(True)
        self.window_slider.setRange(0, max_start)
        self.window_slider.setValue(max(0, min(window_start_offset, max_start)))
        self.window_slider.setEnabled(max_start > 0)
        self.window_slider.blockSignals(False)
        if visible_count <= 0:
            self.window_label.setText("Window: all samples")
        elif max_start <= 0:
            self.window_label.setText("Window: all samples")
        else:
            self.window_label.setText(
                f"Window: {window_start_offset}-{window_start_offset + visible_count - 1} of {total_session_samples}"
            )

    def _update_debug_state(self, session_sample_count: int, x_values: list[int], y_values: list[int]) -> None:
        self._debug_state = {
            "session_sample_count": int(session_sample_count),
            "display_window_samples": int(self.DISPLAY_WINDOW_SAMPLES),
            "slider_enabled": bool(self.window_slider.isEnabled()),
            "slider_min": int(self.window_slider.minimum()),
            "slider_max": int(self.window_slider.maximum()),
            "slider_value": int(self.window_slider.value()),
            "stopped_review_start": int(self._window_start_offset),
            "is_streaming": bool(self._polling_active),
            "plot_x_first": None if not x_values else int(x_values[0]),
            "plot_x_last": None if not x_values else int(x_values[-1]),
            "plot_y_first": None if not y_values else int(y_values[0]),
            "plot_y_last": None if not y_values else int(y_values[-1]),
        }

    @staticmethod
    def _format_selected_node_text(node_id: int | None, node_label: str) -> str:
        if node_id is None:
            return "Unknown"
        label = str(node_label).strip() or "-"
        if label.lower() == f"node {int(node_id)}".lower():
            return f"Node {int(node_id)}"
        return f"Node {int(node_id)} - {label}"
