import sys
import types

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox

from gui.workspace.pages.single_axis_functional_popup import SingleAxisFunctionalPopup
from gui.workspace.controllers.single_axis_functional_test_controller import (
    FunctionalTestConfig,
)
from data.binary_cmd_builders import build_hunting_timeout, build_nodeconfig_query_payload, build_tpos


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
    assert "Tolerance selected: 512 counts" in popup.status_block.toPlainText()

    # Status block should contain some status lines (e.g., IDLE/state updates)
    text = popup.status_block.toPlainText()
    assert "IDLE" in text


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
    assert "TX requested: C3 21 27 10" in popup.status_block.toPlainText()


def test_flag_leds_light_on_events(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(2, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # Simulate left/right sensor events arriving at controller
    popup.controller.handle_runtime_packet([0x81, ord('L')])
    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.left_flag_led.styleSheet()
    popup.controller.handle_runtime_packet([0x81, ord('R')])
    assert SingleAxisFunctionalPopup._ACTIVE_FLAG_COLOR in popup.right_flag_led.styleSheet()


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
    assert "Range 1: 1000" in text
    assert "Range 2: 1100" in text
    assert "Difference: 100" in text
    # range_field keeps the latest real movement value, not the difference.
    assert popup.range_field.text() == "1100"


def test_middle_travel_range_uses_tpos_target_then_latest_position(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(4, "Axis")], allow_safe_tx=True)

    popup.controller.position_changed(8)
    popup.controller.command_requested(build_tpos(50000))
    assert popup.range_field.text() == "49992"
    assert "Middle travel distance: 49992" in popup.status_block.toPlainText()

    popup.controller.position_changed(49990)
    assert popup.range_field.text() == "49992"


def test_range_display_resets_between_runs(monkeypatch):
    _suppress_message_boxes(monkeypatch)
    popup = SingleAxisFunctionalPopup(node_options=[(4, "Axis")], allow_safe_tx=True)
    popup.node_combo.setCurrentIndex(1)

    popup._handle_run_clicked()
    popup.controller.range1_changed(1000)
    popup.controller.range2_changed(1100)
    popup.controller.position_changed(12)
    popup.controller.command_requested(build_tpos(50000))
    assert popup.range_field.text() == "49988"

    popup.stop_button.click()
    popup._handle_run_clicked()

    assert popup.range_field.text() == "-"
    assert popup.status_block.toPlainText().count("Middle travel distance: 49988") == 1


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
    assert "Functional test ABORTED by user." in text
    assert "TX Node 7: DD" in text
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
