import sys
import types
import re

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from gui.workspace.pages.single_axis_functional_popup import SingleAxisFunctionalPopup
from gui.workspace.controllers.single_axis_functional_test_controller import (
    FunctionalTestConfig,
    SingleAxisFunctionalTestController,
)
from data.binary_cmd_builders import build_hunting_timeout, build_nodeconfig_query_payload, build_run, build_tpos
from data.binary_cmd_parser import decode_nodeconfig_motion_polarity
from services.node_sensor_profile import NodeSensorProfile


def get_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    return app


@pytest.fixture(autouse=True)
def _qt_app():
    app = get_app()
    yield app


def _suppress_message_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.node_status: dict[int, dict[str, object]] = {}


class _FakeInterruptBridge:
    def __init__(self, runtime_window: _FakeRuntimeWindow | None = None) -> None:
        self.runtime_window = runtime_window
        self.polarity_by_node: dict[int, dict[str, object]] = {}

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self.runtime_window

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        return True, True

    def get_runtime_node_interrupt_state(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        if self.runtime_window is None:
            return {
                "node_id": int(node_id),
                "int0": None,
                "int1": None,
                "left_cut": None,
                "right_cut": None,
                "last_source": None,
                "left_state": "unknown",
                "right_state": "unknown",
            }
        state = self.runtime_window.node_status.get(int(node_id), {}).get("interrupt_state", {})
        left_cut = state.get("left_cut") if isinstance(state, dict) else None
        right_cut = state.get("right_cut") if isinstance(state, dict) else None
        return {
            "node_id": int(node_id),
            "int0": state.get("int0") if isinstance(state, dict) else None,
            "int1": state.get("int1") if isinstance(state, dict) else None,
            "left_cut": left_cut,
            "right_cut": right_cut,
            "last_source": state.get("last_source") if isinstance(state, dict) else None,
            "left_state": "cut" if left_cut is True else "not_cut" if left_cut is False else "unknown",
            "right_state": "cut" if right_cut is True else "not_cut" if right_cut is False else "unknown",
        }

    def get_runtime_node_motion_polarity(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        return self.polarity_by_node.get(
            int(node_id),
            {
                "node_id": int(node_id),
                "known": False,
                "source": None,
                "nodeconfig_raw": None,
                "home_sensor": None,
                "opposite_sensor": None,
                "hunting_sign": None,
                "outward_sign": None,
                "return_home_sign": None,
                "negative_run_sensor": None,
                "positive_run_sensor": None,
            },
        )


class _FakeReleaseWatchHelper:
    def __init__(self) -> None:
        self.is_active = False
        self.active_node_id: int | None = None
        self.expected_sensor: str | None = None
        self.start_calls: list[tuple[int, str]] = []
        self.stop_calls: list[str] = []
        self.sent_queries: list[list[int]] = []
        self._on_released = None
        self._on_timeout = None
        self._on_stopped = None

    def start_release_watch(
        self,
        node_id: int,
        expected_sensor: str,
        send_query,
        *,
        on_released=None,
        on_timeout=None,
        on_stopped=None,
    ) -> bool:
        if self.is_active:
            return False
        self.is_active = True
        self.active_node_id = int(node_id)
        self.expected_sensor = str(expected_sensor)
        self.start_calls.append((int(node_id), str(expected_sensor)))
        self._on_released = on_released
        self._on_timeout = on_timeout
        self._on_stopped = on_stopped
        send_query([0xD8, 0x3F])
        self.sent_queries.append([0xD8, 0x3F])
        return True

    def stop_release_watch(self, reason: str = "cancelled") -> bool:
        if not self.is_active:
            return False
        node_id = self.active_node_id
        sensor = self.expected_sensor
        self.is_active = False
        self.active_node_id = None
        self.expected_sensor = None
        self.stop_calls.append(str(reason))
        if self._on_stopped is not None and node_id is not None and sensor is not None:
            self._on_stopped(node_id, sensor, str(reason))
        return True

    def trigger_timeout(self) -> None:
        node_id = self.active_node_id
        sensor = self.expected_sensor
        self.is_active = False
        self.active_node_id = None
        self.expected_sensor = None
        if self._on_stopped is not None and node_id is not None and sensor is not None:
            self._on_stopped(node_id, sensor, "timeout")
        if self._on_timeout is not None and node_id is not None and sensor is not None:
            self._on_timeout(node_id, sensor)

    def trigger_released(self) -> None:
        node_id = self.active_node_id
        sensor = self.expected_sensor
        self.is_active = False
        self.active_node_id = None
        self.expected_sensor = None
        if self._on_stopped is not None and node_id is not None and sensor is not None:
            self._on_stopped(node_id, sensor, "released")
        if self._on_released is not None and node_id is not None and sensor is not None:
            self._on_released(node_id, sensor)


def test_run_with_selected_node_starts_controller(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(3, "AxisX")], allow_safe_tx=True)
    # select node 3 (index 1, since 0 is placeholder)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # UI disabled while running
    assert popup._is_running is True
    assert not popup.run_button.isEnabled()
    assert popup.stop_button.isEnabled()
    assert not popup.node_combo.isEnabled()
    assert not popup.tolerance_combo.isEnabled()

    # Controller should request NODECONFIG query first via safe handler
    assert popup._tx_log[-1] == build_nodeconfig_query_payload()
    assert popup.controller is not None
    assert popup.controller.cfg.zero_tolerance == 512
    assert popup.controller.cfg.movement_tolerance == 512
    assert popup.controller.cfg.range_tolerance == 512
    assert popup.controller.cfg.middle_position_tolerance == 512
    text = popup.status_block.toPlainText()
    assert "Functional test started for Node 3" in text
    assert "Tolerance: 512 counts" in text
    assert "Reading node configuration" in text
    assert "IDLE" not in text
    assert re.search(r"^\[\d{2}:\d{2}:\d{2}\] ", text, re.MULTILINE)


def test_footer_button_order_and_stop_state(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(3, "AxisX")], allow_safe_tx=True)
    footer = popup.layout().itemAt(popup.layout().count() - 1).layout()
    assert footer.itemAt(2).widget() is popup.run_button
    assert footer.itemAt(3).widget() is popup.stop_button
    assert footer.itemAt(4).widget() is popup.close_button
    assert not popup.stop_button.isEnabled()


