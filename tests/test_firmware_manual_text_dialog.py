from __future__ import annotations

import inspect
import os
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QComboBox, QLineEdit, QLabel, QPushButton, QTextEdit

import gui.workspace.dialogs.manual_text_command_dialog as manual_text_dialog_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs.manual_binary_command_dialog import ManualBinaryCommandDialog
from gui.workspace.dialogs.manual_text_command_dialog import ManualTextCommandDialog
from gui.workspace.pages.firmware_page import FirmwarePage


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
        self.raw_config = {
            "robot": {
                "axes": {
                    "x": {"node_id": 3},
                    "z": {"node_id": 12},
                }
            }
        }
        self._runtime_window = _FakeRuntimeWindow(connected=connected)
        self.runtime_window_requests = 0

    def get_frame_loss_items(self) -> list[object]:
        return []

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        self.runtime_window_requests += 1
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self._runtime_window.backend_client.write(payload)
        return payload


class FirmwareManualTextDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_manual_text_launcher_opens_dialog_with_required_widgets(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        button = page.findChild(QPushButton, "FirmwareFitManualTextButton")
        self.assertIsNotNone(button)
        assert button is not None
        button.click()
        self._app.processEvents()

        dialog = page._manual_text_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        self.assertEqual(dialog.windowTitle(), "Manual Text Command")
        self.assertTrue(dialog.isVisible())
        self.assertIsNotNone(dialog.findChild(QComboBox, "ManualTextCommandCombo"))
        self.assertIsNotNone(dialog.findChild(QLineEdit, "ManualTextValueInput"))
        self.assertIsNotNone(dialog.findChild(QPushButton, "ManualTextSendButton"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualTextStatusLabel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualTextLatencyLabel"))
        self.assertIsNotNone(dialog.findChild(QLabel, "ManualTextResponseLabel"))
        self.assertIsNotNone(dialog.findChild(QTextEdit, "ManualTextHistoryOutput"))
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.backend_client.writes, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

    def test_opening_dialog_changing_command_and_editing_value_send_nothing(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        dialog.show()
        self._app.processEvents()
        dialog.command_combo.setCurrentText("Robot Power Set")
        dialog.value_input.setText("0")
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.backend_client.writes, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

    def test_command_selector_is_populated_from_controller_definitions(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)

        expected_names = [definition.name for definition in controller.manual_text_command_definitions()]
        actual_names = [dialog.command_combo.itemText(index) for index in range(dialog.command_combo.count())]

        self.assertEqual(actual_names, expected_names)

    def test_query_and_setter_value_behavior_follows_metadata(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)

        dialog.command_combo.setCurrentText("Version Query")
        self._app.processEvents()
        self.assertFalse(dialog.value_input.isEnabled())
        self.assertEqual(dialog.value_input.placeholderText(), "No value required")

        dialog.command_combo.setCurrentText("Robot Power Set")
        self._app.processEvents()
        self.assertTrue(dialog.value_input.isEnabled())
        self.assertEqual(dialog.value_input.text(), "1")
        self.assertIn("value", dialog.value_input.placeholderText().lower())

    def test_send_delegates_to_controller_only(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)
        calls: list[tuple[str, object | None]] = []

        def _fake_send_manual_text_command(command_name: str, value: object | None = None) -> bool:
            calls.append((command_name, value))
            return False

        controller.send_manual_text_command = _fake_send_manual_text_command  # type: ignore[method-assign]

        dialog.command_combo.setCurrentText("Robot Power Set")
        dialog.value_input.setText("0")
        dialog.send_button.click()

        self.assertEqual(calls, [("Robot Power Set", "0")])
        self.assertEqual(bridge._runtime_window.backend_client.writes, [])

    def test_dialog_renders_sent_and_result_signals(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self._app.processEvents()
        self.assertIn("Waiting", dialog.response_label.text())
        self.assertIn("TX Version Query", dialog.history_output.toPlainText())
        self.assertNotEqual(dialog.tx_label.text(), "--")

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        self._app.processEvents()

        self.assertEqual(dialog.response_label.text(), "ver:1.2.3")
        self.assertEqual(dialog.latency_label.text().endswith("ms"), True)
        self.assertIn("RX Version Query", dialog.history_output.toPlainText())
        self.assertNotEqual(dialog.rx_label.text(), "--")

    def test_timeout_and_cancel_render_and_restore_send(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self._app.processEvents()
        self.assertFalse(dialog.send_button.isEnabled())

        controller.handle_timeout()
        self._app.processEvents()
        self.assertIn("TIMEOUT", dialog.history_output.toPlainText())
        self.assertEqual(dialog.latency_label.text(), "--")
        self.assertTrue(dialog.send_button.isEnabled())

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self._app.processEvents()
        dialog.close()
        self._app.processEvents()
        self.assertIn("CANCELLED", dialog.history_output.toPlainText())

    def test_binary_pending_disables_text_send_and_close_does_not_cancel_binary(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        binary_dialog = ManualBinaryCommandDialog(controller)
        text_dialog = ManualTextCommandDialog(controller)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self._app.processEvents()
        self.assertFalse(text_dialog.send_button.isEnabled())
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), 0)

        text_dialog.close()
        self._app.processEvents()
        self.assertIsNotNone(controller.pending_manual_binary_request)

        binary_dialog.close()
        self._app.processEvents()
        self.assertIsNone(controller.pending_manual_binary_request)

    def test_text_pending_prevents_duplicate_send_and_completion_restores_send(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualTextCommandDialog(controller)

        dialog.command_combo.setCurrentText("Version Query")
        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self._app.processEvents()
        self.assertFalse(dialog.send_button.isEnabled())
        first_writes = len(bridge._runtime_window.backend_client.writes)

        dialog.send_button.click()
        self._app.processEvents()
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), first_writes)

        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"ver:9.9.9\r\n")}
        )
        self._app.processEvents()
        self.assertTrue(dialog.send_button.isEnabled())

    def test_dialog_source_contains_no_protocol_runtime_or_matching_logic(self) -> None:
        source = inspect.getsource(manual_text_dialog_module)

        self.assertNotIn("build_text_command_payload", source)
        self.assertNotIn("decode_text_command_response", source)
        self.assertNotIn("packet_received", source)
        self.assertNotIn("backend_client", source)
        self.assertNotIn(".decode(", source)
        self.assertNotIn("startswith(", source)
        self.assertNotIn("QTimer", source)
        self.assertNotIn("send_firmware_text_command", source)


if __name__ == "__main__":
    unittest.main()
