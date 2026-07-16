"""Live Sampling error plot dialog driven by completed controller results."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from math import isclose

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from ..controllers.sampling_test_controller import SamplingMeasurementResult


class SamplingErrorPlotDialog(QDialog):
    """Render completed Sampling error results without owning canonical history."""

    def __init__(
        self,
        *,
        results_provider: Callable[[], tuple[SamplingMeasurementResult, ...]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sampling Error Plot")
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(960, 620)

        self._results_provider = results_provider
        self._rendered_results: tuple[SamplingMeasurementResult, ...] = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel("Sampling Error Plot")
        title_label.setObjectName("PanelTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        root.addLayout(header_row)

        self.latest_error_label = QLabel("Latest Error: —")
        self.latest_error_label.setObjectName("DetailValue")
        root.addWidget(self.latest_error_label)

        self._figure = Figure(figsize=(7.5, 4.2))
        self._figure.patch.set_facecolor("#fff3e0")
        self._axes = self._figure.add_subplot(111)
        self._axes.set_facecolor("#fff3e0")
        self._home_line, = self._axes.plot([], [], color="#ef6c00", linewidth=2, marker="o", label="Home")
        self._opposite_line, = self._axes.plot([], [], color="#fb8c00", linewidth=2, marker="o", label="Opposite")
        self._zero_line = self._axes.axhline(0.0, color="#616161", linestyle="--", linewidth=1.2)
        self._axes.set_title("Sampling Error")
        self._axes.set_xlabel("Measurement")
        self._axes.set_ylabel("Error (counts)")
        self._axes.grid(True, linestyle="--", alpha=0.35)
        self._canvas = FigureCanvas(self._figure)
        root.addWidget(self._canvas, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)
        controls.addWidget(self.close_button)
        root.addLayout(controls)

        self.status_label = QLabel("No completed error measurements yet")
        self.status_label.setObjectName("DetailValue")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.refresh_from_provider()

    def showEvent(self, event) -> None:  # noqa: N802
        self.refresh_from_provider()
        super().showEvent(event)

    def refresh_from_provider(self) -> None:
        self.set_results(self._results_provider())

    def set_results(self, results: Iterable[SamplingMeasurementResult]) -> None:
        self._rendered_results = tuple(results)
        self._refresh_plot()

    def _refresh_plot(self) -> None:
        if not self._rendered_results:
            self._home_line.set_data([], [])
            self._opposite_line.set_data([], [])
            self._axes.legend([], [], frameon=False)
            self._axes.set_xlim(0, 1)
            self._axes.set_ylim(-1, 1)
            self.latest_error_label.setText("Latest Error: —")
            self.status_label.setText("No completed error measurements yet")
            self._canvas.draw_idle()
            return

        home_x: list[int] = []
        home_y: list[float] = []
        opposite_x: list[int] = []
        opposite_y: list[float] = []
        all_values = [0.0]

        for measurement_index, result in enumerate(self._rendered_results, start=1):
            error_counts = float(result.error_counts or 0.0)
            all_values.append(error_counts)
            if result.return_error is None:
                opposite_x.append(measurement_index)
                opposite_y.append(error_counts)
            else:
                home_x.append(measurement_index)
                home_y.append(error_counts)

        self._home_line.set_data(home_x, home_y)
        self._opposite_line.set_data(opposite_x, opposite_y)
        self._apply_plot_bounds(len(self._rendered_results), all_values)

        if home_x or opposite_x:
            self._axes.legend(loc="upper right")
        else:
            self._axes.legend([], [], frameon=False)

        latest_result = self._rendered_results[-1]
        self.latest_error_label.setText(f"Latest Error: {self._format_error_text(latest_result)}")
        self.status_label.setText(f"Showing {len(self._rendered_results)} completed error measurement(s)")
        self._canvas.draw_idle()

    def _apply_plot_bounds(self, measurement_count: int, all_values: list[float]) -> None:
        if measurement_count <= 1:
            self._axes.set_xlim(0.5, 1.5)
        else:
            self._axes.set_xlim(1, measurement_count)

        y_min = min(all_values)
        y_max = max(all_values)
        span = y_max - y_min
        if isclose(span, 0.0):
            padding = max(1.0, abs(y_max) * 0.2, abs(y_min) * 0.2)
        else:
            padding = max(1.0, span * 0.15)
        self._axes.set_ylim(y_min - padding, y_max + padding)

    @staticmethod
    def _format_error_text(result: SamplingMeasurementResult) -> str:
        count_text = SamplingErrorPlotDialog._format_error_count_display(float(result.error_counts or 0.0))
        unit_text = SamplingErrorPlotDialog._format_error_unit_display(float(result.error_units or 0.0))
        return f"{count_text} counts / {unit_text} {result.error_unit or ''}".strip()

    @staticmethod
    def _format_error_count_display(value: float) -> str:
        rounded = int(round(float(value)))
        if rounded == 0:
            return "0"
        return f"{rounded:+d}"

    @staticmethod
    def _format_error_unit_display(value: float) -> str:
        rounded = round(float(value), 4)
        if rounded == 0:
            return "0.0000"
        return f"{rounded:+.4f}"