def test_run_without_node_shows_warning_and_not_start(monkeypatch):
    called = {"warn": False}

    def fake_warn(*a, **k):
        called["warn"] = True
        return None

    monkeypatch.setattr(QMessageBox, "warning", fake_warn)
    popup = SingleAxisFunctionalPopup(node_options=None)
    popup._handle_run_clicked()
    assert called["warn"] is True
    assert popup._is_running is False


def test_status_and_command_logging(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(1, "Axis")], allow_safe_tx=True)
    popup.controller.status_changed("TEST_STATUS")
    assert "TEST_STATUS" in popup.status_block.toPlainText()

    payload = [0xC3, 0x21, 0x27, 0x10]
    popup.controller.command_requested(payload)
    assert popup._tx_log and popup._tx_log[-1] == payload
    assert "TX requested: C3 21 27 10" not in popup.status_block.toPlainText()


def test_popup_leds_render_from_runtime_interrupt_state(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        2: {
            "interrupt_state": {
                "left_cut": True,
                "right_cut": False,
                "last_source": "tpos_cut",
            }
        }
    }
    popup = SingleAxisFunctionalPopup(node_options=[(2, "Axis")], bridge=_FakeInterruptBridge(runtime_window))
    popup.node_combo.setCurrentIndex(1)
    popup._refresh_interrupt_leds()

    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()

    runtime_window.node_status[2]["interrupt_state"] = {
        "left_cut": False,
        "right_cut": True,
        "last_source": "tpos_cut",
    }
    runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 2, "cmd": 0x81, "params": [ord("R")]})
    get_app().processEvents()

    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()


def test_popup_unknown_state_is_neutral_until_runtime_data_arrives(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(2, "Axis")], bridge=_FakeInterruptBridge(_FakeRuntimeWindow()))
    popup.node_combo.setCurrentIndex(1)
    popup._refresh_interrupt_leds()

    assert SingleAxisFunctionalPopup._UNKNOWN_FLAG_COLOR in popup.left_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._UNKNOWN_FLAG_COLOR in popup.right_flag_led.styleSheet()


