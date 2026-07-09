from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from data.binary_cmd_builders import (
    build_motor_current_log_rate_payload,
    build_motor_current_query_payload,
    build_position_log_rate_payload,
)
from gui.workspace.dialogs.motor_current_plot_dialog import MotorCurrentPlotDialog


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient()


class _FakeBridge:
    def __init__(self) -> None:
        self.runtime_window = _FakeRuntimeWindow()
        self.series_by_node: dict[int, list[dict[str, object]]] = {}
        self.plot_nodes: list[tuple[int, str]] = [
            (3, "X"),
            (4, "Y"),
            (5, "V"),
            (6, "H"),
            (7, "NZ"),
            (8, "RZ"),
            (9, "PZ"),
            (10, "HMI"),
            (11, "NGActuator"),
            (12, "Z"),
        ]

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self.runtime_window

    def get_plot_node_options(self, *, create_if_missing: bool = False) -> list[tuple[int, str]]:
        return list(self.plot_nodes)

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        connected = self.runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_node_motor_current(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        series = self.series_by_node.get(int(node_id), [])
        if not series:
            return {"node_id": int(node_id), "current_mA": None, "current_A": None, "sample_count": 0, "last_updated": None}
        latest = series[-1]
        current_mA = int(latest["current_mA"])
        return {
            "node_id": int(node_id),
            "current_mA": current_mA,
            "current_A": current_mA / 1000.0,
            "sample_count": len(series),
            "last_updated": latest["index"],
        }

    def get_runtime_node_motor_current_series(self, node_id: int, *, create_if_missing: bool = False) -> list[dict[str, object]]:
        return [dict(sample) for sample in self.series_by_node.get(int(node_id), [])]


class MotorCurrentPlotDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_dialog_does_not_subscribe_to_packet_received(self) -> None:
        bridge = _FakeBridge()
        before = bridge.runtime_window.receivers(bridge.runtime_window.packet_received)

        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (8, "Rp"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        self.assertEqual(bridge.runtime_window.receivers(bridge.runtime_window.packet_received), before)
        dialog.close()

    def test_opening_dialog_does_not_send_commands_when_manual_start_is_required(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (3, "X"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )
        dialog.show()
        self._app.processEvents()

        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, [])
        self.assertFalse(dialog._render_timer.isActive())
        self.assertEqual(dialog.node_combo.currentText(), "Node 3 - X")
        dropdown_text = [dialog.node_combo.itemText(index) for index in range(dialog.node_combo.count())]
        self.assertEqual(
            dropdown_text,
            [
                "Node 3 - X",
                "Node 4 - Y",
                "Node 5 - V",
                "Node 6 - H",
                "Node 7 - NZ",
                "Node 8 - RZ",
                "Node 9 - PZ",
                "Node 10 - HMI",
                "Node 11 - NGActuator",
                "Node 12 - Z",
            ],
        )
        for forbidden in ("YA", "YB", "Nd", "RS", "RP", "RN", "Node 7 - Node 7", "Node 7 - -"):
            self.assertFalse(any(forbidden in text for text in dropdown_text))
        dialog.close()

    def test_start_without_selected_node_does_not_send(self) -> None:
        bridge = _FakeBridge()
        bridge.plot_nodes = []
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (None, "Unknown"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()

        self.assertFalse(dialog._render_timer.isActive())
        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, [])
        self.assertIn("No selected node available", dialog.status_label.text())
        dialog.close()

    def test_start_with_selected_node_starts_timer_and_tick_sends_query(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        self.assertTrue(dialog._render_timer.isActive())
        self.assertFalse(dialog.start_button.isEnabled())
        self.assertTrue(dialog.stop_button.isEnabled())
        self.assertEqual(
            bridge.runtime_window.backend_client.sent_commands,
            [(7, build_motor_current_log_rate_payload(10))],
        )

        dialog._handle_render_tick()
        self.assertEqual(
            bridge.runtime_window.backend_client.sent_commands,
            [(7, build_motor_current_log_rate_payload(10))],
        )
        dialog.close()

    def test_duplicate_start_does_not_create_duplicate_polling(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        dialog._handle_start_clicked()

        self.assertEqual(
            bridge.runtime_window.backend_client.sent_commands,
            [(7, build_motor_current_log_rate_payload(10))],
        )
        self.assertIn("already active", dialog.status_label.text())
        dialog.close()

    def test_stop_and_close_stop_polling(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (8, "Rp"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        self.assertTrue(dialog._render_timer.isActive())
        dialog.stop_button.click()
        self.assertFalse(dialog._render_timer.isActive())
        self.assertTrue(dialog.start_button.isEnabled())
        self.assertFalse(dialog.stop_button.isEnabled())
        sent_after_stop = list(bridge.runtime_window.backend_client.sent_commands)
        dialog._handle_render_tick()
        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, sent_after_stop)
        self.assertEqual(
            sent_after_stop,
            [
                (8, build_motor_current_log_rate_payload(10)),
                (8, build_motor_current_log_rate_payload(0)),
                (8, build_position_log_rate_payload(0)),
            ],
        )

        dialog.start_button.click()
        self.assertTrue(dialog._render_timer.isActive())
        dialog.close()
        self.assertFalse(dialog._render_timer.isActive())
        sent_after_close = list(bridge.runtime_window.backend_client.sent_commands)
        dialog._handle_render_tick()
        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, sent_after_close)

    def test_clear_does_not_mutate_runtime_canonical_series(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[8] = [
            {"index": 1, "current_mA": 100},
            {"index": 2, "current_mA": 200},
        ]
        original = [dict(sample) for sample in bridge.series_by_node[8]]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (8, "Rp"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()
        self.assertEqual(list(dialog._line.get_ydata()), [100, 200])
        dialog.clear_button.click()

        self.assertEqual(bridge.series_by_node[8], original)
        self.assertEqual(list(dialog._line.get_ydata()), [])
        dialog.close()

    def test_latest_current_label_renders_unknown_and_known_values(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()
        self.assertEqual(dialog.latest_current_label.text(), "Latest Current: Unknown")

        bridge.series_by_node[7] = [{"index": 1, "current_mA": 123}]
        dialog.refresh_display()
        self.assertEqual(dialog.latest_current_label.text(), "Latest Current: 123 mA / 0.123 A")
        dialog.close()

    def test_plot_reads_series_from_bridge_for_selected_node_only(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[3] = [
            {"index": 10, "current_mA": 120},
            {"index": 11, "current_mA": 150},
            {"index": 12, "current_mA": 180},
        ]
        bridge.series_by_node[7] = [
            {"index": 20, "current_mA": 400},
        ]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (3, "X"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()

        self.assertEqual(list(dialog._line.get_xdata()), [0, 1, 2])
        self.assertEqual(list(dialog._line.get_ydata()), [120, 150, 180])
        dialog.close()

    def test_start_resets_local_session_x_axis_to_zero(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[7] = [{"index": 100, "current_mA": 200}]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7].append({"index": 101, "current_mA": 240})
        dialog.refresh_display()

        self.assertEqual(list(dialog._line.get_xdata()), [0])
        self.assertEqual(list(dialog._line.get_ydata()), [240])
        dialog.close()

    def test_render_timer_does_not_send_commands(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        sent_after_start = list(bridge.runtime_window.backend_client.sent_commands)
        dialog._handle_render_tick()

        self.assertEqual(bridge.runtime_window.backend_client.sent_commands, sent_after_start)
        dialog.close()

    def test_node_mismatch_does_not_render_other_node_series_until_selected(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[7] = [{"index": 1, "current_mA": 250}]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (3, "X"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()
        self.assertEqual(list(dialog._line.get_xdata()), [])
        self.assertEqual(list(dialog._line.get_ydata()), [])

        dialog.node_combo.setCurrentIndex(4)
        self.assertEqual(dialog.node_combo.currentText(), "Node 7 - NZ")
        self.assertEqual(list(dialog._line.get_xdata()), [0])
        self.assertEqual(list(dialog._line.get_ydata()), [250])
        dialog.close()

    def test_plot_refresh_requests_canvas_redraw_when_series_changes(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[7] = [{"index": 1, "current_mA": 250}]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )
        redraws: list[str] = []
        dialog._canvas.draw_idle = lambda: redraws.append("draw")

        dialog.refresh_display()

        self.assertGreaterEqual(len(redraws), 1)
        self.assertEqual(list(dialog._line.get_xdata()), [0])
        self.assertEqual(list(dialog._line.get_ydata()), [250])
        dialog.close()

    def test_selected_node_change_resets_display_baseline(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[3] = [{"index": 1, "current_mA": 100}, {"index": 2, "current_mA": 110}]
        bridge.series_by_node[7] = [{"index": 1, "current_mA": 300}, {"index": 2, "current_mA": 320}]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (3, "X"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()
        dialog.clear_button.click()
        self.assertEqual(list(dialog._line.get_xdata()), [])
        dialog.node_combo.setCurrentIndex(4)

        self.assertEqual(list(dialog._line.get_xdata()), [0, 1])
        self.assertEqual(list(dialog._line.get_ydata()), [300, 320])
        dialog.close()

    def test_clear_resets_local_session_x_axis_for_future_samples(self) -> None:
        bridge = _FakeBridge()
        bridge.series_by_node[7] = [{"index": 10, "current_mA": 300}, {"index": 11, "current_mA": 320}]
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.refresh_display()
        dialog.clear_button.click()
        bridge.series_by_node[7].append({"index": 12, "current_mA": 350})
        dialog.refresh_display()

        self.assertEqual(list(dialog._line.get_xdata()), [0])
        self.assertEqual(list(dialog._line.get_ydata()), [350])
        dialog.close()

    def test_disconnect_detected_on_tick_stops_polling_without_sending(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.runtime_window.backend_client.connected = False
        dialog._handle_render_tick()

        self.assertFalse(dialog._render_timer.isActive())
        self.assertEqual(
            bridge.runtime_window.backend_client.sent_commands,
            [
                (7, build_motor_current_log_rate_payload(10)),
                (7, build_motor_current_log_rate_payload(0)),
                (7, build_position_log_rate_payload(0)),
            ],
        )
        self.assertIn("disconnected", dialog.status_label.text())
        dialog.close()

    def test_motor_current_polling_does_not_send_getpos(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        dialog._handle_render_tick()

        sent_payloads = [payload for _node_id, payload in bridge.runtime_window.backend_client.sent_commands]
        self.assertIn(build_motor_current_log_rate_payload(10), sent_payloads)
        self.assertNotIn([0x82], sent_payloads)
        self.assertNotIn([0x82, 0x3F], sent_payloads)
        self.assertNotIn([0xCF, 0x3F], sent_payloads)
        dialog.close()

    def test_node_change_while_polling_disables_old_and_new_node_logging(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (3, "X"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.runtime_window.backend_client.sent_commands.clear()

        dialog.node_combo.setCurrentIndex(4)

        self.assertEqual(
            bridge.runtime_window.backend_client.sent_commands,
            [
                (3, build_motor_current_log_rate_payload(0)),
                (3, build_position_log_rate_payload(0)),
                (7, build_motor_current_log_rate_payload(10)),
            ],
        )
        dialog.close()

    def test_running_state_shows_only_latest_display_window_samples(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 1201)]
        dialog.refresh_display()

        self.assertEqual(len(list(dialog._line.get_xdata())), dialog.DISPLAY_WINDOW_SAMPLES)
        self.assertEqual(list(dialog._line.get_xdata())[0], 0)
        self.assertEqual(list(dialog._line.get_xdata())[-1], dialog.DISPLAY_WINDOW_SAMPLES - 1)
        self.assertEqual(list(dialog._line.get_ydata())[0], 201)
        self.assertEqual(list(dialog._line.get_ydata())[-1], 1200)
        self.assertFalse(dialog.window_slider.isEnabled())
        dialog.close()

    def test_stopped_state_enables_slider_when_session_exceeds_display_window(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 1201)]
        dialog.stop_button.click()

        self.assertTrue(dialog.window_slider.isEnabled())
        self.assertEqual(dialog.window_slider.minimum(), 0)
        self.assertEqual(dialog.window_slider.maximum(), 200)
        self.assertEqual(dialog.window_slider.value(), 200)
        self.assertEqual(dialog._debug_state["session_sample_count"], 1200)
        self.assertEqual(dialog._debug_state["display_window_samples"], 1000)
        self.assertEqual(dialog._debug_state["slider_enabled"], True)
        self.assertEqual(dialog._debug_state["slider_min"], 0)
        self.assertEqual(dialog._debug_state["slider_max"], 200)
        self.assertEqual(dialog._debug_state["slider_value"], 200)
        self.assertEqual(dialog._debug_state["stopped_review_start"], 200)
        self.assertEqual(dialog.window_label.text(), "Window: 200-1199 of 1200")
        dialog.close()

    def test_slider_movement_displays_selected_sample_window_without_mutating_runtime(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 1201)]
        original = [dict(sample) for sample in bridge.series_by_node[7]]
        dialog.stop_button.click()
        dialog.window_slider.setValue(0)

        self.assertEqual(dialog._debug_state["stopped_review_start"], 0)
        self.assertEqual(list(dialog._line.get_xdata())[0], 0)
        self.assertEqual(list(dialog._line.get_xdata())[-1], dialog.DISPLAY_WINDOW_SAMPLES - 1)
        self.assertEqual(list(dialog._line.get_ydata())[0], 1)
        self.assertEqual(list(dialog._line.get_ydata())[-1], 1000)
        self.assertEqual(dialog.window_label.text(), "Window: 0-999 of 1200")
        self.assertEqual(bridge.series_by_node[7], original)

        dialog.window_slider.setValue(dialog.window_slider.maximum())
        self.assertEqual(dialog._debug_state["stopped_review_start"], 200)
        self.assertEqual(list(dialog._line.get_ydata())[0], 201)
        self.assertEqual(list(dialog._line.get_ydata())[-1], 1200)
        dialog.close()

    def test_stopped_state_with_small_session_keeps_slider_disabled(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 501)]
        dialog.stop_button.click()

        self.assertFalse(dialog.window_slider.isEnabled())
        self.assertEqual(dialog.window_label.text(), "Window: all samples")
        dialog.close()

    def test_clear_resets_slider_and_display_baseline(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 1201)]
        dialog.stop_button.click()
        dialog.window_slider.setValue(100)
        self.assertEqual(dialog._debug_state["stopped_review_start"], 100)
        dialog.refresh_display()
        self.assertEqual(dialog.window_slider.value(), 100)
        self.assertEqual(dialog._debug_state["stopped_review_start"], 100)
        dialog.clear_button.click()

        self.assertFalse(dialog.window_slider.isEnabled())
        self.assertEqual(dialog.window_slider.value(), 0)
        self.assertEqual(list(dialog._line.get_xdata()), [])
        self.assertEqual(list(dialog._line.get_ydata()), [])
        bridge.series_by_node[7].append({"index": 1201, "current_mA": 1201})
        dialog.refresh_display()
        self.assertEqual(list(dialog._line.get_xdata()), [0])
        self.assertEqual(list(dialog._line.get_ydata()), [1201])
        dialog.close()

    def test_slider_change_requests_canvas_redraw(self) -> None:
        bridge = _FakeBridge()
        dialog = MotorCurrentPlotDialog(
            bridge,
            node_provider=lambda: (7, "PZ"),
            send_query=lambda node_id, payload: bridge.runtime_window.backend_client.send_command_bytes(node_id, payload),
            query_payload_builder=build_motor_current_query_payload,
        )
        redraws: list[str] = []
        dialog._canvas.draw_idle = lambda: redraws.append("draw")

        dialog.start_button.click()
        bridge.series_by_node[7] = [{"index": index, "current_mA": index} for index in range(1, 1201)]
        dialog.stop_button.click()
        redraws.clear()
        dialog.window_slider.setValue(0)

        self.assertGreaterEqual(len(redraws), 1)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
