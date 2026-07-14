from __future__ import annotations

import inspect
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import data.text_cmd_builders as text_builders
import gui.workspace.sections.firmware.firmware_sections as firmware_sections_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from services.firmware_transport_adapter import FirmwareTransportAdapter


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.writes: list[bytearray] = []
        self.last_write_payload: bytearray | None = None

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray([0x25, 0xA5, 0x01, int(node_id), 0x31, len(payload), *payload])

    def write(self, payload: bytearray) -> None:
        self.last_write_payload = payload
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


class _TextAdapterProbeController:
    def __init__(self, *, pending: bool = True) -> None:
        self.pending = pending
        self.forwarded_packets: list[dict[str, object]] = []

    def pending_request_mode(self) -> str | None:
        return "text" if self.pending else None

    def handle_manual_text_packet(self, packet: object) -> None:
        if isinstance(packet, dict):
            self.forwarded_packets.append(packet)


class FirmwareManualTextCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_text_query_builder_bytes_are_pinned(self) -> None:
        self.assertEqual(
            list(text_builders.build_text_command_payload("ver?")),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x08, 0x76, 0x65, 0x72, 0x3F, 0x0D, 0x0A, 0x0D, 0x0A, 0xF5, 0x19],
        )
        self.assertEqual(
            list(text_builders.build_text_command_payload("uartstat?")),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x0D, 0x75, 0x61, 0x72, 0x74, 0x73, 0x74, 0x61, 0x74, 0x3F, 0x0D, 0x0A, 0x0D, 0x0A, 0x25, 0x5C],
        )
        self.assertEqual(
            list(text_builders.build_text_command_payload("opmode?")),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x0B, 0x6F, 0x70, 0x6D, 0x6F, 0x64, 0x65, 0x3F, 0x0D, 0x0A, 0x0D, 0x0A, 0x2F, 0x5B],
        )
        self.assertEqual(
            list(text_builders.build_text_command_payload("onRB?")),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x09, 0x6F, 0x6E, 0x52, 0x42, 0x3F, 0x0D, 0x0A, 0x0D, 0x0A, 0x1A, 0x60],
        )

    def test_text_setter_builder_bytes_are_pinned(self) -> None:
        self.assertEqual(
            list(text_builders.build_text_command_payload("onRB=", "1")),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x0A, 0x6F, 0x6E, 0x52, 0x42, 0x3D, 0x31, 0x0D, 0x0A, 0x0D, 0x0A, 0x4A, 0x40],
        )

    def test_text_response_decode_normalizes_ascii_once(self) -> None:
        self.assertEqual(text_builders.decode_text_command_response(list(b"ver:1.2.3\r\n")), "ver:1.2.3")
        self.assertEqual(text_builders.decode_text_command_response(list(b"  ver:1.2.3 \r\n")), "ver:1.2.3")
        self.assertIsNone(text_builders.decode_text_command_response([0xFF, 0xFE, 0xFD]))

    def test_text_builder_rejects_invalid_command_or_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty"):
            text_builders.build_text_command_payload("")
        with self.assertRaisesRegex(ValueError, "requires a value"):
            text_builders.build_text_command_payload("onRB=")
        with self.assertRaisesRegex(ValueError, "does not accept a value"):
            text_builders.build_text_command_payload("ver?", "1")

    def test_controller_supported_manual_text_catalog_exists(self) -> None:
        controller = FirmwareIntegrationController()
        names = [definition.name for definition in controller.manual_text_command_definitions()]

        self.assertEqual(len(names), 70)
        self.assertEqual(names[:4], ["Version Query", "UART Status Query", "Operating Mode Query", "Robot Power Query"])
        self.assertIn("Robot Power Set", names)
        for definition in controller.manual_text_command_definitions():
            self.assertEqual(definition.mode, "text")
            self.assertIsNotNone(definition.text_command)
            self.assertIsNotNone(definition.expected_response)
            self.assertIsNotNone(definition.execution_policy)
            self.assertIsNotNone(definition.category)

    def test_controller_uses_canonical_text_builder_and_bridge_send_once(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        sent_events: list[dict[str, object]] = []
        controller.manual_text_sent.connect(sent_events.append)

        with patch(
            "gui.workspace.controllers.firmware_integration_controller.build_text_command_payload",
            wraps=text_builders.build_text_command_payload,
        ) as build_payload:
            self.assertTrue(controller.send_manual_text_command("Version Query"))

        self.assertTrue(controller.has_pending_manual_text_request())
        build_payload.assert_called_once_with("ver?", None)
        self.assertEqual(len(bridge._runtime_window.backend_client.writes), 1)
        self.assertEqual(
            list(bridge._runtime_window.backend_client.writes[0]),
            [0x25, 0xA5, 0x01, 0x01, 0x31, 0x08, 0x76, 0x65, 0x72, 0x3F, 0x0D, 0x0A, 0x0D, 0x0A, 0xF5, 0x19],
        )
        self.assertEqual(sent_events[-1]["command_text"], "ver?")

    def test_controller_disconnected_text_send_fails_cleanly(self) -> None:
        bridge = _FakeBridge(connected=False)
        controller = FirmwareIntegrationController(bridge)
        statuses: list[str] = []
        controller.status_changed.connect(statuses.append)

        self.assertFalse(controller.send_manual_text_command("Version Query"))
        self.assertEqual(bridge._runtime_window.backend_client.writes, [])
        self.assertIn("Serial port not connected.", statuses[-1])

    def test_controller_rejects_second_send_while_text_or_binary_pending(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        statuses: list[str] = []
        controller.status_changed.connect(statuses.append)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertFalse(controller.send_manual_text_command("UART Status Query"))
        self.assertIn("already pending", statuses[-1])

        controller.cancel_active_operation()
        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertFalse(controller.send_manual_text_command("Version Query"))
        self.assertIn("already pending", statuses[-1])

    def test_matching_prefix_completes_request_and_computes_latency(self) -> None:
        now = [100.0]
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge, clock=lambda: now[0])
        results: list[dict[str, object]] = []
        controller.manual_text_result.connect(results.append)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        now[0] = 100.025
        bridge._runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 1,
                "raw_payload": list(b"ver:1.2.3\r\n"),
            }
        )

        self.assertIsNone(controller.pending_manual_text_request)
        self.assertEqual(results[-1]["status"], "PASS")
        self.assertEqual(results[-1]["response_text"], "ver:1.2.3")
        self.assertAlmostEqual(float(results[-1]["latency_ms"]), 25.0, delta=0.001)

    def test_wrong_prefix_and_malformed_ascii_are_ignored_safely(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        results: list[dict[str, object]] = []
        controller.manual_text_result.connect(results.append)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        bridge._runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 1,
                "raw_payload": list(b"uartstat:ok\r\n"),
            }
        )
        bridge._runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 1,
                "raw_payload": [0xFF, 0xFE, 0xFD],
            }
        )

        self.assertTrue(controller.has_pending_manual_text_request())
        self.assertEqual(results, [])

    def test_timeout_and_cancellation_clear_pending_and_detach_adapter(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        runtime_window = bridge.get_runtime_window(create_if_missing=False)
        baseline = runtime_window.receivers(runtime_window.packet_received)
        results: list[dict[str, object]] = []
        controller.manual_text_result.connect(results.append)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.handle_timeout()
        self.assertEqual(results[-1]["status"], "TIMEOUT")
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.cancel_active_operation()
        self.assertEqual(results[-1]["status"], "CANCELLED")
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

    def test_adapter_ignores_packets_without_pending_or_wrong_type_and_forwards_direct_uart_without_prefix_policy(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        controller = _TextAdapterProbeController(pending=False)
        adapter = FirmwareTransportAdapter(controller)
        adapter.attach(runtime_window)

        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"ver:1.2.3\r\n")})
        self.assertEqual(controller.forwarded_packets, [])

        controller.pending = True
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})
        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"uartstat:ok\r\n")})
        runtime_window.packet_received.emit({"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"ver:1.2.3\r\n")})

        self.assertEqual(len(controller.forwarded_packets), 2)
        self.assertEqual(controller.forwarded_packets[0]["raw_payload"], list(b"uartstat:ok\r\n"))
        self.assertEqual(controller.forwarded_packets[1]["raw_payload"], list(b"ver:1.2.3\r\n"))
        self.assertFalse(hasattr(adapter, "_timeout_timer"))
        self.assertFalse(hasattr(adapter, "_pending_manual_text_request"))

    def test_binary_text_pending_states_do_not_cross_complete(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        text_results: list[dict[str, object]] = []
        binary_results: list[dict[str, object]] = []
        controller.manual_text_result.connect(text_results.append)
        controller.manual_binary_result.connect(binary_results.append)

        self.assertTrue(controller.send_manual_text_command("Version Query"))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]}
        )
        self.assertTrue(controller.has_pending_manual_text_request())
        self.assertEqual(text_results, [])
        self.assertEqual(binary_results, [])

        controller.cancel_active_operation()
        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        bridge._runtime_window.packet_received.emit(
            {"status": "ok", "type": "direct_uart", "node_id": 1, "raw_payload": list(b"ver:1.2.3\r\n")}
        )
        self.assertTrue(controller.has_pending_manual_binary_request())
        self.assertEqual(binary_results, [])

    def test_firmware_ui_contains_no_text_builder_or_packet_subscription_logic(self) -> None:
        source = inspect.getsource(firmware_sections_module)

        self.assertNotIn("text_cmd_builders", source)
        self.assertNotIn("build_text_command_payload", source)
        self.assertNotIn("decode_text_command_response", source)
        self.assertNotIn("packet_received", source)
        self.assertNotIn("backend_client", source)

    def test_no_public_manual_text_controller_and_no_legacy_widget_import(self) -> None:
        controller_sources = []
        for path in Path("gui/workspace/controllers").glob("*.py"):
            controller_sources.append(path.read_text(encoding="utf-8"))
        all_controller_source = "\n".join(controller_sources)

        self.assertNotIn("class ManualTextController", all_controller_source)
        self.assertNotIn("class TextCommandController", all_controller_source)
        self.assertNotIn("legacy_reference.firmware_integration_test", sys.modules)

    def test_controller_source_contains_no_independent_raw_text_decode(self) -> None:
        source = inspect.getsource(FirmwareIntegrationController)
        self.assertNotIn(".decode(", source)


if __name__ == "__main__":
    unittest.main()
