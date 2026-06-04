import sys

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

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
    node_id = 3
    backend = _FakeBackendClient(connected=True)
    runtime_window = _FakeRuntimeWindow(backend)
    bridge = _FakeBridge(runtime_window)

    popup = SingleAxisFunctionalPopup(node_options=[(node_id, "AxisX")], bridge=bridge)
    popup.node_combo.setCurrentIndex(1)
    popup._handle_run_clicked()

    # Should be running in live mode
    assert popup._is_running is True
    text = popup.status_block.toPlainText()
    assert f"Using live transport for Node {node_id}" in text

    # The controller will request a HUNTING command first; ensure that went to backend
    assert backend.sent, "Expected at least one command to be sent via backend"
    sent_nodes = {n for (n, _p) in backend.sent}
    assert sent_nodes == {node_id}

    # Simulate incoming RX packets from our node
    runtime_window.packet_received.emit({
        "type": "can_over_uart",
        "sender": node_id,
        "cmd": 0x81,
        "params": [ord('L')],
    })
    runtime_window.packet_received.emit({
        "type": "can_over_uart",
        "sender": node_id,
        "cmd": 0x82,
        "params": [0x00, 0x00, 0x00, 0x10],  # position 16
    })

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
