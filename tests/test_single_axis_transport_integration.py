import sys

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from data.binary_cmd_builders import build_nodeconfig_query_payload
from gui.workspace.pages.single_axis_functional_popup import SingleAxisFunctionalPopup


def get_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv[:1])
    return app


@pytest.fixture(autouse=True)
def _qt_app():
    app = get_app()
    yield app


def _suppress_boxes(monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)


class _FakeBackendClient:
    def __init__(self, connected: bool) -> None:
        self._connected = connected
        self.sent = []  # list[(node_id, payload)]

    def is_connected(self) -> bool:
        return bool(self._connected)

    def send_command_bytes(self, node_id: int, command_bytes: list[int]):
        self.sent.append((int(node_id), list(command_bytes)))
        return bytearray([0x25, 0xA5, 0x01, node_id, 0x31, len(command_bytes), *command_bytes])


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, backend_client: _FakeBackendClient):
        super().__init__()
        self.backend_client = backend_client


class _FakeBridge:
    def __init__(self, runtime_window: _FakeRuntimeWindow | None) -> None:
        self._runtime_window = runtime_window

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self._runtime_window


def _emit_can(runtime_window: _FakeRuntimeWindow, sender: int, cmd: int, params: list[int]):
    runtime_window.packet_received.emit({
        "type": "can_over_uart",
        "sender": sender,
        "cmd": cmd,
        "params": list(params),
    })


def _emit_direct(runtime_window: _FakeRuntimeWindow, node_id: int, payload: list[int]):
    runtime_window.packet_received.emit({
        "type": "direct_uart",
        "node_id": node_id,
        "raw_payload": list(payload),
    })


