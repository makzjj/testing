from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import data.text_cmd_builders as text_builders
import services.firmware_transport_adapter as firmware_transport_adapter_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from services.firmware_transport_adapter import FirmwareTransportAdapter


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.writes.append(payload)


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)


class _FakeBridge:
    def __init__(self, *, connected: bool = True) -> None:
        self._runtime_window = _FakeRuntimeWindow(connected=connected)

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class FirmwareManualTextArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_controller_uses_single_active_operation_owner(self) -> None:
        controller = FirmwareIntegrationController()

        self.assertTrue(hasattr(controller, "_active_operation"))
        self.assertFalse(hasattr(controller, "_pending_manual_binary_request"))
        self.assertFalse(hasattr(controller, "_pending_manual_text_request"))

    def test_binary_pending_rejects_text_send_without_replacing_active_operation(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        pending_before = controller.pending_manual_binary_request
        self.assertIsNotNone(pending_before)
        timeout_before = controller._timeout_timer.remainingTime()

        self.assertFalse(controller.send_manual_text_command("Version Query"))

        self.assertIs(controller.pending_manual_binary_request, pending_before)
        self.assertEqual(len(bridge._runtime_window.backend_client.sent_commands), 1)
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), 0)
        self.assertGreaterEqual(controller._timeout_timer.remainingTime(), 0)
        self.assertLessEqual(controller._timeout_timer.remainingTime(), timeout_before)

    def test_text_pending_rejects_binary_send_without_replacing_active_operation(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        pending_before = controller.pending_manual_text_request
        self.assertIsNotNone(pending_before)
        timeout_before = controller._timeout_timer.remainingTime()

        self.assertFalse(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))

        self.assertIs(controller.pending_manual_text_request, pending_before)
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), 1)
        self.assertEqual(len(bridge._runtime_window.backend_client.sent_commands), 0)
        self.assertGreaterEqual(controller._timeout_timer.remainingTime(), 0)
        self.assertLessEqual(controller._timeout_timer.remainingTime(), timeout_before)

    def test_completion_timeout_cancel_and_send_failure_return_to_idle(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        runtime_window = bridge.get_runtime_window(create_if_missing=False)
        baseline = runtime_window.receivers(runtime_window.packet_received)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.handle_manual_text_packet({"status": "ok", "type": "direct_uart", "raw_payload": list(b"ver:1.2.3\r\n")})
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.handle_timeout()
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.cancel_active_operation()
        self.assertFalse(controller.has_pending_firmware_request())
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        disconnected = FirmwareIntegrationController(_FakeBridge(connected=False))
        self.assertFalse(disconnected.send_manual_text_command("Version Query"))
        self.assertFalse(disconnected.has_pending_firmware_request())

    def test_text_decode_helper_is_single_canonical_normalization_owner(self) -> None:
        helper_source = inspect.getsource(text_builders)
        controller_source = inspect.getsource(FirmwareIntegrationController)
        adapter_source = inspect.getsource(firmware_transport_adapter_module)

        self.assertIn("def decode_text_command_response", helper_source)
        self.assertNotIn(".decode(", controller_source)
        self.assertNotIn(".decode(", adapter_source)
        self.assertNotIn("startswith(", adapter_source)
        self.assertNotIn("decode_text_command_response", adapter_source)

    def test_manual_text_ui_file_exists_without_new_public_controller(self) -> None:
        self.assertTrue(Path("gui/workspace/dialogs/manual_text_command_dialog.py").exists())
        controller_sources = []
        for path in Path("gui/workspace/controllers").glob("*.py"):
            controller_sources.append(path.read_text(encoding="utf-8"))
        all_controller_source = "\n".join(controller_sources)
        self.assertNotIn("class ManualTextController", all_controller_source)
        self.assertNotIn("class TextCommandController", all_controller_source)


if __name__ == "__main__":
    unittest.main()
