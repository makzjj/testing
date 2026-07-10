from __future__ import annotations

import dataclasses
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

import data.binary_cmd_builders as binary_builders
import data.binary_cmd_parser as binary_parser
import gui.workspace.dialogs.manual_binary_command_dialog as manual_binary_dialog_module
from gui.workspace.bridges import WorkspaceRuntimeBridge
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.dialogs.manual_binary_command_dialog import ManualBinaryCommandDialog
from gui.workspace.models import FirmwareCommandDefinition
from gui.workspace.pages.firmware_page import FirmwarePage
from myconfig.project_models import ProjectDefinition
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
                }
            }
        }
        self._runtime_window = _FakeRuntimeWindow(connected=connected)

    def get_firmware_node_options(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return [(3, "X"), (12, "Z")]

    def get_runtime_connection_state(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self._runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        return self._runtime_window.backend_client.send_command_bytes(node_id, payload)

    def get_frame_loss_items(self) -> list[object]:
        return []


class _AdapterProbeController:
    def __init__(self, *, expected_node: int = 3, expected_cmd: int = 0xC8, pending: bool = True) -> None:
        self.expected_node = expected_node
        self.expected_cmd = expected_cmd
        self.pending = pending
        self.forwarded_packets: list[dict[str, object]] = []

    def has_pending_manual_binary_request(self) -> bool:
        return self.pending

    def accepts_manual_binary_packet(self, *, sender: int | None, cmd: int | None, params: list[int] | None = None) -> bool:
        _ = params
        return sender == self.expected_node and cmd == self.expected_cmd

    def handle_runtime_packet(self, packet: object) -> None:
        if isinstance(packet, dict):
            self.forwarded_packets.append(packet)


class FirmwareManualBinaryArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_adapter_attach_and_detach_are_idempotent(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        controller = _AdapterProbeController()
        adapter = FirmwareTransportAdapter(controller)

        baseline = runtime_window.receivers(runtime_window.packet_received)
        adapter.attach_runtime_window(runtime_window)
        first_count = runtime_window.receivers(runtime_window.packet_received)
        adapter.attach_runtime_window(runtime_window)
        second_count = runtime_window.receivers(runtime_window.packet_received)

        self.assertEqual(first_count, baseline + 1)
        self.assertEqual(second_count, first_count)

        adapter.detach_runtime_window()
        after_first_detach = runtime_window.receivers(runtime_window.packet_received)
        adapter.detach_runtime_window()
        after_second_detach = runtime_window.receivers(runtime_window.packet_received)

        self.assertEqual(after_first_detach, baseline)
        self.assertEqual(after_second_detach, baseline)

    def test_controller_detaches_adapter_after_response_timeout_and_cancel(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        runtime_window = bridge.get_runtime_window(create_if_missing=False)
        baseline = runtime_window.receivers(runtime_window.packet_received)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.handle_runtime_packet({"sender": 3, "cmd": 0xC8, "params": [0x3A, 0x12, 0x30, 0x01]})
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.handle_timeout()
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        self.assertTrue(controller.send_manual_binary_command(node_id=3, command_name="GETVER"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        controller.cancel_active_operation()
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

    def test_repeated_dialog_open_close_does_not_duplicate_subscriptions(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        runtime_window = bridge.get_runtime_window(create_if_missing=False)
        baseline = runtime_window.receivers(runtime_window.packet_received)

        page._open_manual_binary_dialog()
        self._app.processEvents()
        dialog = page._manual_binary_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        dialog.close()
        self._app.processEvents()
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

        page._open_manual_binary_dialog()
        self._app.processEvents()
        dialog = page._manual_binary_dialog
        self.assertIsNotNone(dialog)
        assert dialog is not None
        dialog.command_combo.setCurrentText("GETVER")
        dialog.node_combo.setCurrentIndex(0)
        dialog.send_button.click()
        self._app.processEvents()
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline + 1)
        dialog.close()
        self._app.processEvents()
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), baseline)

    def test_adapter_owns_no_pending_timeout_or_latency_state(self) -> None:
        adapter = FirmwareTransportAdapter(_AdapterProbeController())

        self.assertFalse(hasattr(adapter, "_pending_manual_binary_request"))
        self.assertFalse(hasattr(adapter, "_timeout_timer"))
        self.assertFalse(hasattr(adapter, "_latency_ms"))

    def test_firmware_command_definition_remains_metadata_only(self) -> None:
        definition = FirmwareCommandDefinition(
            name="GETVER",
            mode="binary",
            opcode=0xC8,
            parameter_schema={"kind": "none"},
            expected_response="firmware",
            timeout_ms=1500,
            builder_name="build_getver_query_payload",
            decoder_name="decode_command",
        )

        self.assertTrue(dataclasses.is_dataclass(definition))
        for field in dataclasses.fields(definition):
            value = getattr(definition, field.name)
            self.assertNotIsInstance(value, QObject)
            self.assertFalse(hasattr(value, "send_command_bytes"))
            self.assertFalse(hasattr(value, "packet_received"))

    def test_dialog_contains_no_direct_protocol_or_backend_ownership(self) -> None:
        source = inspect.getsource(manual_binary_dialog_module)

        self.assertNotIn("backend_client", source)
        self.assertNotIn("send_command_bytes", source)
        self.assertNotIn("packet_received", source)
        self.assertNotIn("decode_command", source)
        self.assertNotIn("binary_cmd_builders", source)
        self.assertNotIn("binary_cmd_parser", source)

    def test_dialog_send_and_raw_hex_delegate_to_controller_only(self) -> None:
        bridge = _FakeBridge()
        controller = FirmwareIntegrationController(bridge)
        dialog = ManualBinaryCommandDialog(controller)
        calls: list[dict[str, object]] = []

        def _fake_send_manual_binary_command(**kwargs) -> bool:
            calls.append(dict(kwargs))
            return False

        controller.send_manual_binary_command = _fake_send_manual_binary_command  # type: ignore[method-assign]

        dialog.node_combo.setCurrentIndex(0)
        dialog.command_combo.setCurrentIndex(0)
        dialog.send_button.click()
        dialog.raw_hex_toggle.setChecked(True)
        dialog.raw_hex_input.setPlainText("C8 3F")
        dialog.send_button.click()

        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["command_name"], "GETVER")
        self.assertFalse(calls[0]["use_raw_hex"])
        self.assertTrue(calls[1]["use_raw_hex"])
        self.assertEqual(calls[1]["raw_hex_text"], "C8 3F")

    def test_supported_commands_map_to_canonical_builders_and_decoders(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = {definition.name: definition for definition in controller.manual_binary_command_definitions()}
        controller_source = inspect.getsource(FirmwareIntegrationController)
        self.assertNotIn("def _build_payload(", controller_source)
        cases = [
            ("GETVER", definitions["GETVER"], binary_builders.build_getver_query_payload(), (0xC8, [0x3A, 0x12, 0x30, 0x01], "firmware")),
            ("GETPOS", definitions["GETPOS"], binary_builders.build_getpos(), (0x82, [0x00, 0x00, 0x00, 0x10], "getpos")),
            ("GETVEL", definitions["GETVEL"], binary_builders.build_getvel_query_payload(), (0x85, [0x00, 0x32], "getvel")),
            ("VEL Write", definitions["VEL Write"], binary_builders.build_vel(30), (0x84, [0x53, 0x00, 0x1E], "velocity_ack")),
            ("RUN", definitions["RUN"], binary_builders.build_run(30), (0x88, [0x53, 0x00, 0x1E], "run_started")),
            ("NODECONFIG Query", definitions["NODECONFIG Query"], binary_builders.build_nodeconfig_query_payload(), (0xC4, [0x3A, 0x00], "nodeconfig")),
            ("INTERRUPT Query", definitions["INTERRUPT Query"], binary_builders.build_interrupt_query_payload(), (0xD8, [0x3A, 0x01, 0x00], "interrupt")),
            ("MOTOR_I Query", definitions["MOTOR_I Query"], binary_builders.build_motor_current_query_payload(), (0xCF, [0x3A, 0x04, 0xD2], "motor_current_mA")),
        ]

        for name, definition, expected_payload, decode_case in cases:
            with self.subTest(command=name):
                self.assertEqual(definition.decoder_name, "decode_command")
                payload = controller._build_binary_payload(
                    definition,
                    definition.parameter_schema.get("default") if definition.parameter_schema else None,
                )
                self.assertEqual(payload, expected_payload)
                decode_kind, _decoded_value = binary_parser.decode_command(decode_case[0], decode_case[1])
                self.assertEqual(decode_kind, decode_case[2])

    def test_bridge_send_helper_is_thin_delegation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            payload = [0xC8, 0x3F]
            backend_calls: list[tuple[int, list[int]]] = []

            class _Backend:
                def is_connected(self) -> bool:
                    return True

                def send_command_bytes(self, node_id: int, command_bytes: list[int]) -> bytearray:
                    backend_calls.append((node_id, command_bytes))
                    return bytearray(command_bytes)

            runtime_window = SimpleNamespace(backend_client=_Backend())

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                response = bridge.send_firmware_binary_command(8, payload)

            self.assertEqual(len(backend_calls), 1)
            self.assertEqual(backend_calls[0][0], 8)
            self.assertIs(backend_calls[0][1], payload)
            self.assertEqual(list(response), payload)


if __name__ == "__main__":
    unittest.main()
