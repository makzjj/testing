from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QTextEdit

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs.manual_binary_command_dialog import ManualBinaryCommandDialog
from gui.workspace.pages.firmware_page import FirmwarePage
from services.firmware_transport_adapter import FirmwareTransportAdapter


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)


class _FakeBridge:
    def __init__(self, *, connected: bool = True) -> None:
        self.raw_config = {
            "robot": {
                "axes": {
                    "x": {"node_id": 3},
                    "z": {"node_id": 12},
                },
                "encoders": {
                    "encoder": {"node_id": 14},
                },
            }
        }
        self._runtime_window = _FakeRuntimeWindow(connected=connected)
        self.runtime_window_requests = 0

    def get_frame_loss_items(self) -> list[object]:
        return []

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return [(3, "X"), (12, "Z")]

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        self.runtime_window_requests += 1
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)


class _AdapterProbeController:
    def __init__(self, *, expected_node: int = 3, expected_cmd: int = 0xC8, pending: bool = True) -> None:
        self.expected_node = expected_node
        self.expected_cmd = expected_cmd
        self.pending = pending
        self.forwarded_packets: list[dict[str, object]] = []
        self.accept_calls: list[tuple[int | None, int | None]] = []

    def has_pending_manual_binary_request(self) -> bool:
        return self.pending

    def accepts_manual_binary_packet(self, *, sender: int | None, cmd: int | None, params: list[int] | None = None) -> bool:
        _ = params
        self.accept_calls.append((sender, cmd))
        return sender == self.expected_node and cmd == self.expected_cmd

    def handle_runtime_packet(self, packet: object) -> None:
        if isinstance(packet, dict):
            self.forwarded_packets.append(packet)


class FirmwareManualBinaryModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_firmware_page_manual_binary_button_opens_dialog_with_required_widgets(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        button = page.findChild(QPushButton, "FirmwareFitManualBinaryButton")
        self.assertIsNotNone(button)
        assert button is not None
        button.click()
        self._app.processEvents()

        dialog = page._manual_binary_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        self.assertTrue(dialog.isVisible())
        self.assertIsNotNone(dialog.findChild(QComboBox, "ManualBinaryNodeCombo"))
        self.assertIsNotNone(dialog.findChild(QComboBox, "ManualBinaryCommandCombo"))
        self.assertIsNotNone(dialog.findChild(QCheckBox, "ManualBinaryRawHexToggle"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "ManualBinarySendButton"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualBinaryStatusLabel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualBinaryLatencyLabel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualBinaryDecodedResponseLabel"))
        self.assertIsNotNone(dialog.findChild(QTextEdit, "ManualBinaryHistoryOutput"))
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

    def test_opening_dialog_and_changing_selections_send_no_commands(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualBinaryCommandDialog(controller)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        dialog.show()
        self._app.processEvents()
        dialog.node_combo.setCurrentIndex(min(1, max(0, dialog.node_combo.count() - 1)))
        dialog.command_combo.setCurrentIndex(min(1, max(0, dialog.command_combo.count() - 1)))
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

    def test_dialog_send_delegates_to_controller(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualBinaryCommandDialog(controller)
        calls: list[dict[str, object]] = []

        def _fake_send_manual_binary_command(**kwargs) -> bool:
            calls.append(dict(kwargs))
            return False

        controller.send_manual_binary_command = _fake_send_manual_binary_command  # type: ignore[method-assign]
        dialog.node_combo.setCurrentIndex(0)
        dialog.command_combo.setCurrentIndex(dialog.command_combo.findData("GETVER"))
        dialog.findChild(QPushButton, "ManualBinarySendButton").click()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["node_id"], 3)
        self.assertEqual(calls[0]["command_name"], "GETVER")

    def test_dialog_close_cancels_pending_command(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualBinaryCommandDialog(controller)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertIsNotNone(controller.pending_manual_binary_request)

        dialog.close()
        self._app.processEvents()

        self.assertIsNone(controller.pending_manual_binary_request)
        self.assertIn("Cancelled pending manual binary command", controller.last_action or "")

    def test_controller_supported_manual_binary_catalog_exists(self) -> None:
        controller = FirmwareIntegrationController()
        names = [definition.name for definition in controller.manual_binary_command_definitions()]
        display_names = [str(definition.display_name or definition.name) for definition in controller.manual_binary_command_definitions()]

        self.assertEqual(len(names), 83)
        self.assertEqual(names[:6], ["TPOS - Move Motor Position", "GETPOS", "GETRPS - Get Speed", "VEL Write", "GETVEL", "NODEIDref - Get ID Reference"])
        self.assertIn("VEL Write", names)
        self.assertIn("RUN", names)
        self.assertIn("NODETYPE - Get node type", names)
        self.assertIn("NODETYPE - Set node type", names)
        self.assertIn("bcmd_NODECONFIG (Query Node Configuration)", display_names)
        self.assertIn("bcmd_INTERRUPT (Query Interrupt State)", display_names)
        self.assertIn("bcmd_MOTOR_I (Query Motor Current)", display_names)
        self.assertEqual(len(set(names)), len(names))

    def test_manual_binary_dialog_uses_canonical_order_and_display_labels(self) -> None:
        dialog = ManualBinaryCommandDialog(FirmwareIntegrationController(_FakeBridge()))
        items = [(dialog.command_combo.itemText(index), dialog.command_combo.itemData(index)) for index in range(dialog.command_combo.count())]

        self.assertEqual(items[0], ("TPOS - Move Motor Position", "TPOS - Move Motor Position"))
        self.assertEqual(items[1], ("GETPOS", "GETPOS"))
        self.assertEqual(items[2], ("GETRPS - Get Speed", "GETRPS - Get Speed"))
        self.assertLess(
            next(index for index, item in enumerate(items) if item[1] == "NODECONFIG Query"),
            next(index for index, item in enumerate(items) if item[1] == "SAVEEEPROM - Save settings"),
        )
        self.assertEqual(
            next(item[0] for item in items if item[1] == "NODECONFIG Query"),
            "bcmd_NODECONFIG (Query Node Configuration)",
        )

    def test_controller_send_creates_pending_request_and_uses_bridge_send_boundary(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        sent_events: list[object] = []
        controller.manual_binary_sent.connect(sent_events.append)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertIsNotNone(controller.pending_manual_binary_request)
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [(3, [0xC8, 0x3F])])
        self.assertEqual(len(sent_events), 1)

    def test_controller_disconnected_send_fails_cleanly(self) -> None:
        bridge = _FakeBridge(connected=False)
        controller = FirmwareIntegrationController(bridge)
        statuses: list[str] = []
        controller.status_changed.connect(statuses.append)

        self.assertFalse(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertIn("Serial port not connected.", statuses[-1])

    def test_controller_rejects_second_send_while_pending(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        statuses: list[str] = []
        controller.status_changed.connect(statuses.append)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertFalse(controller.send_manual_binary_command(node_id=3, command_name="GETPOS"))
        self.assertEqual(len(bridge._runtime_window.backend_client.sent_commands), 1)
        self.assertIn("already pending", statuses[-1])

    def test_controller_matching_response_clears_pending_and_computes_latency(self) -> None:
        now = [100.0]
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge, clock=lambda: now[0])
        results: list[dict[str, object]] = []
        controller.manual_binary_result.connect(results.append)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        now[0] = 100.050
        controller.handle_runtime_packet(
            {
                "sender": 3,
                "cmd": 0xC8,
                "params": [0x3A, 0x12, 0x30, 0x01],
                "raw_hex": "C8 3A 12 30 01",
            }
        )

        self.assertIsNone(controller.pending_manual_binary_request)
        self.assertEqual(results[-1]["status"], "PASS")
        self.assertAlmostEqual(float(results[-1]["latency_ms"]), 50.0, delta=0.001)
        self.assertIn("firmware", str(results[-1]["decoded_text"]))

    def test_controller_timeout_clears_pending_and_emits_timeout(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[dict[str, object]] = []
        controller.manual_binary_result.connect(results.append)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        controller.handle_timeout()

        self.assertIsNone(controller.pending_manual_binary_request)
        self.assertEqual(results[-1]["status"], "TIMEOUT")

    def test_controller_wrong_node_or_command_is_ignored(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[dict[str, object]] = []
        controller.manual_binary_result.connect(results.append)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        controller.handle_runtime_packet({"sender": 12, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})
        controller.handle_runtime_packet({"sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]})

        self.assertIsNotNone(controller.pending_manual_binary_request)
        self.assertEqual(results, [])

    def test_controller_raw_hex_validation_fails_cleanly(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        statuses: list[str] = []
        controller.status_changed.connect(statuses.append)

        self.assertFalse(controller.send_manual_binary_command(node_id=3, use_raw_hex=True, raw_hex_text="ZZ"))
        self.assertEqual(bridge._runtime_window.backend_client.sent_commands, [])
        self.assertIn("Invalid raw hex payload.", statuses[-1])

    def test_adapter_ignores_packets_without_pending_request(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        controller = _AdapterProbeController(pending=False)
        adapter = FirmwareTransportAdapter(controller)
        adapter.attach(runtime_window)

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})

        self.assertEqual(controller.accept_calls, [])
        self.assertEqual(controller.forwarded_packets, [])
        self.assertFalse(hasattr(adapter, "_pending_manual_binary_request"))
        self.assertFalse(hasattr(adapter, "_timeout_timer"))

    def test_adapter_ignores_wrong_node_and_wrong_command(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        controller = _AdapterProbeController(expected_node=3, expected_cmd=0xC8, pending=True)
        adapter = FirmwareTransportAdapter(controller)
        adapter.attach(runtime_window)

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 12, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]})

        self.assertEqual(controller.forwarded_packets, [])
        self.assertEqual(controller.accept_calls, [(12, 0xC8), (3, 0x82)])

    def test_adapter_forwards_matching_packet_only(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        controller = _AdapterProbeController(expected_node=3, expected_cmd=0xC8, pending=True)
        adapter = FirmwareTransportAdapter(controller)
        adapter.attach(runtime_window)

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})

        self.assertEqual(len(controller.forwarded_packets), 1)
        self.assertEqual(controller.forwarded_packets[0]["sender"], 3)
        self.assertEqual(controller.forwarded_packets[0]["cmd"], 0xC8)


if __name__ == "__main__":
    unittest.main()
