from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QFrame

from gui.workspace.dialogs.sampling_test_popup import SamplingTestPopup
from gui.workspace.pages.production_page import ProductionPage
from services.node_motion_calibration_store import NodeMotionCalibrationStore


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []

    def is_connected(self) -> bool:
        return False


class _FakeRuntimeWindow:
    def __init__(self) -> None:
        self.backend_client = _FakeBackendClient()


class _FakeBridge:
    def __init__(self) -> None:
        self.runtime_window = _FakeRuntimeWindow()
        self.node_motion_calibration_store = NodeMotionCalibrationStore.load_default()

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self.runtime_window

    def get_runtime_communication_model(self, *, create_if_missing: bool = False) -> dict:
        _ = create_if_missing
        return {
            "connected": False,
            "ports": [],
            "selected_port": "",
            "baud_rates": ["115200"],
            "selected_baud": "115200",
        }

    def get_runtime_robot_nodes(self, *, create_if_missing: bool = False) -> dict:
        _ = create_if_missing
        return {"connected_nodes": [], "rows": []}

    def get_runtime_robot_power_state(self, *, create_if_missing: bool = False) -> bool | None:
        _ = create_if_missing
        return None


class SamplingErrorUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _title_label(self, popup: SamplingTestPopup, title: str) -> QLabel:
        for label in popup.findChildren(QLabel):
            if label.objectName() == "SectionTitle" and label.text() == title:
                return label
        raise AssertionError(f"Missing section title {title!r}")

    def _section_frame(self, popup: SamplingTestPopup, title: str) -> QFrame:
        title_label = self._title_label(popup, title)
        parent = title_label.parentWidget()
        assert isinstance(parent, QFrame)
        return parent

    def _child_label_texts(self, frame: QFrame) -> set[str]:
        return {label.text() for label in frame.findChildren(QLabel)}

    def test_sampling_popup_layout_groups_summary_progress_last_sample_and_logs(self) -> None:
        popup = SamplingTestPopup()
        popup.show()
        self._app.processEvents()

        titles = {
            label.text()
            for label in popup.findChildren(QLabel)
            if label.objectName() == "SectionTitle"
        }
        self.assertEqual(
            titles,
            {"Sampling Summary", "Sampling Progress", "Last Sample", "Operator Log", "Packet Log"},
        )

        summary_texts = self._child_label_texts(self._section_frame(popup, "Sampling Summary"))
        for text in ("Selected Node", "Sampling Sheet", "Status", "Reason", "Resume"):
            self.assertIn(text, summary_texts)
        for text in ("Range Mode", "Samples per PWM", "PWM Selection"):
            self.assertIn(text, summary_texts)
        for text in ("Current State", "Final Status", "Failure Context", "Current Status"):
            self.assertNotIn(text, summary_texts)

        button_texts = {button.text() for button in self._section_frame(popup, "Sampling Summary").findChildren(QPushButton)}
        self.assertEqual(button_texts, {"Start Sampling", "Resume Sampling", "Stop Sampling", "Close"})

        title_font = self._title_label(popup, "Sampling Summary").font()
        body_font = next(label.font() for label in popup.findChildren(QLabel) if label.text() == "Selected Node")
        self.assertTrue(title_font.bold())
        self.assertGreaterEqual(title_font.pointSize(), body_font.pointSize())

        self.assertLessEqual(popup.layout().sizeHint().width(), popup.width())
        self.assertTrue(popup.range_mode_combo.width() > 0)
        self.assertTrue(popup.samples_per_pwm_combo.width() > 0)
        self.assertTrue(popup.pwm_selection_combo.width() > 0)
        popup.close()

    def test_sampling_progress_and_last_sample_split_error_row_correctly(self) -> None:
        popup = SamplingTestPopup()
        popup.show()
        self._app.processEvents()

        progress_frame = self._section_frame(popup, "Sampling Progress")
        progress_texts = self._child_label_texts(progress_frame)
        self.assertEqual(
            progress_texts & {"Current PWM", "Current Direction", "Sample Index", "Completed Movements"},
            {"Current PWM", "Current Direction", "Sample Index", "Completed Movements"},
        )
        self.assertNotIn("Error Count", progress_texts)

        last_sample_frame = self._section_frame(popup, "Last Sample")
        last_sample_texts = self._child_label_texts(last_sample_frame)
        self.assertEqual(
            last_sample_texts & {"Latest Range", "Latest Time", "Latest Speed", "Error Count"},
            {"Latest Range", "Latest Time", "Latest Speed", "Error Count"},
        )
        self.assertIn(popup.error_plot_button, last_sample_frame.findChildren(QPushButton))
        self.assertNotIn(popup.error_plot_button, progress_frame.findChildren(QPushButton))

        popup.set_latest_error_result(SimpleNamespace(error_counts=32.6, error_units=0.0003747, error_unit="mm"))
        self.assertEqual(popup.latest_error_value.text(), "+33 counts / +0.0004 mm")
        popup.set_latest_error_result(SimpleNamespace(error_counts=-25.2, error_units=-0.0002839, error_unit="mm"))
        self.assertEqual(popup.latest_error_value.text(), "-25 counts / -0.0003 mm")
        popup.set_latest_error_result(SimpleNamespace(error_counts=0.0, error_units=0.0, error_unit="deg"))
        self.assertEqual(popup.latest_error_value.text(), "0 counts / 0.0000 deg")
        popup.close()

    def test_logs_remain_side_by_side_with_one_clear_logs_button_below(self) -> None:
        popup = SamplingTestPopup()
        popup.show()
        self._app.processEvents()

        operator_frame = self._section_frame(popup, "Operator Log")
        packet_frame = self._section_frame(popup, "Packet Log")

        all_clear_buttons = [button for button in popup.findChildren(QPushButton) if button.text() == "Clear Logs"]
        self.assertEqual(len(all_clear_buttons), 1)
        self.assertIs(all_clear_buttons[0], popup.clear_logs_button)

        operator_top_left = operator_frame.mapTo(popup, QPoint(0, 0))
        packet_top_left = packet_frame.mapTo(popup, QPoint(0, 0))
        clear_top_left = popup.clear_logs_button.mapTo(popup, QPoint(0, 0))

        self.assertLess(operator_top_left.x(), packet_top_left.x())
        lower_log_bottom = max(
            operator_top_left.y() + operator_frame.height(),
            packet_top_left.y() + packet_frame.height(),
        )
        self.assertGreaterEqual(clear_top_left.y(), lower_log_bottom)

        popup.append_operator_log("operator message")
        popup.append_packet_log("packet message")
        self.assertIn("operator message", popup.log_output.toPlainText())
        self.assertIn("packet message", popup.packet_log_output.toPlainText())
        popup.clear_logs_button.click()
        self.assertEqual(popup.log_output.toPlainText(), "")
        self.assertEqual(popup.packet_log_output.toPlainText(), "")
        popup.close()

    def test_error_plot_button_emits_request_signal_and_popup_source_stays_ui_only(self) -> None:
        popup = SamplingTestPopup()
        requested: list[str] = []
        popup.error_plot_requested.connect(lambda: requested.append("plot"))

        popup.error_plot_button.click()

        self.assertEqual(requested, ["plot"])

        source = Path("gui/workspace/dialogs/sampling_test_popup.py").read_text(encoding="utf-8")
        self.assertNotIn("ElementTree", source)
        self.assertNotIn("NodeMotionCalibrationStore", source)
        self.assertNotIn("node_motion_calibration.xml", source)
        self.assertNotIn("decode_command", source)
        self.assertNotIn("write_sampling_result", source)
        popup.close()

    def test_production_page_reuses_one_error_plot_dialog_and_clears_destroyed_reference(self) -> None:
        bridge = _FakeBridge()
        page = ProductionPage(bridge)
        popup = page._ensure_sampling_popup()

        popup.error_plot_button.click()
        self._app.processEvents()

        first_dialog = page._sampling_error_plot_dialog
        self.assertIsNotNone(first_dialog)
        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, [])
        self.assertFalse(page._sampling_controller.is_active())

        popup.error_plot_button.click()
        self._app.processEvents()

        self.assertIs(page._sampling_error_plot_dialog, first_dialog)
        assert first_dialog is not None
        first_dialog.close()
        self._app.processEvents()

        self.assertIsNone(page._sampling_error_plot_dialog)
