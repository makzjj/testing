"""Focused tests for the Production runtime-backed ML 2.0 node flow."""

from __future__ import annotations

import os
import csv
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.workspace.pages.production_page import ProductionPage
from gui.workspace.widgets import ResponsiveRow
from gui.workspace.pages.production_parameter_controller import (
    ProductionParameterController,
    build_uuid_read_payload,
    build_uuid_write_payload,
    decode_uuid_response,
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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from openpyxl import Workbook, load_workbook

    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover - environment dependent.
    _HAS_OPENPYXL = False


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self._connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.stop_commands: list[int] = []

    def is_connected(self) -> bool:
        return self._connected

    def get_command_bytes(self, _command_name: str, fallback: list[int] | None = None) -> list[int]:
        return list(fallback or [])

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
        self.node_status = {
            2: {"connected": False},
            3: {"connected": False},
            8: {"connected": False},
        }


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
                "ports": [],
                "selected_port": None,
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

    @staticmethod
    def _create_ipqc_workbook(path: Path, *, with_optional_fields: bool = True) -> None:
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

        self.assertEqual(page.node_status_section.table.item(6, 2).text(), "Testing")
        self.assertEqual(page.result_summary_section._status_label.text(), "TESTING")

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

        self.assertEqual(page.node_status_section.table.item(6, 2).text(), "Pass")
        pass_item = page.node_status_section.table.item(6, 2)
        self.assertTrue(pass_item.font().bold())
        self.assertEqual(pass_item.foreground().color().name().lower(), "#2e7d32")
        self.assertEqual(page.result_summary_section._status_label.text(), "PASS")
        self.assertIn("All profile steps passed", page.result_summary_section._reason_label.text())

    def test_profile_step_results_append_to_csv_logger(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        with tempfile.TemporaryDirectory() as tmpdir:
            page._result_logger.set_output_dir(Path(tmpdir))
            page._handle_run_test()
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xCB, "params": [0xA5, 0x5A]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x2A]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xD8, "params": [0, 1]})
            self._app.processEvents()

            csv_path = page._result_logger.result_csv_path
            self.assertIsNotNone(csv_path)
            self.assertTrue(csv_path.exists())
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(rows), 5)
            self.assertEqual(rows[-1]["test_type"], "PROFILE_SUMMARY")

    def test_movement_profile_step_results_append_to_csv_logger(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)
        page.test_control_section._profile_combo.setCurrentIndex(1)  # movement

        with tempfile.TemporaryDirectory() as tmpdir:
            page._result_logger.set_output_dir(Path(tmpdir))
            page._handle_run_test()
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xCB, "params": [0xA5, 0x5A]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xC8, "params": [0x3A, 1, 2, 3]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x10]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0xD8, "params": [0, 0]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x81, "params": [ord('E'), 0x00, 0x00, 0x00, 0x20]})
            runtime_window.packet_received.emit({"status": "ok", "type": "can_over_uart", "sender": 3, "cmd": 0x82, "params": [0x00, 0x00, 0x00, 0x20]})
            self._app.processEvents()

            csv_path = page._result_logger.result_csv_path
            self.assertIsNotNone(csv_path)
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            test_types = [row["test_type"] for row in rows]
            self.assertIn("read_initial_position", test_types)
            self.assertIn("wait_move_end", test_types)
            self.assertIn("verify_position_delta", test_types)
            self.assertIn("stop_motor", test_types)
            self.assertEqual(rows[-1]["test_type"], "PROFILE_SUMMARY")

    def test_production_page_uses_compact_section_order_with_results_before_uuid(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        first_row = page.content_layout.itemAt(0).widget()
        second_row = page.content_layout.itemAt(1).widget()
        third_row = page.content_layout.itemAt(2).widget()
        fourth_widget = page.content_layout.itemAt(3).widget()

        self.assertIsInstance(first_row, ResponsiveRow)
        self.assertIsInstance(second_row, ResponsiveRow)
        self.assertIsInstance(third_row, ResponsiveRow)
        self.assertIs(fourth_widget, page.uuid_section)

        first_layout = first_row.layout()
        second_layout = second_row.layout()
        third_layout = third_row.layout()

        self.assertIs(first_layout.itemAt(0).widget(), page.communication_section)
        self.assertIs(first_layout.itemAt(1).widget(), page.robot_nodes_section)

        self.assertIs(second_layout.itemAt(0).widget(), page.node_status_section)
        self.assertIs(second_layout.itemAt(1).widget(), page.test_control_section)

        self.assertIs(third_layout.itemAt(0).widget(), page.result_summary_section)
        self.assertIs(third_layout.itemAt(1).widget(), page.progress_section)
        self.assertEqual(first_row.stretch_factors(), (1, 2))
        self.assertEqual(third_row.stretch_factors(), (1, 2))

    def test_production_page_node_status_fail_is_bold_red(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        page.node_status_section.set_node_status(8, "Fail")
        fail_item = page.node_status_section.table.item(6, 2)
        self.assertEqual(fail_item.text(), "Fail")
        self.assertTrue(fail_item.font().bold())
        self.assertEqual(fail_item.foreground().color().name().lower(), "#c62828")

    def test_production_page_shows_communication_card_controls(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        self.assertGreaterEqual(page.communication_section._port_combo.count(), 1)
        self.assertGreaterEqual(page.communication_section._baud_combo.count(), 1)
        self.assertEqual(page.communication_section._connect_button.text(), "Disconnect")

    def test_production_page_shows_runtime_robot_nodes_and_syncs_dropdown(self) -> None:
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

        self.assertIn("Connected nodes: 8", page.robot_nodes_section._connected_label.text())
        self.assertEqual(page.robot_nodes_section._table.item(0, 0).text(), "Node 08 ✅ Connected")
        page.robot_nodes_section._handle_cell_clicked(0, 0)
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

            self.assertEqual(page.uuid_section._sheet_group_combo.currentText(), "3X")
            self.assertIn("Selected workbook", page.uuid_section._workbook_label.text())
            self.assertIn("1223303010", page.uuid_section._expected_summary_label.text())
            self.assertIn("PWM=100", page.uuid_section._expected_summary_label.text())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC workbook write wiring tests.")
    def test_production_page_writes_uuid_result_to_ipqc_workbook_output(self) -> None:
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

            page._write_uuid_result_to_ipqc_workbook("1223303011", True)
            self._app.processEvents()

            output_text = page.uuid_section._workbook_output_label.text()
            self.assertTrue(output_text.startswith("Completed workbook: "))
            output_path = Path(output_text.replace("Completed workbook: ", "", 1))
            self.assertTrue(output_path.exists())

            output_wb = load_workbook(output_path)
            output_sheet = output_wb["3X"]
            self.assertEqual(output_sheet["C4"].value, "1223303011")
            self.assertEqual(output_sheet["D4"].value, "PASS")


class ProductionParameterControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_uuid_helper_functions(self) -> None:
        self.assertEqual(parse_uuid_value("1234567890"), 1234567890)
        self.assertEqual(parse_uuid_value("0x499602D2"), 1234567890)
        self.assertEqual(build_uuid_read_payload(), [0xE0, 0x3F])
        self.assertEqual(build_uuid_write_payload(1234567890), [0xE0, 0x3D, 0x00, 0x49, 0x96, 0x02, 0xD2])
        self.assertEqual(validate_uuid_format(1223306010, 6), (True, ""))
        is_valid, invalid_message = validate_uuid_format(1223305010, 6)
        self.assertFalse(is_valid)
        self.assertIn("does not match node_id", invalid_message)
        decoded_ok, decoded_uuid, _ = decode_uuid_response([0xE0, 0x3A, 0x00, 0x49, 0x96, 0x02, 0xD2])
        self.assertTrue(decoded_ok)
        self.assertEqual(decoded_uuid, 1234567890)

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

    def test_write_loaded_uuid_sends_write_and_readback_payloads(self) -> None:
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
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (6, [0xE0, 0x3F]))

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

    def test_uuid_section_buttons_use_safe_verify_first_wording(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        page = ProductionPage(bridge)

        self.assertEqual(page.uuid_section.load_button.text(), "Load UUID CSV")
        self.assertEqual(page.uuid_section.verify_button.text(), "Verify Current UUID")
        self.assertEqual(page.uuid_section.write_button.text(), "Write UUID to PCB")


if __name__ == "__main__":
    unittest.main()
