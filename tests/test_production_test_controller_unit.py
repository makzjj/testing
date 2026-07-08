"""Focused tests for the ProductionTestController profile logic."""

from __future__ import annotations

import time
import unittest

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.workspace.pages.production_parameter_controller import (
    EEPROM_SAVE_COMMAND,
    SET_COMMAND_SUFFIX,
    build_eeprom_save_payload,
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


class _FakeBackendClient:
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

    def __init__(self, *, connected: bool = True) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)
        self.node_status = {}


class _FakeBridge:
    def __init__(self, runtime_window: _FakeRuntimeWindow | None) -> None:
        self.runtime_window = runtime_window

    def get_runtime_window(self, *, create_if_missing: bool = False):
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
            return {"ports": [], "selected_port": "COM11", "baud_rates": ["115200"], "selected_baud": "115200", "connected": False}
        return {"ports": [], "selected_port": "COM11", "baud_rates": ["115200"], "selected_baud": "115200", "connected": runtime_window.backend_client.is_connected()}

    def get_runtime_robot_power_state(self, *, create_if_missing: bool = False) -> bool | None:
        return None

    def send_runtime_robot_power(self, power_on: bool) -> bytearray:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            raise RuntimeError("Runtime backend is unavailable for Production operations.")
        backend_client = runtime_window.backend_client
        payload = backend_client.get_command_bytes("ROBOT On" if power_on else "ROBOT Off")
        backend_client.send_command_bytes(0x01, payload)
        return bytearray(payload)

    def get_runtime_robot_nodes(self, *, create_if_missing: bool = False) -> dict:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {"connected_nodes": [], "rows": []}
        return {"connected_nodes": [], "rows": []}

    def request_runtime_node_scan(self) -> bool:
        runtime_window = self.get_runtime_window(create_if_missing=True)
        return runtime_window is not None


class Recorder(ProductionTestController):
    def __init__(self, bridge, timeout_ms: int = 100) -> None:
        super().__init__(bridge, timeout_ms=timeout_ms)
        self.commands = []
        self.statuses = []
        self.positions = []
        self.flags = {"L": [], "R": []}
        self.range1 = None
        self.range2 = None
        self.diffs = []
        self.passed = False
        self.failed = False
        self.fail_reason = ""
        self.aborted = False
        self.abort_reason = ""

    def command_requested(self, payload: list[int]) -> None:
        self.commands.append(payload)

    def status_changed(self, text: str) -> None:
        self.statuses.append(text)

    def position_changed(self, pos: int) -> None:
        self.positions.append(pos)

    def range1_changed(self, value: int) -> None:
        self.range1 = value

    def range2_changed(self, value: int) -> None:
        self.range2 = value

    def difference_changed(self, value: int) -> None:
        self.diffs.append(value)

    def left_flag_changed(self, active: bool) -> None:
        self.flags["L"].append(active)

    def right_flag_changed(self, active: bool) -> None:
        self.flags["R"].append(active)

    def test_passed(self) -> None:
        self.passed = True

    def test_failed(self, reason: str) -> None:
        self.failed = True
        self.fail_reason = reason

    def test_aborted(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason


def pkt(*bytes_):
    return list(bytes_)


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

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (8, [0xC8, 0x3F]))

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[2], (8, [0x82]))

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x01, 0x00]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[3], (8, [0xD8]))

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [1, 0]})
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
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 11, "cmd": 0xCB, "params": [0x01, 0x02]})
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

        deadline = time.monotonic() + 2.0
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
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 7, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        self._app.processEvents()
        self.assertEqual(events, [])
        self.assertTrue(controller.is_active())
        controller.abort_test()

    def test_unsupported_node_emits_unsupported_without_sending(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []
        controller.test_unsupported.connect(lambda node_id, node_name, reason: events.append(("unsupported", node_id, node_name, reason)))

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
        self.assertEqual(decode_tpos_state_response([ord("E"), 0x00, 0x00, 0x00, 0x10]), (True, {"state": "E", "position": 16}, ""))
        self.assertEqual(decode_interrupt_response([0x01, 0x00]), (True, {"int0_status": 1, "int1_status": 0}, ""))
        self.assertEqual(build_eeprom_save_payload(), [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX])

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
        controller = ProductionTestController(bridge, timeout_ms=500)
        step_ids: list[str] = []
        controller.step_finished.connect(lambda _node_id, _node_name, step: step_ids.append(step.step_id))

        self.assertTrue(controller.run_test(8, "RZ", profile_mode="movement"))
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xCB, "params": [0xA5, 0x5A]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x64]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0, 0]})
        self._app.processEvents()

        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("S"), 0, 0, 0, 100]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [ord("E"), 0, 0, 0, 116]})
        runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x74]})
        self._app.processEvents()

        self.assertFalse(controller.is_active())
        self.assertIsNotNone(controller.last_final_result)
        self.assertEqual(controller.last_final_result.final_result, "PASS")
        self.assertIn("verify_position_delta", step_ids)
        self.assertNotIn("stop_motor", step_ids)
        sent_cmds = [cmd for _node, cmd in runtime_window.backend_client.sent_commands]
        self.assertIn([0x84, 0x00, 0x14], sent_cmds)
        self.assertNotIn([0xDD], sent_cmds)

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

    @pytest.mark.xfail(reason="movement profile path is legacy/future scope and not active in Production UI yet", strict=False)
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
            ],
        )
