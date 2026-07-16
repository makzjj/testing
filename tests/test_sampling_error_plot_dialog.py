from __future__ import annotations

import os
import unittest
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from gui.workspace.controllers.sampling_test_controller import SamplingMeasurementResult
from gui.workspace.dialogs.sampling_error_plot_dialog import SamplingErrorPlotDialog


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _ResultsProvider:
    def __init__(self, results: tuple[SamplingMeasurementResult, ...] = ()) -> None:
        self.results = results

    def __call__(self) -> tuple[SamplingMeasurementResult, ...]:
        return self.results


class SamplingErrorPlotDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _result(
        *,
        sample_index: int,
        direction: str,
        error_counts: float,
        error_units: float,
        error_unit: str,
        return_error: int | None,
    ) -> SamplingMeasurementResult:
        return SamplingMeasurementResult(
            pwm=100,
            sample_index=sample_index,
            direction=direction,
            range_value=1000 + sample_index,
            elapsed_seconds=1.0,
            speed=100.0,
            start_l_pos=0,
            r_pos=100,
            l_pos=0 if return_error is not None else None,
            return_error=return_error,
            expected_range_counts=1000.0,
            error_counts=error_counts,
            error_units=error_units,
            error_unit=error_unit,
            workbook_cells={},
        )

    def test_no_data_state_renders_safely_without_timer_or_commands(self) -> None:
        provider = _ResultsProvider(())
        dialog = SamplingErrorPlotDialog(results_provider=provider)

        self.assertEqual(dialog.status_label.text(), "No completed error measurements yet")
        self.assertEqual(dialog.latest_error_label.text(), "Latest Error: —")
        self.assertEqual(list(dialog._home_line.get_xdata()), [])
        self.assertEqual(list(dialog._opposite_line.get_xdata()), [])
        self.assertEqual(dialog._axes.get_xlabel(), "Measurement")
        self.assertEqual(dialog._axes.get_ylabel(), "Error (counts)")
        self.assertEqual(dialog.findChildren(QTimer), [])
        dialog.close()

    def test_plot_uses_signed_error_counts_with_zero_line_and_home_opposite_series(self) -> None:
        results = (
            self._result(sample_index=1, direction="+", error_counts=33.4, error_units=0.00038, error_unit="mm", return_error=None),
            self._result(sample_index=1, direction="-", error_counts=-25.2, error_units=-0.00029, error_unit="mm", return_error=10),
            self._result(sample_index=2, direction="+", error_counts=0.0, error_units=0.0, error_unit="mm", return_error=None),
        )
        provider = _ResultsProvider(results)
        dialog = SamplingErrorPlotDialog(results_provider=provider)

        self.assertEqual(list(dialog._opposite_line.get_xdata()), [1, 3])
        self.assertEqual(list(dialog._home_line.get_xdata()), [2])
        self.assertEqual(list(dialog._opposite_line.get_ydata()), [33.4, 0.0])
        self.assertEqual(list(dialog._home_line.get_ydata()), [-25.2])
        self.assertTrue(all(value == 0.0 for value in dialog._zero_line.get_ydata()))
        self.assertEqual(dialog.latest_error_label.text(), "Latest Error: 0 counts / 0.0000 mm")
        self.assertEqual(dialog.status_label.text(), "Showing 3 completed error measurement(s)")
        dialog.close()

    def test_refresh_from_provider_updates_without_mutating_results(self) -> None:
        initial_results = (
            self._result(sample_index=1, direction="+", error_counts=42.0, error_units=0.0012, error_unit="deg", return_error=None),
        )
        provider = _ResultsProvider(initial_results)
        dialog = SamplingErrorPlotDialog(results_provider=provider)

        provider.results = initial_results + (
            self._result(sample_index=1, direction="-", error_counts=-17.0, error_units=-0.0005, error_unit="deg", return_error=4),
        )
        dialog.refresh_from_provider()

        self.assertEqual(initial_results[0].error_counts, 42.0)
        self.assertEqual(list(dialog._opposite_line.get_ydata()), [42.0])
        self.assertEqual(list(dialog._home_line.get_ydata()), [-17.0])
        self.assertEqual(dialog.latest_error_label.text(), "Latest Error: -17 counts / -0.0005 deg")
        dialog.close()

    def test_dialog_source_stays_ui_only(self) -> None:
        source = Path("gui/workspace/dialogs/sampling_error_plot_dialog.py").read_text(encoding="utf-8")

        self.assertNotIn("ElementTree", source)
        self.assertNotIn("NodeMotionCalibrationStore", source)
        self.assertNotIn("node_motion_calibration.xml", source)
        self.assertNotIn("decode_command", source)
        self.assertNotIn("write_sampling_result", source)
        self.assertNotIn("ErrorHistoryStore", source)
