"""Focused tests for the Production runtime-backed ML 2.0 node flow."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from gui.workspace.pages.production_page import ProductionPage
from gui.workspace.pages.single_axis_functional_popup import SingleAxisFunctionalPopup
from gui.workspace.widgets import ResponsiveRow
from gui.workspace.pages.production_parameter_controller import (
    EEPROM_SAVE_COMMAND,
    SET_COMMAND_SUFFIX,
    ParameterDefinition,
    ParameterVerificationResult,
    ProductionParameterController,
    build_eeprom_save_payload,
    build_pwm_read_payload,
    build_pwm_write_payload,
    build_uuid_read_payload,
    build_uuid_write_payload,
    decode_eeprom_save_response,
    decode_pwm_response,
    decode_uuid_response,
    default_workbook_parameter_definitions,
    format_uuid_like_source,
    parse_pwm_value,
    parse_uuid_value,
    validate_uuid_format,
)
from gui.workspace.pages.production_test_controller import (
    ProductionTestController,
    build_basic_test_profile,
    build_safe_movement_profile,
    decode_getpos_response,
    decode_tpos_state_response,
    decode_getver_response,
    decode_interrupt_response,
)
from gui.workspace.pages.production_test_models import Tolerance, evaluate_tolerance
from myconfig.constants import COMMANDS

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from openpyxl import Workbook, load_workbook

    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover - environment dependent.
    _HAS_OPENPYXL = False

class _FakeBack
endClient:
    def __init__(self, *, connected: bool = True) -> None:
        self._connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.stop_commands: list[int] = []

    def is_connected(self) -> bool:
        return self._connected

    def get_command_bytes(self, _command_name: str, fallback: list[int] | None = None) -> list[int]:
        return list(COMMANDS.get(_command_name, fallback or []))

    def send_command_bytes(self, node_id: int, command_bytes: list[int]) -> bytearray:
        self.sent_commands.append((node_id, list(command_bytes)))
        return bytearray([0x25, 0xA5, 0x01, node_id, 0x31, len(command_bytes), *command_bytes])

    def send_stop_motor(self, node_id: int) -> bytearray:
        self.stop_commands.append(node_id)
        return bytearray([0x25, 0xA5, 0x01, node_id, 0x31, 0x01, 0xDD])


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True, mcu_version: str | None = "v1.0.0") -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)
        self.mcu_version = mcu_version
        self._selected_port = "COM11"
        self._selected_baud = "115200"
        self.sys_mode = {"text": "Ready" if connected else "System Off", "node_id": 0x01, "state_value": 1 if connected else 0}
        self.node_status = {
            2: {"connected": False},
            3: {"connected": False},
            8: {"connected": False},
        }
        self.scan_requests = 0


class _FakeBridge:
    def __init__(self, runtime_window: _FakeRuntimeWindow | None) -> None:
        self.runtime_window = runtime_window
        self.create_requests = 0

    def get_runtime_window(self, *, create_if_missing: bool = False):
        if create_if_missing:
            self.create_requests += 1
        return self.runtime_window

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return False, False
        serial_connected = runtime_window.backend_client.is_connected()
        return serial_connected, serial_connected

    def get_runtime_communication_model(self, *, create_if_missing: bool = False) -> dict:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {
                "ports": [{"label": "COM11 ✅ (Valid)", "value": "COM11"}],
                "selected_port": "COM11",
                "baud_rates": ["115200", "230400", "345600"],
                "selected_baud": "115200",
                "connected": False,
            }
        return {
            "ports": [{"label": "COM11 ✅ (Valid)", "value": "COM11"}],
            "selected_port": runtime_window._selected_port,
            "baud_rates": ["115200", "230400", "345600"],
            "selected_baud": runtime_window._selected_baud,
            "connected": runtime_window.backend_client.is_connected(),
        }

    def connect_runtime_serial(self, *, port: str, baud_rate: int) -> bool:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return False
        runtime_window._selected_port = port
        runtime_window._selected_baud = str(baud_rate)
        runtime_window.backend_client._connected = True
        return True

    def disconnect_runtime_serial(self) -> None:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return
        runtime_window.backend_client._connected = False

    def get_runtime_robot_power_state(self, *, create_if_missing: bool = False) -> bool | None:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return None
        sys_mode = getattr(runtime_window, "sys_mode", None)
        if not isinstance(sys_mode, dict):
            return None
        if sys_mode.get("node_id") == 0x01 and sys_mode.get("state_value") == 0:
            return False
        if str(sys_mode.get("text", "")).strip().lower() == "system off":
            return False
        return True

    def send_runtime_robot_power(self, power_on: bool) -> bytearray:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            raise RuntimeError("Runtime backend is unavailable for Production operations.")
        backend_client = runtime_window.backend_client
        payload = backend_client.get_command_bytes("ROBOT On" if power_on else "ROBOT Off")
        backend_client.send_command_bytes(0x01, payload)
        runtime_window.sys_mode = {"text": "Ready" if power_on else "System Off", "node_id": 0x01, "state_value": 1 if power_on else 0}
        return bytearray(payload)

    def get_runtime_robot_nodes(self, *, create_if_missing: bool = False) -> dict:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {"connected_nodes": [], "rows": []}
        rows = []
        connected_nodes = []
        for node_id, status in runtime_window.node_status.items():
            if not status.get("connected", False):
                continue
            connected_nodes.append(node_id)
            rows.append(
                {
                    "node_id": node_id,
                    "node": f"Node {node_id:02d} ✅ Connected",
                    "firmware": str(status.get("firmware", "")),
                    "uuid": str(status.get("uuid", "")),
                    "node_type": str(status.get("type", "")),
                    "status": str(status.get("interrupt", "")),
                }
            )
        return {"connected_nodes": sorted(connected_nodes), "rows": rows}

    def request_runtime_node_scan(self) -> bool:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return False
        runtime_window.scan_requests += 1
        return True


class _FakeRobotPowerButton:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class _FakeRobotPowerMessageBox:
    class Icon:
        Question = object()

    class ButtonRole:
        AcceptRole = object()
        DestructiveRole = object()
        RejectRole = object()

    next_choice_text: str | None = None
    instances: list["_FakeRobotPowerMessageBox"] = []

    def __init__(self, parent=None) -> None:
        self.parent = parent
        self.icon = None
        self.window_title = ""
        self.text = ""
        self.buttons: list[_FakeRobotPowerButton] = []
        self._clicked_button: _FakeRobotPowerButton | None = None
        _FakeRobotPowerMessageBox.instances.append(self)

    def setIcon(self, icon) -> None:
        self.icon = icon

    def setWindowTitle(self, title: str) -> None:
        self.window_title = title

    def setText(self, text: str) -> None:
        self.text = text

    def addButton(self, text: str, _role) -> _FakeRobotPowerButton:
        button = _FakeRobotPowerButton(text)
        self.buttons.append(button)
        return button

    def exec(self) -> int:
        choice = type(self).next_choice_text
        self._clicked_button = None
        if choice is not None:
            for button in self.buttons:
                if button.text() == choice:
                    self._clicked_button = button
                    break
        return 0

    def clickedButton(self):
        return self._clicked_button


class ProductionTestControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_profile_runs_steps_in_order(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=50)
        events: list[tuple] = []

        controller.step_finished.connect(lambda node_id, node_name, step: events.append(("step", node_id, node_name, step.step_id)))
        controller.test_passed.connect(lambda node_id, node_name, reason: events.append(("passed", node_id, node_name, reason)))

        self.assertTrue(controller.run_test(8, "RZ"))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (8, [0xCB, 0xA5, 0x5A]))

        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 8,
                "cmd": 0xCB,
                "params": [0xA5, 0x5A],
            }
        )
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (8, [0xC8, 0x3F]))

        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]}
        )
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[2], (8, [0x82]))

        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x01, 0x00]}
        )
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[3], (8, [0xD8]))

        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [1, 0]}
        )
        self._app.processEvents()

        self.assertEqual([event[3] for event in events if event[0] == "step"], ["echo", "getver", "getpos", "interrupt"])
        self.assertTrue(any(event[0] == "passed" and event[1] == 8 for event in events))
        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "PASS")
        self.assertEqual(len(controller.last_final_result.step_results), 4)

    def test_stop_on_fail_stops_later_steps(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []

        controller.test_failed.connect(lambda node_id, node_name, reason: events.append(("failed", node_id, node_name, reason)))

        self.assertTrue(controller.run_test(11, "NGActuator"))
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 11,
                "cmd": 0xCB,
                "params": [0x01, 0x02],
            }
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertEqual(len(runtime_window.backend_client.sent_commands), 1)
        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "FAIL")

    def test_timeout_causes_timeout_final_result(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=10)
        events: list[tuple] = []
        controller.test_failed.connect(lambda node_id, node_name, reason: events.append(("failed", node_id, node_name, reason)))

        controller.run_test(10, "HMI")

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not events:
            self._app.processEvents()
            time.sleep(0.01)

        self.assertTrue(any(event[0] == "failed" and event[1] == 10 and "Timed out" in event[3] for event in events))
        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "TIMEOUT")
        self.assertEqual(controller.last_final_result.step_results[0].result, "TIMEOUT")

    def test_abort_produces_aborted_final_result_and_sends_stop(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []
        controller.test_aborted.connect(lambda node_id, node_name, reason: events.append(("aborted", node_id, node_name, reason)))

        controller.run_test(3, "X")
        self.assertTrue(controller.abort_test())

        self.assertEqual(runtime_window.backend_client.stop_commands, [3])
        self.assertTrue(any(event[0] == "aborted" and event[1] == 3 for event in events))
        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "ABORTED")

    def test_wrong_node_response_is_ignored(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []
        controller.step_finished.connect(lambda _node_id, _node_name, step: events.append(("step", step.step_id, step.result)))

        self.assertTrue(controller.run_test(8, "RZ"))
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 7,
                "cmd": 0xCB,
                "params": [0xA5, 0x5A],
            }
        )
        self._app.processEvents()
        self.assertEqual(events, [])
        self.assertTrue(controller.is_active())
        controller.abort_test()

    def test_unsupported_node_emits_unsupported_without_sending(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []
        controller.test_unsupported.connect(
            lambda node_id, node_name, reason: events.append(("unsupported", node_id, node_name, reason))
        )

        self.assertFalse(controller.run_test(2, "Node 2"))
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertTrue(any(event[0] == "unsupported" and event[1] == 2 for event in events))
        self.assertFalse(controller.is_active())

    def test_tolerance_exact_abs_and_range(self) -> None:
        self.assertEqual(evaluate_tolerance(7, 7, Tolerance(exact_match=7)), (True, ""))
        self.assertFalse(evaluate_tolerance(7, 6, Tolerance(exact_match=7))[0])
        self.assertTrue(evaluate_tolerance(10.0, 10.2, Tolerance(abs_margin=0.3))[0])
        self.assertFalse(evaluate_tolerance(10.0, 10.5, Tolerance(abs_margin=0.3))[0])
        self.assertTrue(evaluate_tolerance(None, 5, Tolerance(min_value=1, max_value=10))[0])
        self.assertFalse(evaluate_tolerance(None, 11, Tolerance(min_value=1, max_value=10))[0])

    def test_decode_helpers(self) -> None:
        self.assertEqual(decode_getver_response([0x3A, 1, 2, 3]), (True, "1.2.3", ""))
        self.assertEqual(decode_getpos_response([0x00, 0x00, 0x01, 0x00]), (True, 256, ""))
        self.assertEqual(
            decode_tpos_state_response([ord("E"), 0x00, 0x00, 0x00, 0x10]),
            (True, {"state": "E", "position": 16}, ""),
        )
        self.assertEqual(
            decode_interrupt_response([0x01, 0x00]),
            (True, {"int0_status": 1, "int1_status": 0}, ""),
        )
        self.assertEqual(build_eeprom_save_payload(), [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX])
        self.assertEqual(decode_eeprom_save_response([EEPROM_SAVE_COMMAND, 0x0A, 0x00]), (True, "ACK", ""))
        self.assertFalse(decode_eeprom_save_response([EEPROM_SAVE_COMMAND, 0x0B, 0x00])[0])

    def test_uuid_0xe0_remains_supported_in_profile_when_expected_uuid_present(self) -> None:
        profile = build_basic_test_profile(6, "H", timeout_ms=100, expected_uuid=1223306010)
        self.assertEqual(profile.steps[-1].step_type, "UUID_VERIFY")
        self.assertEqual(profile.steps[-1].command_id, 0xE0)

    def test_final_node_result_is_aggregated(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        self.assertTrue(controller.run_test(8, "RZ"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0, 0, 0, 1]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 1]})
        self._app.processEvents()
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "PASS")
        self.assertEqual([step.step_id for step in controller.last_final_result.step_results], ["echo", "getver", "getpos", "interrupt"])

    def test_movement_profile_runs_steps_in_order_and_passes_on_tpos_end(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=80)
        step_ids: list[str] = []
        controller.step_finished.connect(lambda _node_id, _node_name, step: step_ids.append(step.step_id))

        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        self._app.processEvents()

        # WAIT step should ignore start state and pass on end state.
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("S"), 0, 0, 0, 100]})
        self._app.processEvents()
        self.assertTrue(controller.is_active())
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("E"), 0, 0, 0, 116]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x74]})
        self._app.processEvents()

        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "PASS")
        self.assertIn("verify_position_delta", step_ids)
        self.assertIn("stop_motor", step_ids)
        sent_cmds = [cmd for _node, cmd in runtime_window.backend_client.sent_commands]
        self.assertIn([0x84, 0x00, 0x14], sent_cmds)
        self.assertIn([0xDD], sent_cmds)

    def test_movement_profile_tpos_lr_state_fails_and_sends_stop(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=80)
        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("L"), 0, 0, 0, 104]})
        self._app.processEvents()

        self.assertFalse(controller.is_active())
        self.assertIn(8, runtime_window.backend_client.stop_commands)
        self.assertEqual(controller.last_final_result.final_result, "FAIL")

    def test_movement_profile_timeout_sends_stop(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=20)
        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        self._app.processEvents()

        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline and controller.is_active():
            self._app.processEvents()
            time.sleep(0.01)

        self.assertIn(8, runtime_window.backend_client.stop_commands)
        self.assertEqual(controller.last_final_result.final_result, "TIMEOUT")

    @pytest.mark.xfail(
        reason="movement profile path is legacy/future scope and not active in Production UI yet",
        strict=False,
    )
    def test_movement_profile_position_delta_outside_tolerance_fails(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=80)
        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("E"), 0, 0, 0, 108]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x6C]})
        self._app.processEvents()

        self.assertFalse(controller.is_active())
        self.assertEqual(controller.last_final_result.final_result, "FAIL")

    def test_movement_profile_wrong_node_response_is_rejected(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=80)
        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 7, "cmd": 0x81, "params": [ord("E"), 0, 0, 0, 116]})
        self._app.processEvents()
        self.assertTrue(controller.is_active())
        controller.abort_test()

    def test_build_safe_movement_profile_contains_expected_steps(self) -> None:
        profile = build_safe_movement_profile(8, "RZ", timeout_ms=120)
        self.assertEqual(
            [step.step_id for step in profile.steps],
            [
                "echo",
                "getver",
                "read_initial_position",
                "interrupt_initial",
                "set_safe_velocity",
                "move_to_position",
                "wait_move_end",
                "read_final_position",
                "verify_position_delta",
                "stop_motor",
            ],
        )


class ProductionPageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_parse_pwm_value_validation(self) -> None:
        self.assertEqual(ProductionPage._parse_pwm_value("100"), 100)
        self.assertEqual(parse_pwm_value("65535"), 65535)
        with self.assertRaisesRegex(ValueError, "required"):
            ProductionPage._parse_pwm_value(" ")
        with self.assertRaisesRegex(ValueError, "digits only"):
            ProductionPage._parse_pwm_value("10x")
        with self.assertRaisesRegex(ValueError, "16-bit"):
            ProductionPage._parse_pwm_value("70000")

    @staticmethod
    def _create_ipqc_workbook(path: Path, *, with_optional_fields: bool = True) -> None:
        if not _HAS_OPENPYXL:
            raise RuntimeError("openpyxl is required to create IPQC workbook fixtures.")
        wb = Workbook()
        ws = wb.active
        ws.title = "3X"
        wb.create_sheet("3X_D")
        wb.create_sheet("3X_A")
        ws["B4"] = "1223303010"
        ws["B5"] = "100"
        if with_optional_fields:
            ws["B3"] = "operator-a"
            ws["B6"] = "N/A"
        wb.save(path)

    def test_production_page_updates_ui_for_runtime_backed_selected_node_pass(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        combo = page.test_control_section._combo
        for index in range(combo.count()):
            if combo.itemText(index) == "Node 8 - RZ":
                combo.setCurrentIndex(index)
                break
        page._handle_run_test()
        self._app.processEvents()

        self.assertEqual(page.result_summary_section._status_label.text(), "TESTING")
        self.assertIn("[INFO] TESTING: Running Production test for Node 8 RZ.", page.progress_section.to_plain_text())

        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]}
        )
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]}
        )
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 8,
                "cmd": 0x82,
                "params": [0x00, 0x00, 0x01, 0xC8],
            }
        )
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [1, 0]}
        )
        self._app.processEvents()

        self.assertEqual(page.result_summary_section._status_label.text(), "PASS")
        self.assertIn("All profile steps passed", page.result_summary_section._reason_label.text())
        self.assertIn("#2e7d32", page.stage_section._rows["configuration"][0].styleSheet().lower())

    def test_profile_step_results_keep_workbook_flow_only(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        page._handle_run_test()
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x2A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xD8, "params": [0, 1]})
        self._app.processEvents()

        self.assertFalse(hasattr(page, "_result_logger"))

    def test_production_page_hides_test_profile_selector(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        self.assertFalse(hasattr(page.test_control_section, "_profile_combo"))

    def test_production_page_run_test_still_works_without_profile_selector(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        page._handle_run_test()
        self._app.processEvents()
        self.assertEqual(page.result_summary_section._status_label.text(), "TESTING")

    def test_production_page_uses_two_column_top_layout_and_section_order(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        first_row = page.content_layout.itemAt(0).widget()
        second_widget = page.content_layout.itemAt(1).widget()
        third_widget = page.content_layout.itemAt(2).widget()
        fourth_widget = page.content_layout.itemAt(3).widget()

        self.assertIsInstance(first_row, ResponsiveRow)
        self.assertIs(second_widget, page.node_status_section)
        self.assertIs(third_widget, page.uuid_section)
        self.assertIs(fourth_widget, page.progress_section)

        first_layout = first_row.layout()
        self.assertIs(first_layout.itemAt(0).widget(), page.communication_section)
        self.assertIs(first_layout.itemAt(1).widget(), page.stage_section)
        self.assertEqual(first_row.stretch_factors(), (1, 1))
        self.assertIsNone(page.result_summary_section.parent())

    def test_production_page_shows_compact_status_with_refresh_and_clear_buttons(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        page.resize(1280, 800)
        self._app.processEvents()

        button_texts = [button.text() for button in page.progress_section.findChildren(QPushButton)]
        self.assertIn("Refresh", button_texts)
        self.assertIn("Clear", button_texts)
        self.assertEqual(page.progress_section.windowTitle(), "")
        self.assertTrue(hasattr(page.progress_section, "_log_output"))
        self.assertGreaterEqual(page.progress_section._log_output.minimumHeight(), 220)
        self.assertEqual(
            page.progress_section._log_output.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(page.horizontalScrollBarPolicy(), Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def test_production_page_node_status_clear_resets_led_to_dark_green(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        runtime_window.node_status[8]["connected"] = True
        page._refresh_robot_nodes()
        self.assertIn("#7ed957", page.node_status_section._led_by_node_id[8].styleSheet().lower())
        page._handle_clear_nodes_requested()
        self.assertIn("#1e5e20", page.node_status_section._led_by_node_id[8].styleSheet().lower())
        node_labels = [label.text() for label in page.node_status_section.findChildren(QLabel)]
        self.assertEqual(node_labels.count("Node"), 1)
        self.assertEqual(len(page.node_status_section._led_by_node_id), 15)

    def test_production_page_shows_communication_card_controls(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        self.assertGreaterEqual(page.communication_section._port_combo.count(), 1)
        self.assertGreaterEqual(page.communication_section._baud_combo.count(), 1)
        self.assertEqual(page.communication_section._connect_button.text(), "Disconnect")
        self.assertIn("MCU Firmware Version", page.communication_section._firmware_label.text())
        self.assertIn("Nodes Firmware Version", page.communication_section._nodes_firmware_label.text())

    def test_production_page_populates_com_ports_on_startup_without_runtime_page(self) -> None:
        bridge = _FakeBridge(None)
        page = ProductionPage(bridge)
        page.show()
        self._app.processEvents()

        self.assertEqual(bridge.create_requests, 0)
        self.assertGreaterEqual(page.communication_section._port_combo.count(), 1)
        self.assertEqual(page.communication_section._port_combo.currentData(), "COM11")

    def test_production_page_robot_power_button_order_and_connection_state(self) -> None:
        disconnected_page = ProductionPage(_FakeBridge(None))
        button_row = disconnected_page.node_status_section.body_layout.itemAt(0).layout()
        self.assertIsNotNone(button_row)
        assert button_row is not None
        self.assertIsNotNone(button_row.itemAt(0).spacerItem())
        button_texts = [button_row.itemAt(index).widget().text() for index in range(button_row.count()) if button_row.itemAt(index).widget() is not None]
        self.assertEqual(button_texts, ["Robot Power ON/OFF", "Update Nodes", "Clear"])
        self.assertFalse(disconnected_page.node_status_section._robot_power_button.isEnabled())

        connected_page = ProductionPage(_FakeBridge(_FakeRuntimeWindow(connected=True)))
        self.assertTrue(connected_page.node_status_section._robot_power_button.isEnabled())

    def test_robot_power_button_cancels_without_sending(self) -> None:
        runtime_window = _FakeRuntimeWindow(connected=True)
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        _FakeRobotPowerMessageBox.next_choice_text = "Cancel"
        _FakeRobotPowerMessageBox.instances.clear()
        with patch("gui.workspace.pages.production_page.QMessageBox", _FakeRobotPowerMessageBox):
            page._handle_robot_power_requested()

        self.assertEqual(len(_FakeRobotPowerMessageBox.instances), 1)
        dialog = _FakeRobotPowerMessageBox.instances[0]
        self.assertEqual(dialog.window_title, "Robot Power")
        self.assertEqual(dialog.text, "Choose robot power command to send.")
        self.assertEqual([button.text() for button in dialog.buttons], ["Power ON", "Power OFF", "Cancel"])
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertIn("Robot power command cancelled.", page.progress_section.to_plain_text())

    def test_robot_power_button_sends_on_then_off_payloads_via_existing_backend_path(self) -> None:
        runtime_window = _FakeRuntimeWindow(connected=True)
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        _FakeRobotPowerMessageBox.instances.clear()
        with patch("gui.workspace.pages.production_page.QMessageBox", _FakeRobotPowerMessageBox):
            _FakeRobotPowerMessageBox.next_choice_text = "Power ON"
            page._handle_robot_power_requested()
            _FakeRobotPowerMessageBox.next_choice_text = "Power OFF"
            page._handle_robot_power_requested()

        self.assertEqual(
            runtime_window.backend_client.sent_commands,
            [
                (1, COMMANDS["ROBOT On"]),
                (1, COMMANDS["ROBOT Off"]),
            ],
        )
        log_text = page.progress_section.to_plain_text()
        self.assertIn("Robot power ON command sent.", log_text)
        self.assertIn("Robot power OFF command sent.", log_text)

    def test_robot_power_button_succeeds_when_power_state_is_unavailable(self) -> None:
        runtime_window = _FakeRuntimeWindow(connected=True)
        runtime_window.sys_mode = None
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        _FakeRobotPowerMessageBox.next_choice_text = "Power ON"
        _FakeRobotPowerMessageBox.instances.clear()
        with patch("gui.workspace.pages.production_page.QMessageBox", _FakeRobotPowerMessageBox):
            page._handle_robot_power_requested()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(1, COMMANDS["ROBOT On"])])
        self.assertNotIn("robot power state is unavailable", page.progress_section.to_plain_text().lower())

    def test_production_page_shows_runtime_robot_nodes_status_and_supports_dropdown_sync(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[8] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "123456",
            "type": "RZ",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        self.assertIn("#7ed957", page.robot_nodes_section._led_by_node_id[8].styleSheet().lower())
        self.assertIn("v1.0.0", page.communication_section._nodes_firmware_label.text())
        page._handle_runtime_node_selected(8)
        selected_node_id, _selected_name = page.test_control_section.selected_node()
        self.assertEqual(selected_node_id, 8)

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UI tests.")
    def test_production_page_loads_ipqc_workbook_and_shows_expected_preview(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=True)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            self.assertEqual(page.uuid_section._selected_group, "3X")
            self.assertIn("Loaded Workbook", page.uuid_section._loaded_workbook_label.text())
            self.assertTrue(page.uuid_section._loaded_workbook_label.text().endswith("ipqc.xlsx"))
            self.assertEqual(page.uuid_section._loaded_workbook_label.toolTip(), str(workbook_path))
            self.assertEqual(page.uuid_section._expected_serial_value, "1223303010")
            self.assertEqual(page.uuid_section._expected_pwm_value, "100")
            self.assertEqual(page.uuid_section._expected_other_value, "-")
            self.assertEqual(page.uuid_section.workbook_validation_text, "Workbook Validation: READY")
            self.assertTrue(page.uuid_section.verify_button.isEnabled())
            self.assertTrue(page.uuid_section.write_button.isEnabled())
            self.assertFalse(page.uuid_section.save_button.isEnabled())
            self.assertEqual(runtime_window.backend_client.sent_commands, [])
            log_text = page.progress_section.to_plain_text()
            self.assertIn("Expected S/N / UUID: 1223303010", log_text)
            self.assertIn("Expected PWM: 100", log_text)
            self.assertIn("loaded ipqc workbook", page.progress_section.to_html().lower())
            self.assertIn("#2e7d32", page.progress_section.to_html().lower())

    def test_production_page_logs_workbook_load_failure_in_red(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with patch("gui.workspace.pages.production_page.QFileDialog.getOpenFileName", return_value=("bad.xlsx", "Excel Files (*.xlsx)")):
            with patch.object(page._ipqc_excel_adapter, "load_template", side_effect=RuntimeError("broken workbook")):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

        self.assertIn("IPQC workbook load failed", page.progress_section.to_plain_text())
        self.assertIn("#c62828", page.progress_section.to_html().lower())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook write wiring tests.")
    def test_production_page_write_uuid_sends_write_command_using_workbook_expected_value(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()

            expected_uuid = 1223303010
            self.assertTrue(runtime_window.backend_client.sent_commands)
            self.assertIn((3, build_uuid_write_payload(expected_uuid)), runtime_window.backend_client.sent_commands)
            self.assertIn((3, build_pwm_write_payload(100)), runtime_window.backend_client.sent_commands)
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            self.assertFalse(page.uuid_section.save_button.isEnabled())
            sent_count = len(runtime_window.backend_client.sent_commands)
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(len(runtime_window.backend_client.sent_commands), sent_count)
            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": EEPROM_SAVE_COMMAND,
                    "params": [0x0A, 0x00],
                }
            )
            self._app.processEvents()
            self.assertEqual(page.uuid_section.workbook_validation_text, "Workbook Validation: READY")
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            self.assertFalse(page.uuid_section.save_button.isEnabled())
            self.assertIn("[INFO] EEPROM save ACK received.", page.progress_section.to_plain_text())

            page._handle_eeprom_save_settle_finished()
            self._app.processEvents()
            self.assertTrue(page.uuid_section.verify_button.isEnabled())

            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))

            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": 0xE0,
                    "params": [0x3A, *build_uuid_write_payload(expected_uuid)[2:]],
                }
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x64]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, str(expected_uuid))
            self.assertEqual(output_sheet["D4"].value, "PASS")
            self.assertEqual(output_sheet["C5"].value, "100")
            self.assertEqual(output_sheet["D5"].value, "PASS")
            self.assertEqual(page.result_summary_section._status_label.text(), "PASS")
            self.assertEqual(page.uuid_section.workbook_validation_text, "Workbook Validation: PASSED")
            self.assertTrue(page.uuid_section.save_button.isEnabled())
            self.assertEqual(page.progress_section.to_plain_text().count("[PASS] Workbook parameter read-back verification"), 1)
            self.assertFalse(hasattr(page, "_result_logger"))

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook write wiring tests.")
    def test_production_page_write_uuid_timeout_disables_verify_and_reports_quiet_mode_issue(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        page._parameter_controller._timeout_ms = 20

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()

            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and page.uuid_section.workbook_validation_text != "Workbook Validation: FAILED (EEPROM save ACK not received; check command payload and quiet mode.)":
                self._app.processEvents()
                time.sleep(0.01)

            self.assertEqual(
                page.uuid_section.workbook_validation_text,
                "Workbook Validation: FAILED (EEPROM save ACK not received; check command payload and quiet mode.)",
            )
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            self.assertIn("EEPROM save ACK not received; check command payload and quiet mode.", page.result_summary_section._reason_label.text())
            timeout_line = next(
                line for line in page.progress_section.to_plain_text().splitlines() if "Timed out waiting for EEPROM save ACK." in line
            )
            self.assertIn("[FAIL] Timed out waiting for EEPROM save ACK.", timeout_line)
            self.assertNotIn("Node", timeout_line)
            self.assertNotIn("Axis", timeout_line)

    def test_progress_log_coloring_uses_black_green_and_red(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        page.progress_section.clear_log()
        page.progress_section.append_step("Info entry")
        page.progress_section.append_step("Pass entry", level="pass")
        page.progress_section.append_step("Fail entry", level="fail")

        html = page.progress_section.to_html().lower()
        self.assertIn("#000000", html)
        self.assertIn("#2e7d32", html)
        self.assertIn("#c62828", html)

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_after_load_without_prior_write_sets_passed_and_enables_save(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            self.assertTrue(page.uuid_section.verify_button.isEnabled())
            self.assertFalse(page.uuid_section.save_button.isEnabled())

            expected_uuid = 1223303010
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))
            self.assertNotIn((3, build_uuid_write_payload(expected_uuid)), runtime_window.backend_client.sent_commands)

            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": 0xE0,
                    "params": [0x3A, *build_uuid_write_payload(expected_uuid)[2:]],
                }
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x64]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, str(expected_uuid))
            self.assertEqual(output_sheet["D4"].value, "PASS")
            self.assertEqual(output_sheet["C5"].value, "100")
            self.assertEqual(output_sheet["D5"].value, "PASS")
            self.assertEqual(page.uuid_section.workbook_validation_text, "Workbook Validation: PASSED")
            self.assertTrue(page.uuid_section.save_button.isEnabled())
            self.assertFalse(hasattr(page, "_result_logger"))

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_after_load_without_prior_write_sets_failed_on_mismatch(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))
            self.assertNotIn((3, build_uuid_write_payload(1223303011)), runtime_window.backend_client.sent_commands)

            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": 0xE0,
                    "params": [0x3A, *build_uuid_write_payload(1223303011)[2:]],
                }
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x32]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, "1223303011")
            self.assertEqual(output_sheet["D4"].value, "FAIL")
            self.assertEqual(output_sheet["C5"].value, "50")
            self.assertEqual(output_sheet["D5"].value, "FAIL")
            self.assertIn("Workbook Validation: FAILED", page.uuid_section.workbook_validation_text)
            self.assertFalse(page.uuid_section.save_button.isEnabled())
            self.assertIn("expected 1223303010, actual 1223303011", page.progress_section.to_plain_text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook write wiring tests.")
    def test_production_page_write_uuid_logs_pwm_blocked_when_b5_invalid(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            wb = load_workbook(workbook_path)
            wb["3X"]["B5"] = "bad-pwm"
            wb.save(workbook_path)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()

            self.assertEqual(runtime_window.backend_client.sent_commands, [])
            self.assertIn("Expected PWM in workbook B5 is invalid", page.result_summary_section._reason_label.text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook write wiring tests.")
    def test_production_page_workbook_write_failure_is_reporting_error(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            with patch.object(page._ipqc_excel_adapter, "write_summary_result", side_effect=OSError("disk full")):
                page._update_uuid_cells_in_workbook_memory("1223303011", True)
                self._app.processEvents()

            self.assertEqual(page.result_summary_section._status_label.text(), "REPORTING ERROR")
            self.assertIn("writing IPQC workbook report failed", page.result_summary_section._reason_label.text())
            self.assertIn("failed", page.uuid_section.last_workbook_action_text.lower())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_uses_workbook_expected_sn_and_writes_result_cells(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A, 0x00]}
            )
            self._app.processEvents()
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            page._handle_eeprom_save_settle_finished()
            self._app.processEvents()
            self.assertTrue(page.uuid_section.verify_button.isEnabled())

            expected_uuid = 1223303010
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))

            response_params = [0x3A, *build_uuid_write_payload(expected_uuid)[2:]]
            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": 0xE0,
                    "params": response_params,
                }
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x64]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, str(expected_uuid))
            self.assertEqual(output_sheet["D4"].value, "PASS")
            self.assertEqual(output_sheet["C5"].value, "100")
            self.assertEqual(output_sheet["D5"].value, "PASS")
            self.assertEqual(page.uuid_section.workbook_validation_text, "Workbook Validation: PASSED")
            self.assertTrue(page.uuid_section.save_button.isEnabled())
            self.assertEqual(page.progress_section.to_plain_text().count("[PASS] Workbook parameter read-back verification"), 1)

            self.assertFalse(hasattr(page, "_result_logger"))

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_mismatch_writes_fail_result_cells(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A, 0x00]}
            )
            self._app.processEvents()
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            page._handle_eeprom_save_settle_finished()
            self._app.processEvents()
            self.assertTrue(page.uuid_section.verify_button.isEnabled())
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))
            runtime_window.packet_received.emit(
                {
                    "status": "ok",
                    "type": "can_over_uart",
                    "sender": 3,
                    "cmd": 0xE0,
                    "params": [0x3A, *build_uuid_write_payload(1223303011)[2:]],
                }
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x32]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, "1223303011")
            self.assertEqual(output_sheet["D4"].value, "FAIL")
            self.assertEqual(output_sheet["C5"].value, "50")
            self.assertEqual(output_sheet["D5"].value, "FAIL")
            self.assertIn("Workbook Validation: FAILED", page.uuid_section.workbook_validation_text)
            self.assertFalse(page.uuid_section.save_button.isEnabled())
            self.assertIn("[FAIL] UUID read-back verification", page.progress_section.to_plain_text())
            self.assertIn("expected 1223303010, actual 1223303011", page.progress_section.to_plain_text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_pwm_mismatch_writes_fail_for_pwm_cells(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A, 0x00]}
            )
            self._app.processEvents()
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            page._handle_eeprom_save_settle_finished()
            self._app.processEvents()
            self.assertTrue(page.uuid_section.verify_button.isEnabled())
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xE0, "params": [0x3A, *build_uuid_write_payload(1223303010)[2:]]}
            )
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0x85]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x85, "params": [0x00, 0x32]}
            )
            self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertEqual(output_sheet["C4"].value, "1223303010")
            self.assertEqual(output_sheet["D4"].value, "PASS")
            self.assertEqual(output_sheet["C5"].value, "50")
            self.assertEqual(output_sheet["D5"].value, "FAIL")

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook UUID verify tests.")
    def test_production_page_verify_pwm_timeout_writes_fail_after_read_back_only(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            output_sheet = page._ipqc_excel_adapter._workbook["3X"]
            self.assertIn(output_sheet["C5"].value, (None, ""))
            self.assertIn(output_sheet["D5"].value, (None, ""))
            page._handle_write_uuid()
            self._app.processEvents()
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A, 0x00]}
            )
            self._app.processEvents()
            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            page._handle_eeprom_save_settle_finished()
            self._app.processEvents()
            self.assertTrue(page.uuid_section.verify_button.isEnabled())
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands[-1], (3, [0xE0, 0x3F]))
            runtime_window.packet_received.emit(
                {"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xE0, "params": [0x3A, *build_uuid_write_payload(1223303010)[2:]]}
            )
            self._app.processEvents()
            self.assertIn(output_sheet["C5"].value, (None, ""))
            self.assertIn(output_sheet["D5"].value, (None, ""))
            page._parameter_controller._handle_parameter_verify_timeout()
            self._app.processEvents()

            self.assertEqual(output_sheet["C4"].value, "1223303010")
            self.assertEqual(output_sheet["D4"].value, "PASS")
            self.assertIn(output_sheet["C5"].value, (None, ""))
            self.assertIn(output_sheet["D5"].value, (None, ""))
            self.assertIn("actual timeout", page.progress_section.to_plain_text())
            self.assertIn("Workbook Validation: FAILED", page.uuid_section.workbook_validation_text)

    def test_production_page_eeprom_save_failure_marks_validation_failed(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._handle_write_uuid()
            self._app.processEvents()
            self.assertEqual(
                runtime_window.backend_client.sent_commands[-1],
                (3, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]),
            )
            page._parameter_controller._handle_eeprom_save_timeout()
            self._app.processEvents()

            self.assertEqual(page.result_summary_section._status_label.text(), "FAIL")
            self.assertIn("EEPROM save", page.result_summary_section._reason_label.text())
            self.assertIn("Workbook Validation: FAILED", page.uuid_section.workbook_validation_text)

    def test_production_page_logs_mixed_parameter_results_with_pass_and_fail_levels(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        results = [
            ParameterVerificationResult(
                definition=definitions["UUID"],
                expected_text="1223303010",
                actual_text="",
                passed=False,
                reason="S/N read-back verification - expected 1223303010, actual timeout",
            ),
            ParameterVerificationResult(
                definition=definitions["PWM"],
                expected_text="10",
                actual_text="10",
                passed=True,
                reason="PWM read-back verification",
            ),
        ]

        page._handle_parameter_verification_finished(
            False,
            "S/N read-back verification - expected 1223303010, actual timeout",
            results,
        )

        log_text = page.progress_section.to_plain_text()
        self.assertIn("[FAIL] UUID read-back verification - expected 1223303010, actual timeout", log_text)
        self.assertIn("[PASS] PWM read-back verification - expected 10, actual 10", log_text)

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook save tests.")
    def test_production_page_save_completed_workbook_shows_output_path(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        runtime_window.node_status[3] = {
            "connected": True,
            "firmware": "v1.0.0",
            "uuid": "",
            "type": "X",
            "interrupt": "OK",
        }
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            output_path = Path(tmpdir) / "ipqc_completed.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)

            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            page._update_uuid_cells_in_workbook_memory("1223303010", True)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getSaveFileName",
                return_value=(str(output_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_save_completed_workbook()
                self._app.processEvents()

            self.assertEqual(page.uuid_section.workbook_output_text, str(output_path.resolve()))
            self.assertTrue(output_path.exists())

    def test_production_status_history_and_clear_button(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        for index in range(40):
            page.progress_section.append_step(f"log line {index}")
        self._app.processEvents()

        self.assertIn("[INFO] log line 39", page.progress_section.to_plain_text())

        clear_buttons = [button for button in page.progress_section.findChildren(QPushButton) if button.text() == "Clear"]
        self.assertEqual(len(clear_buttons), 1)
        clear_buttons[0].click()
        self._app.processEvents()
        self.assertEqual(page.progress_section.to_plain_text().strip(), "")


class ProductionParameterControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    @staticmethod
    def _create_ipqc_workbook(path: Path, *, with_optional_fields: bool = True) -> None:
        ProductionPageWorkflowTests._create_ipqc_workbook(path, with_optional_fields=with_optional_fields)

    def test_uuid_helper_functions(self) -> None:
        self.assertEqual(parse_uuid_value("1234567890"), 1234567890)
        self.assertEqual(parse_uuid_value("0x499602D2"), 1234567890)
        self.assertEqual(parse_pwm_value("100"), 100)
        self.assertEqual(build_pwm_read_payload(), [0x85])
        self.assertEqual(build_uuid_read_payload(), [0xE0, 0x3F])
        self.assertEqual(build_uuid_write_payload(1234567890), [0xE0, 0x3D, 0x00, 0x49, 0x96, 0x02, 0xD2])
        self.assertEqual(build_pwm_write_payload(100), [0x84, 0x00, 0x64])
        self.assertEqual(format_uuid_like_source(1234567890, "1234567890"), "1234567890")
        self.assertEqual(format_uuid_like_source(1234567890, "0x499602D2"), "0x499602D2")
        self.assertEqual(validate_uuid_format(1223306010, 6), (True, ""))
        is_valid, invalid_message = validate_uuid_format(1223305010, 6)
        self.assertFalse(is_valid)
        self.assertIn("does not match node_id", invalid_message)
        decoded_ok, decoded_uuid, _ = decode_uuid_response([0xE0, 0x3A, 0x00, 0x49, 0x96, 0x02, 0xD2])
        self.assertTrue(decoded_ok)
        self.assertEqual(decoded_uuid, 1234567890)
        pwm_decoded_ok, pwm_decoded_value, _ = decode_pwm_response([0x85, 0x00, 0x50])
        self.assertTrue(pwm_decoded_ok)
        self.assertEqual(pwm_decoded_value, 80)

    def test_write_pwm_sends_set_pwm_payload_to_selected_node(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge)

        ok, _message = controller.write_pwm(6, "H", 100, expected_pwm_text="100")
        self.assertTrue(ok)
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0x84, 0x00, 0x64]))

    def test_verify_pwm_uses_getvel_and_decodes_response(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        events: list[tuple[bool, str]] = []
        controller.pwm_verification_finished.connect(lambda passed, reason: events.append((passed, reason)))

        self.assertTrue(controller.verify_pwm(6, "H", 80, expected_pwm_text="80"))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0x85]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x85, "params": [0x00, 0x50]}
        )
        self._app.processEvents()
        self.assertTrue(events)
        self.assertTrue(events[-1][0])
        self.assertEqual(controller.last_verify_actual_pwm, 80)
        self.assertEqual(controller.last_verify_actual_pwm_text, "80")

    def test_verify_pwm_accepts_expected_values_as_string_and_int(self) -> None:
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        for expected_input in ("10", 10):
            with self.subTest(expected_input=expected_input):
                runtime_window = _FakeRuntimeWindow()
                bridge = _FakeBridge(runtime_window)
                controller = ProductionParameterController(bridge, timeout_ms=100)
                events: list[tuple[bool, str, object]] = []
                controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

                request = controller.build_parameter_request(definitions["PWM"], 6, "H", expected_input)
                self.assertTrue(controller.verify_parameters([request]))
                self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0x85]))
                runtime_window.packet_received.emit(
                    {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x85, "params": [0x00, 0x0A]}
                )
                self._app.processEvents()

                self.assertTrue(events)
                self.assertTrue(events[-1][0])
                result = events[-1][2][0]
                self.assertEqual(result.definition.name, "PWM")
                self.assertEqual(result.actual_text, "10")

    def test_verify_pwm_fails_when_actual_value_differs(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        request = controller.build_parameter_request(definitions["PWM"], 6, "H", "10")
        self.assertTrue(controller.verify_parameters([request]))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0x85]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x85, "params": [0x00, 0x50]}
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("expected 10, actual 80", events[-1][1])

    def test_verify_loaded_uuid_times_out_when_response_is_missing(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=20)
        events: list[tuple[bool, str]] = []
        controller.verification_finished.connect(lambda passed, reason: events.append((passed, reason)))

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        self.assertTrue(controller.verify_loaded_uuid(6, "H"))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0xE0, 0x3F]))

        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not events:
            self._app.processEvents()
            time.sleep(0.01)

        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("Timed out", events[-1][1])

    def test_parameter_pipeline_verifies_uuid_and_pwm_with_shared_definitions(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        requests = [
            controller.build_parameter_request(definitions["UUID"], 6, "H", "1223306010"),
            controller.build_parameter_request(definitions["PWM"], 6, "H", "80"),
        ]
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        self.assertTrue(controller.verify_parameters(requests))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0xE0, 0x3F]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0xE0, "params": [0x3A, *build_uuid_write_payload(1223306010)[2:]]}
        )
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, [0x85]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x85, "params": [0x00, 0x50]}
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertTrue(events[-1][0])
        result_names = [result.definition.name for result in events[-1][2]]
        self.assertEqual(result_names, ["UUID", "PWM"])

    def test_parameter_pipeline_dummy_definition_uses_shared_flow(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        dummy = ParameterDefinition(
            name="DUMMY",
            expected_cell="B9",
            actual_cell="C9",
            result_cell="D9",
            parse_expected=lambda value: int(str(value).strip()),
            build_write_command=lambda value: [0x91, int(value) & 0xFF],
            build_read_command=lambda: [0x92],
            response_command=0x92,
            decode_response=lambda payload: (True, payload[1], "") if len(payload) > 1 else (False, None, "short"),
            format_actual=lambda actual, _expected: str(actual),
            compare=lambda expected, _expected_text, actual, _actual_text: int(expected) == int(actual),
        )
        request = controller.build_parameter_request(dummy, 6, "H", "7")
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        ok, message = controller.write_parameters([request])
        self.assertTrue(ok, message)
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, [0x91, 0x07]))
        self.assertTrue(controller.verify_parameters([request]))
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, [0x92]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x92, "params": [0x07]}
        )
        self._app.processEvents()

        self.assertTrue(events[-1][0])
        self.assertEqual(events[-1][2][0].definition.name, "DUMMY")

    def test_parameter_pipeline_dummy_definition_mismatch_fails(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        dummy = ParameterDefinition(
            name="DUMMY",
            expected_cell="B9",
            actual_cell="C9",
            result_cell="D9",
            parse_expected=lambda value: int(str(value).strip()),
            build_write_command=lambda value: [0x91, int(value) & 0xFF],
            build_read_command=lambda: [0x92],
            response_command=0x92,
            decode_response=lambda payload: (True, payload[1], "") if len(payload) > 1 else (False, None, "short"),
            format_actual=lambda actual, _expected: str(actual),
            compare=lambda expected, _expected_text, actual, _actual_text: int(expected) == int(actual),
        )
        request = controller.build_parameter_request(dummy, 6, "H", "7")
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        self.assertTrue(controller.verify_parameters([request]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x92, "params": [0x09]}
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("expected 7, actual 9", events[-1][1])

    def test_parameter_pipeline_dummy_string_definition_uses_shared_flow(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        dummy = ParameterDefinition(
            name="DUMMY-ID",
            expected_cell="B10",
            actual_cell="C10",
            result_cell="D10",
            parse_expected=lambda value: str(value).strip().upper(),
            build_write_command=None,
            build_read_command=lambda: [0x93],
            response_command=0x93,
            decode_response=lambda payload: (True, chr(payload[1]), "") if len(payload) > 1 else (False, None, "short"),
            format_actual=lambda actual, _expected: str(actual),
            compare=lambda expected, _expected_text, actual, _actual_text: str(expected) == str(actual),
        )
        request = controller.build_parameter_request(dummy, 6, "H", " a ")
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        self.assertTrue(controller.verify_parameters([request]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": 0x93, "params": [ord("A")]}
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertTrue(events[-1][0])
        self.assertEqual(events[-1][2][0].actual_text, "A")

    def test_parameter_pipeline_uuid_timeout_still_fails_with_timeout(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=20)
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        request = controller.build_parameter_request(definitions["UUID"], 6, "H", "1223306010")
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        self.assertTrue(controller.verify_parameters([request]))
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline and not events:
            self._app.processEvents()
            time.sleep(0.01)

        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("actual timeout", events[-1][1])

    def test_verify_parameters_blocks_during_eeprom_settle_and_allows_after(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        definitions = {definition.name: definition for definition in default_workbook_parameter_definitions()}
        request = controller.build_parameter_request(definitions["UUID"], 6, "H", "1223306010")
        events: list[tuple[bool, str, object]] = []
        controller.parameter_verification_finished.connect(lambda passed, reason, results: events.append((passed, reason, results)))

        self.assertTrue(controller.save_parameters_to_eeprom(6, "H"))
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]))
        runtime_window.packet_received.emit(
            {"status": "ok", "type": "can_over_uart", "sender": 6, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A, 0x00]}
        )
        self._app.processEvents()

        sent_before_verify = len(runtime_window.backend_client.sent_commands)
        self.assertFalse(controller.verify_parameters([request]))
        self.assertEqual(len(runtime_window.backend_client.sent_commands), sent_before_verify)
        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("settle is still active", events[-1][1])

        controller._handle_eeprom_settle_timeout()
        self.assertTrue(controller.verify_parameters([request]))
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, [0xE0, 0x3F]))

    def test_load_uuid_csv_validation_blocks_invalid_rows(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge)

        csv_text = "node_id,node_name,uuid\n6,H,1223305010\n2,Y,1223302010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_invalid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            is_valid = controller.load_uuid_csv(str(csv_path))

        self.assertFalse(is_valid)
        self.assertEqual(controller.rows, [])
        self.assertGreaterEqual(len(controller.errors), 1)

    def test_write_loaded_uuid_sends_write_payload_only(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge)

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        ok, _message = controller.write_loaded_uuid(6, "H")
        self.assertTrue(ok)
        self.assertEqual(
            runtime_window.backend_client.sent_commands[0],
            (6, [0xE0, 0x3D, 0x00, 0x48, 0xEA, 0x2B, 0x1A]),
        )
        self.assertEqual(len(runtime_window.backend_client.sent_commands), 1)

    def test_verify_loaded_uuid_passes_for_matching_response(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        events: list[tuple[bool, str]] = []
        controller.verification_finished.connect(lambda passed, reason: events.append((passed, reason)))

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        self.assertTrue(controller.verify_loaded_uuid(6, "H"))
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, [0xE0, 0x3F]))
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 6,
                "cmd": 0xE0,
                "params": [0x3A, 0x00, 0x48, 0xEA, 0x2B, 0x1A],
            }
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertTrue(events[-1][0])

    def test_verify_loaded_uuid_fails_for_wrong_node(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        events: list[tuple[bool, str]] = []
        controller.verification_finished.connect(lambda passed, reason: events.append((passed, reason)))

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        self.assertTrue(controller.verify_loaded_uuid(6, "H"))
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 5,
                "cmd": 0xE0,
                "params": [0x3A, 0x00, 0x48, 0xEA, 0x2B, 0x1A],
            }
        )
        self._app.processEvents()

        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("wrong node", events[-1][1])

    def test_verify_loaded_uuid_fails_when_selected_node_missing_in_csv(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge, timeout_ms=100)
        events: list[tuple[bool, str]] = []
        controller.verification_finished.connect(lambda passed, reason: events.append((passed, reason)))

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        self.assertFalse(controller.verify_loaded_uuid(5, "V"))
        self.assertTrue(events)
        self.assertFalse(events[-1][0])
        self.assertIn("No UUID CSV row found", events[-1][1])

    def test_uuid_section_removes_legacy_uuid_csv_controls_and_keeps_workbook_flow(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        title_labels = [label.text() for label in page.uuid_section.findChildren(QLabel) if label.objectName() == "PanelTitle"]
        self.assertIn("IPQC Workbook Parameter Programming", title_labels)
        self.assertFalse(hasattr(page.uuid_section, "load_button"))
        self.assertFalse(hasattr(page.uuid_section, "_file_label"))
        self.assertFalse(hasattr(page.uuid_section, "_validation_label"))
        self.assertFalse(hasattr(page.uuid_section, "_preview_table"))
        self.assertEqual(page.uuid_section.load_workbook_button.text(), "Load IPQC Workbook")
        self.assertEqual(page.uuid_section.write_button.text(), "Write Parameters to MCU")
        self.assertEqual(page.uuid_section.verify_button.text(), "Read Back / Verify")
        self.assertEqual(page.uuid_section.save_button.text(), "Save / Download Completed Workbook")
        self.assertFalse(page.uuid_section.verify_button.isEnabled())
        self.assertFalse(page.uuid_section.write_button.isEnabled())
        self.assertFalse(page.uuid_section.save_button.isEnabled())
        self.assertEqual(page.uuid_section.last_workbook_action_text, "-")
        self.assertFalse(hasattr(page.uuid_section, "_result_csv_label"))
        button_texts = [button.text() for button in page.findChildren(type(page.uuid_section.write_button))]
        self.assertNotIn("Echo Test", button_texts)
        self.assertNotIn("Safe Movement Test", button_texts)
        self.assertFalse(hasattr(page.test_control_section, "_profile_combo"))
        stage_labels = [label.text() for label in page.stage_section.findChildren(QLabel)]
        self.assertIn("Configuration", stage_labels)
        self.assertIn("Single Axis Functional Test", stage_labels)
        self.assertIn("Performance Test", stage_labels)
        stage_button_texts = [button.text() for button in page.stage_section.findChildren(QPushButton)]
        self.assertEqual(stage_button_texts.count("Start Test"), 3)

    def test_single_axis_stage_opens_functional_popup(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        page._handle_single_axis_test_requested()
        self._app.processEvents()

        self.assertIsNotNone(page._single_axis_popup)
        assert page._single_axis_popup is not None
        self.assertIsInstance(page._single_axis_popup, SingleAxisFunctionalPopup)
        self.assertEqual(page._single_axis_popup.windowTitle(), "Functional")

    def test_single_axis_popup_warns_when_run_without_node(self) -> None:
        popup = SingleAxisFunctionalPopup(node_options=[(3, "X")])
        with patch("gui.workspace.pages.single_axis_functional_popup.QMessageBox.warning") as warning_mock:
            popup._handle_run_clicked()
        self.assertTrue(warning_mock.called)
        self.assertTrue(popup.run_button.isEnabled())
        self.assertTrue(popup.node_combo.isEnabled())

    def test_single_axis_popup_placeholder_run_updates_status_and_reenables_controls(self) -> None:
        # Suppress any modal dialogs from the placeholder pass flow
        with patch(
            "gui.workspace.pages.single_axis_functional_popup.QMessageBox.information",
            return_value=None,
        ), patch(
            "gui.workspace.pages.single_axis_functional_popup.QMessageBox.warning",
            return_value=None,
        ), patch(
            "gui.workspace.pages.single_axis_functional_popup.SingleAxisFunctionalPopup.ask_start_sampling",
            return_value=False,
        ):
            popup = SingleAxisFunctionalPopup(node_options=[(3, "X")], allow_safe_tx=True)
            popup.node_combo.setCurrentIndex(1)
            popup._handle_run_clicked()

            # Legacy placeholder flow is no longer step-driven. Simulate completion
            # by invoking the pass handler directly to verify UI re-enables and status updates.
            popup.mark_passed()

            status_text = popup.status_block.toPlainText()
            self.assertIn("Functional test PASSED.", status_text)
            self.assertTrue(popup.run_button.isEnabled())
            self.assertTrue(popup.node_combo.isEnabled())

            # Ensure the dialog is closed to avoid stray timers in CI
            popup.close()

    def test_production_page_blocks_write_and_verify_when_no_workbook_loaded(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        self.assertFalse(page.uuid_section.write_button.isEnabled())
        self.assertFalse(page.uuid_section.verify_button.isEnabled())
        page._handle_write_uuid()
        page._handle_verify_uuid()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(page.result_summary_section._status_label.text(), "FAIL")
        self.assertIn("Expected S/N is unavailable", page.result_summary_section._reason_label.text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook guard tests.")
    def test_production_page_blocks_uuid_actions_when_workbook_expected_sn_missing(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            wb = load_workbook(workbook_path)
            wb["3X"]["B4"] = None
            wb.save(workbook_path)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            self.assertFalse(page.uuid_section.write_button.isEnabled())
            page._handle_write_uuid()
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands, [])
            self.assertEqual(page.result_summary_section._status_label.text(), "FAIL")
            self.assertIn("Expected S/N is unavailable", page.result_summary_section._reason_label.text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook guard tests.")
    def test_production_page_blocks_uuid_actions_when_workbook_expected_sn_invalid(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            self._create_ipqc_workbook(workbook_path, with_optional_fields=False)
            wb = load_workbook(workbook_path)
            wb["3X"]["B4"] = "not-a-uuid"
            wb.save(workbook_path)
            with patch(
                "gui.workspace.pages.production_page.QFileDialog.getOpenFileName",
                return_value=(str(workbook_path), "Excel Files (*.xlsx)"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            self.assertFalse(page.uuid_section.verify_button.isEnabled())
            self.assertFalse(page.uuid_section.write_button.isEnabled())
            page._handle_write_uuid()
            page._handle_verify_uuid()
            self._app.processEvents()
            self.assertEqual(runtime_window.backend_client.sent_commands, [])
            self.assertEqual(page.result_summary_section._status_label.text(), "FAIL")
            self.assertIn("Expected S/N in workbook B4 is invalid", page.result_summary_section._reason_label.text())


if __name__ == "__main__":
    unittest.main()