def test_popup_reopening_shows_latest_runtime_state_for_selected_node(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        4: {
            "interrupt_state": {
                "left_cut": False,
                "right_cut": True,
                "last_source": "tpos_cut",
            }
        }
    }
    popup = SingleAxisFunctionalPopup(node_options=[(4, "Axis")], bridge=_FakeInterruptBridge(runtime_window))
    popup.node_combo.setCurrentIndex(1)
    popup.hide()
    popup.show()
    get_app().processEvents()

    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()


def test_popup_node_switch_updates_runtime_backed_led_state(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        2: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}},
        3: {"interrupt_state": {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}},
    }
    popup = SingleAxisFunctionalPopup(
        node_options=[(2, "AxisX"), (3, "AxisY")],
        bridge=_FakeInterruptBridge(runtime_window),
    )
    popup.node_combo.setCurrentIndex(1)
    popup._refresh_interrupt_leds()
    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()

    popup.node_combo.setCurrentIndex(2)
    get_app().processEvents()
    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()


def test_popup_d8_response_refreshes_leds_from_runtime_state(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        5: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    popup = SingleAxisFunctionalPopup(node_options=[(5, "Axis")], bridge=_FakeInterruptBridge(runtime_window))
    popup.node_combo.setCurrentIndex(1)
    popup._refresh_interrupt_leds()

    runtime_window.node_status[5]["interrupt_state"] = {
        "int0": 1,
        "int1": 0,
        "left_cut": False,
        "right_cut": True,
        "last_source": "d8_query",
    }
    runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 5, "cmd": 0xD8, "params": [0x3A, 0x01, 0x00]})
    get_app().processEvents()

    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()


def test_popup_controller_sensor_callbacks_no_longer_override_runtime_led_truth(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        2: {"interrupt_state": {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}}
    }
    popup = SingleAxisFunctionalPopup(node_options=[(2, "Axis")], bridge=_FakeInterruptBridge(runtime_window))
    popup.node_combo.setCurrentIndex(1)
    popup._refresh_interrupt_leds()

    popup.controller.handle_runtime_packet([0x81, ord("L")])

    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()
    assert SingleAxisFunctionalPopup._INACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()