def _start_live_popup(node_id: int, node_name: str = "Axis") -> tuple[SingleAxisFunctionalPopup, _FakeBackendClient, _FakeRuntimeWindow]:
    backend = _FakeBackendClient(connected=True)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)
    popup = SingleAxisFunctionalPopup(node_options=[(node_id, node_name)], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    return popup, backend, runtime_window


def _drive_to_first_run_ack_wait(runtime_window: _FakeRuntimeWindow, node_id: int) -> None:
    _emit_can(runtime_window, node_id, 0xC4, [0x3A, 0x00])
    _emit_can(runtime_window, node_id, 0xC3, [0x41])
    _emit_can(runtime_window, node_id, 0x81, [ord("L")])
    _emit_can(runtime_window, node_id, 0x81, [ord("I")])
    _emit_can(runtime_window, node_id, 0x82, [0x00, 0x00, 0x00, 0x00])
    _emit_can(runtime_window, node_id, 0xC9, [0x3A, 0x09])
    _emit_can(runtime_window, node_id, 0xCA, [0x3A, 0x09])


def _drive_to_first_sensor_wait(runtime_window: _FakeRuntimeWindow, node_id: int) -> None:
    _drive_to_first_run_ack_wait(runtime_window, node_id)
    _emit_can(runtime_window, node_id, 0x88, [0x53, 0x00, 0xBE])


def test_disconnected_backend_aborts_run(monkeypatch):
    _suppress_boxes(monkeypatch)
    backend = _FakeBackendClient(connected=False)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)

    popup = SingleAxisFunctionalPopup(node_options=[(7, "Axis")], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # Aborted: UI should be re-enabled and no run in progress
    assert popup._is_running is False
    assert popup.run_button.isEnabled() and popup.node_combo.isEnabled()
    assert "Transport not connected. Functional test not started." in popup.status_block.toPlainText()
    # Ensure nothing was sent on disconnected backend
    assert backend.sent == []


def test_connected_backend_sends_and_receives(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisX")

    # Should be running in live mode
    assert popup._is_running is True
    text = popup.status_block.toPlainText()
    assert f"Using live transport for Node {node_id}" in text

    # The controller will request a HUNTING command first; ensure that went to backend
    assert backend.sent, "Expected at least one command to be sent via backend"
    sent_nodes = {n for (n, _p) in backend.sent}
    assert sent_nodes == {node_id}

    _emit_can(runtime_window, node_id, 0xC4, [0x3A, 0x00])
    _emit_can(runtime_window, node_id, 0xC3, [0x41])
    _emit_can(runtime_window, node_id, 0x81, [ord('L')])
    _emit_can(runtime_window, node_id, 0x81, [ord('I')])
    _emit_can(runtime_window, node_id, 0x82, [0x00, 0x00, 0x00, 0x10])

    # Check status logs include RX labels
    t = popup.status_block.toPlainText()
    assert f"RX Node {node_id}: 81 4C - Left sensor has been cut" in t
    assert f"RX Node {node_id}: 82 00 00 00 10 - Position 16" in t

    # Ensure TX logs include node
    assert any(f"TX Node {node_id}:" in line for line in t.splitlines())


def test_adapter_forwards_nodeconfig_and_controller_proceeds(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 6
    backend = _FakeBackendClient(connected=True)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)

    popup = SingleAxisFunctionalPopup(node_options=[(node_id, "AxisY")], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # Emit NODECONFIG response from our node (CAN-over-UART style)
    runtime_window.packet_received.emit({
        "type": "can_over_uart",
        "sender": node_id,
        "cmd": 0xC4,
        "params": [0x3A, 0x00],
    })

    # The controller should log NODECONFIG received and proceed to HUNTING
    text = popup.status_block.toPlainText()
    assert f"RX Node {node_id}: C4 3A 00" in text
    assert "NODECONFIG received: 0x00" in text
    assert "HUNTING" in text
    lines = text.splitlines()
    rx_idx = next(i for i, line in enumerate(lines) if f"RX Node {node_id}: C4 3A 00" in line)
    tx_idx = next(i for i, line in enumerate(lines[rx_idx + 1 :], start=rx_idx + 1) if f"TX Node {node_id}:" in line)
    assert rx_idx < tx_idx


def test_live_stop_button_sends_dd_and_reenables_controls(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    backend = _FakeBackendClient(connected=True)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)

    popup = SingleAxisFunctionalPopup(node_options=[(node_id, "AxisZ")], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()
    assert popup._is_running is True
    assert popup.stop_button.isEnabled()

    popup.stop_button.click()

    assert popup._is_running is False
    assert popup.run_button.isEnabled()
    assert popup.node_combo.isEnabled()
    assert popup.tolerance_combo.isEnabled()
    assert not popup.stop_button.isEnabled()
    assert backend.sent[-1] == (node_id, [0xDD])
    text = popup.status_block.toPlainText()
    assert f"TX Node {node_id}: DD" in text
    assert "Functional test ABORTED by user." in text


def test_no_out_of_state_ignore_log_while_waiting_for_nodeconfig(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 5
    backend = _FakeBackendClient(connected=True)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)

    popup = SingleAxisFunctionalPopup(node_options=[(node_id, "AxisZ")], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # While still waiting for NODECONFIG, a GETPOS arrives; ensure no RUN-ACK ignore log appears
    runtime_window.packet_received.emit({
        "type": "can_over_uart",
        "sender": node_id,
        "cmd": 0x82,
        "params": [0x00, 0x00, 0x00, 0x00],
    })

    text = popup.status_block.toPlainText()
    assert "Querying NODECONFIG" in text
    assert "Ignoring out-of-state packet while waiting for RUN ACK" not in text


def test_adapter_ignores_wrong_node_and_runtime_only_packets_without_logging(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 5
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisZ")

    baseline_text = popup.status_block.toPlainText()
    assert backend.sent == [(node_id, build_nodeconfig_query_payload())]
    assert popup.controller is not None
    assert popup.controller.current_wait_for == "nodeconfig"

    _emit_can(runtime_window, 7, 0x88, [0x53, 0x00, 0xBE])
    _emit_can(runtime_window, node_id, 0xC8, [0x3A, 0x12, 0x30, 0x10])
    _emit_can(runtime_window, node_id, 0xD8, [0x3A, 0x01, 0x00])
    _emit_can(runtime_window, node_id, 0x86, [0x3A])
    _emit_direct(runtime_window, 1, [0xB5, 0x3A, 0x01, 0x05, 0x00])

    assert popup.controller.current_wait_for == "nodeconfig"
    assert backend.sent == [(node_id, build_nodeconfig_query_payload())]
    assert popup.status_block.toPlainText() == baseline_text
    assert popup._is_running is True


def test_stale_run_ack_with_wrong_velocity_is_dropped(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisY")

    _drive_to_first_run_ack_wait(runtime_window, node_id)
    assert popup.controller is not None
    assert popup.controller.current_wait_for == "run_right_ack"
    baseline_text = popup.status_block.toPlainText()
    sent_count = len(backend.sent)

    _emit_can(runtime_window, node_id, 0x88, [0x53, 0xFF, 0x42])

    assert popup.controller.current_wait_for == "run_right_ack"
    assert len(backend.sent) == sent_count
    assert popup.status_block.toPlainText() == baseline_text

    _emit_can(runtime_window, node_id, 0x88, [0x53, 0x00, 0xBE])
    assert popup.controller.current_wait_for == "right_sensor"
    assert "WAIT_FOR_RIGHT_SENSOR" in popup.status_block.toPlainText()


def test_stale_same_node_getpos_and_middle_tpos_are_dropped_while_waiting_for_sensor(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisY")

    _drive_to_first_sensor_wait(runtime_window, node_id)
    assert popup.controller is not None
    assert popup.controller.current_wait_for == "right_sensor"
    baseline_text = popup.status_block.toPlainText()
    sent_count = len(backend.sent)

    _emit_can(runtime_window, node_id, 0x82, [0x00, 0x00, 0x00, 0x10])
    _emit_can(runtime_window, node_id, 0x81, [ord("E"), 0x82, 0x00, 0x00, 0x13, 0x88])

    assert popup.controller.current_wait_for == "right_sensor"
    assert len(backend.sent) == sent_count
    assert popup.status_block.toPlainText() == baseline_text


def test_duplicate_sensor_event_outside_relevant_wait_is_dropped(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisY")

    _drive_to_first_sensor_wait(runtime_window, node_id)
    _emit_can(runtime_window, node_id, 0x81, [ord("R")])
    assert popup.controller is not None
    assert popup.controller.current_wait_for == "getpos_r1"
    sent_count = len(backend.sent)
    baseline_text = popup.status_block.toPlainText()

    _emit_can(runtime_window, node_id, 0x81, [ord("R")])

    assert popup.controller.current_wait_for == "getpos_r1"
    assert len(backend.sent) == sent_count
    assert popup.status_block.toPlainText() == baseline_text


def test_wrong_sensor_during_active_movement_wait_still_reaches_controller_and_fails(monkeypatch):
    _suppress_boxes(monkeypatch)
    node_id = 8
    popup, backend, runtime_window = _start_live_popup(node_id, "AxisY")

    _drive_to_first_sensor_wait(runtime_window, node_id)
    _emit_can(runtime_window, node_id, 0x81, [ord("L")])

    assert popup._is_running is False
    assert backend.sent[-1] == (node_id, [0xDD])
    text = popup.status_block.toPlainText()
    assert f"RX Node {node_id}: 81 4C - Left sensor has been cut" in text
    assert "FAILED" in text or "Functional test FAILED" in text
