from __future__ import annotations

import os
import sys
import unittest

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.models import FirmwareCommandDefinition
from gui.workspace.pages.firmware_page import FirmwarePage
from services.firmware_transport_adapter import FirmwareTransportAdapter


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []

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
        self.raw_config = {
            "robot": {
                "axes": {
                    "x": {"node_id": 3},
                    "y": {"node_id": 11},
                },
                "encoders": {
                    "encoder": {"node_id": 14},
                },
            }
        }
        self._runtime_window = _FakeRuntimeWindow()
        self.runtime_window_requests = 0

    def get_frame_loss_items(self) -> list[object]:
        return []

    def get_runtime_window(self, *, create_if_missing: bool = False):
        self.runtime_window_requests += 1
        return self._runtime_window


class FirmwareFitScaffoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_firmware_page_renders_fit_section_and_buttons(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        page.show()
        self._app.processEvents()

        expected_buttons = {
            "FirmwareFitManualBinaryButton": "Manual Binary Command",
            "FirmwareFitManualTextButton": "Manual Text Command",
            "FirmwareFitRunBinaryButton": "Run Binary FIT",
            "FirmwareFitRunTextButton": "Run Text FIT",
            "FirmwareFitReportsButton": "Reports / Export",
        }

        for object_name, label in expected_buttons.items():
            button = page.findChild(QPushButton, object_name)
            self.assertIsNotNone(button)
            assert button is not None
            self.assertEqual(button.text(), label)

        status_label = page.findChild(QLabel, "FirmwareIntegrationStatusLabel")
        self.assertIsNotNone(status_label)
        assert status_label is not None
        self.assertIn("FIT-0B", status_label.text())

    def test_fit_buttons_are_inert_and_do_not_send_commands(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        runtime_window = bridge._runtime_window
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        button_names = [
            "FirmwareFitManualBinaryButton",
            "FirmwareFitManualTextButton",
            "FirmwareFitRunBinaryButton",
            "FirmwareFitRunTextButton",
            "FirmwareFitReportsButton",
        ]

        for object_name in button_names:
            button = page.findChild(QPushButton, object_name)
            self.assertIsNotNone(button)
            assert button is not None
            button.click()

        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)
        self.assertEqual(bridge.runtime_window_requests, 0)
        self.assertNotIn("legacy_reference.firmware_integration_test", sys.modules)

        status_label = page.findChild(QLabel, "FirmwareIntegrationStatusLabel")
        self.assertIsNotNone(status_label)
        assert status_label is not None
        self.assertIn("No report behavior yet", status_label.text())

    def test_firmware_integration_controller_is_instantiable_and_inert(self) -> None:
        controller = FirmwareIntegrationController()

        self.assertIsInstance(controller.transport_adapter, FirmwareTransportAdapter)
        self.assertIn("FIT-0B", controller.open_manual_binary_mode())
        self.assertIn("No active", controller.cancel_active_operation())
        controller.handle_runtime_packet({"ignored": True})
        self.assertIn("No active", controller.last_action or "")

    def test_firmware_transport_adapter_is_instantiable_without_subscribing(self) -> None:
        controller = FirmwareIntegrationController()
        adapter = FirmwareTransportAdapter(controller)
        runtime_window = _FakeRuntimeWindow()
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)

        adapter.attach(runtime_window)
        adapter.handle_packet({"ignored": True})

        self.assertTrue(adapter.is_attached)
        self.assertIs(adapter.runtime_packet_source, runtime_window)
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

        adapter.detach()
        self.assertFalse(adapter.is_attached)
        self.assertIsNone(adapter.runtime_packet_source)

    def test_firmware_command_definition_is_instantiable(self) -> None:
        definition = FirmwareCommandDefinition(
            name="GETVER",
            mode="binary",
            opcode=0xC8,
            expected_response="firmware",
            timeout_ms=1500,
            builder_name="build_getver_query_payload",
            decoder_name="decode_command",
        )

        self.assertEqual(definition.name, "GETVER")
        self.assertEqual(definition.mode, "binary")
        self.assertEqual(definition.opcode, 0xC8)
        self.assertEqual(definition.timeout_ms, 1500)


if __name__ == "__main__":
    unittest.main()