def test_release_watch_starts_for_left_cut_when_run_moves_away(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == [(9, "L")]
    assert helper.sent_queries == [[0xD8, 0x3F]]
    assert popup._tx_log[-2:] == [build_run(-100), [0xD8, 0x3F]]
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_starts_for_right_cut_when_run_moves_away(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        8: {"interrupt_state": {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[8] = {
        "node_id": 8,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x00,
        "negative_run_sensor": "L",
        "positive_run_sensor": "R",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(8, "Axis")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-190))

    assert helper.start_calls == [(8, "R")]
    assert helper.sent_queries == [[0xD8, 0x3F]]


def test_release_watch_moving_toward_cut_sensor_skips_with_reason(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(100))

    assert helper.start_calls == []
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_unknown_interrupt_state_skips_with_reason(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": None, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == []
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_unknown_polarity_skips_with_reason(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == []
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_no_cut_sensor_skips(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": False, "right_cut": False, "last_source": "d8_query"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == []
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_both_cut_skips(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": True, "last_source": "d8_query"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == []
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_no_duplicate_watch_is_started(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.controller.command_requested(build_run(-100))
    popup.controller.command_requested(build_run(-100))

    assert helper.start_calls == [(9, "L")]
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_timeout_does_not_fail_or_advance_controller(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    popup.controller._state = popup.controller.S_WAIT_LEFT
    popup.controller._wait_for = "left_sensor"

    popup.controller.command_requested(build_run(-100))
    before_state = popup.controller._state
    before_wait = popup.controller.current_wait_for
    helper.trigger_timeout()

    assert popup.controller._state == before_state
    assert popup.controller.current_wait_for == before_wait
    assert popup._is_running is True
    assert popup.controller._state != popup.controller.S_FAILED
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_release_does_not_advance_controller(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        8: {"interrupt_state": {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}}
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[8] = {
        "node_id": 8,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x00,
        "negative_run_sensor": "L",
        "positive_run_sensor": "R",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(8, "Axis")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    popup.controller._state = popup.controller.S_WAIT_RIGHT
    popup.controller._wait_for = "right_sensor"

    popup.controller.command_requested(build_run(-190))
    before_state = popup.controller._state
    before_wait = popup.controller.current_wait_for
    helper.trigger_released()

    assert popup.controller._state == before_state
    assert popup.controller.current_wait_for == before_wait
    assert "[ReleaseWatch]" not in popup.status_block.toPlainText()


def test_release_watch_stop_completion_failure_and_node_change_cancel(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    runtime_window = _FakeRuntimeWindow()
    runtime_window.node_status = {
        9: {"interrupt_state": {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}},
        10: {"interrupt_state": {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}},
    }
    bridge = _FakeInterruptBridge(runtime_window)
    bridge.polarity_by_node[9] = {
        "node_id": 9,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x02,
        "negative_run_sensor": "R",
        "positive_run_sensor": "L",
    }
    bridge.polarity_by_node[10] = {
        "node_id": 10,
        "known": True,
        "source": "config",
        "nodeconfig_raw": 0x00,
        "negative_run_sensor": "L",
        "positive_run_sensor": "R",
    }
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ"), (10, "Axis")],
        bridge=bridge,
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    popup.controller.command_requested(build_run(-100))
    popup.stop_button.click()
    assert "user_stop" in helper.stop_calls

    popup._handle_run_clicked()
    popup.controller.command_requested(build_run(-100))
    popup.mark_failed("oops")
    assert "run_finished" in helper.stop_calls

    popup._handle_run_clicked()
    popup.controller.command_requested(build_run(-100))
    popup.mark_passed = lambda: None  # prevent modal path if accidentally invoked
    popup._finish_run_ui()
    assert helper.stop_calls.count("run_finished") >= 2

    popup._handle_run_clicked()
    popup.controller.command_requested(build_run(-100))
    popup.node_combo.setCurrentIndex(2)
    assert "node_changed" in helper.stop_calls


def test_release_watch_close_cancels_when_popup_is_not_running(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    helper = _FakeReleaseWatchHelper()
    popup = SingleAxisFunctionalPopup(
        node_options=[(9, "PZ")],
        bridge=_FakeInterruptBridge(_FakeRuntimeWindow()),
        allow_safe_tx=True,
        release_watch_helper=helper,
    )
    helper.is_active = True
    helper.active_node_id = 9
    helper.expected_sensor = "L"

    popup.close()

    assert "popup_closed" in helper.stop_calls


def test_position_and_range_difference_updates(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(4, "Axis")], allow_safe_tx=True)
    # Position direct callback
    popup.controller.position_changed(123)
    assert popup.position_field.text() == "123"
    # Range 1 and Range 2 update the field; difference only logs.
    popup.controller.range1_changed(1000)
    assert popup.range_field.text() == "1000"
    popup.controller.range2_changed(1100)
    assert popup.range_field.text() == "1100"
    popup.controller.difference_changed(100)
    text = popup.status_block.toPlainText()
    assert text == ""
    # range_field keeps the latest real movement value, not the difference.
    assert popup.range_field.text() == "1100"


class SingleAxisFunctionalPopupTests:
    __test__ = True

    def test_single_axis_return_leg_keeps_measured_range_display_and_logs_middle_preview(self, monkeypatch):
        _suppress_message_boxes(monkeypatch)
        controller = SingleAxisFunctionalTestController(FunctionalTestConfig(reference_sensor="L", opposite_sensor="R"))
        polarity = decode_nodeconfig_motion_polarity(0x00)
        controller._node_id = 6
        controller._motion_polarity = polarity
        controller._sensor_profile = NodeSensorProfile.from_node_context(6, polarity)
        popup = SingleAxisFunctionalPopup(node_options=[(3, "X")], controller=controller, allow_safe_tx=True)
        differences: list[int] = []
        original_difference_changed = controller.difference_changed

        def record_difference(value: int) -> None:
            differences.append(value)
            original_difference_changed(value)

        controller.difference_changed = record_difference

        controller._home_pos = 0
        controller._state = controller.S_READ_RANGE1
        controller._wait_for = "getpos_r1"
        controller._handle_getpos(("G", 2_499_678))
        assert popup.range_field.text() == "2499678"

        controller._state = controller.S_READ_RANGE2
        controller._wait_for = "getpos_r2"
        controller._opposite_pos = 2_499_678
        controller._range_1 = 2_499_678
        controller._handle_getpos(("G", -100))

        assert popup.range_field.text() == "2499778"
        assert differences[-1] == 100
        assert "Moving to midpoint" in popup.status_block.toPlainText()
        assert "Middle travel distance" not in popup.status_block.toPlainText()
        popup.close()


def test_range_display_resets_between_runs(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(4, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)

    popup._handle_run_clicked()
    popup.controller.range1_changed(1000)
    popup.controller.range2_changed(1100)
    popup.controller.position_changed(12)
    popup.controller.command_requested(build_tpos(50000))
    assert popup.range_field.text() == "1100"

    popup.stop_button.click()
    popup._handle_run_clicked()

    assert popup.range_field.text() == "-"
    assert "Middle travel distance" not in popup.status_block.toPlainText()


def test_pass_triggers_sampling_prompt_and_reenables(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(5, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    called = {"ask": False}

    def fake_ask():
        called["ask"] = True
        return False

    popup.ask_start_sampling = fake_ask  # type: ignore[assignment]
    popup.controller.test_passed()
    assert called["ask"] is True
    assert popup._is_running is False
    assert popup.run_button.isEnabled() and popup.node_combo.isEnabled() and popup.tolerance_combo.isEnabled()
    assert not popup.stop_button.isEnabled()


def test_failed_marks_failed_and_no_sampling_prompt(monkeypatch):
    # If sampling is asked here, raise to fail the test
    def bad_ask():
        raise AssertionError("ask_start_sampling should not be called on failure")

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    popup = SingleAxisFunctionalPopup(node_options=[(6, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    popup.ask_start_sampling = bad_ask  # type: ignore[assignment]
    popup.controller.test_failed("oops")
    assert popup._is_running is False
    assert popup.run_button.isEnabled() and popup.node_combo.isEnabled() and popup.tolerance_combo.isEnabled()
    assert not popup.stop_button.isEnabled()


def test_stop_button_aborts_logs_dd_and_allows_rerun(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(7, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    popup.stop_button.click()

    text = popup.status_block.toPlainText()
    assert "Functional test aborted by user" in text
    assert "Functional test ABORTED by user." not in text
    assert "TX Node 7: DD" not in text
    assert popup._tx_log[-1] == [0xDD]
    assert popup._is_running is False
    assert popup.run_button.isEnabled()
    assert popup.node_combo.isEnabled()
    assert popup.tolerance_combo.isEnabled()
    assert not popup.stop_button.isEnabled()

    popup._handle_run_clicked()
    assert popup._is_running is True
    assert popup._tx_log[-1] == build_nodeconfig_query_payload()


def test_tolerance_dropdown_defaults_and_selection_propagates(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(9, "Axis")], allow_safe_tx=True)
    assert popup.tolerance_combo.currentText() == "512 counts"
    popup.tolerance_combo.setCurrentIndex(popup.tolerance_combo.findData(2048))
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    assert popup.controller is not None
    assert popup.controller.cfg.zero_tolerance == 2048
    assert popup.controller.cfg.movement_tolerance == 2048
    assert not popup.tolerance_combo.isEnabled()


def test_close_works_after_stop(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(11, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    popup.stop_button.click()

    warned = {"called": False}

    def fake_info(*a, **k):
        warned["called"] = True
        return None

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    assert popup.close() is True
    assert warned["called"] is False


def test_run_with_selected_node_but_no_backend_aborts_normally(monkeypatch):
    # Normal UI behavior (allow_safe_tx=False): do not start without connection
    calls = {"warn": 0}

    def fake_warn(*a, **k):
        calls["warn"] += 1
        return None

    monkeypatch.setattr(QMessageBox, "warning", fake_warn)
    popup = SingleAxisFunctionalPopup(node_options=[(9, "AxisZ")])
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    assert popup._is_running is False
    assert popup.run_button.isEnabled() and popup.node_combo.isEnabled()
    text = popup.status_block.toPlainText()
    assert "Transport not connected. Functional test not started." in text
    assert calls["warn"] == 1
