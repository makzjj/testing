"""Focused tests for the Production runtime-backed ML 2.0 node flow."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.workspace.pages.production_page import ProductionPage
from gui.workspace.pages.production_parameter_controller import (
    ProductionParameterController,
    build_uuid_read_payload,
    build_uuid_write_payload,
    decode_uuid_response,
    parse_uuid_value,
    validate_uuid_format,
)
from gui.workspace.pages.production_test_controller import ProductionTestController

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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


class ProductionTestControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_selected_node_test_starts_and_matching_response_passes(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=50)
        events: list[tuple] = []

        controller.test_started.connect(lambda node_id, node_name: events.append(("started", node_id, node_name)))
        controller.test_passed.connect(lambda node_id, node_name, reason: events.append(("passed", node_id, node_name, reason)))

        self.assertTrue(controller.run_test(8, "RZ"))
        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, [0x82])])
        self.assertIn(("started", 8, "RZ"), events)

        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 8,
                "cmd": 0x82,
                "decoded_key": "getpos",
                "decoded_value": ("G", 12345),
            }
        )
        self._app.processEvents()

        self.assertTrue(any(event[0] == "passed" and event[1] == 8 for event in events))
        self.assertFalse(controller.is_active())

    def test_wrong_node_response_does_not_pass(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionTestController(bridge, timeout_ms=100)
        events: list[tuple] = []

        controller.test_passed.connect(lambda node_id, node_name, reason: events.append(("passed", node_id, node_name, reason)))

        controller.run_test(11, "NGActuator")
        runtime_window.packet_received.emit(
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 10,
                "cmd": 0x82,
                "decoded_key": "getpos",
                "decoded_value": ("G", 999),
            }
        )
        self._app.processEvents()

        self.assertEqual(events, [])
        self.assertTrue(controller.is_active())
        controller.abort_test()

    def test_timeout_causes_fail(self) -> None:
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

    def test_stop_causes_aborted_and_sends_stop_command(self) -> None:
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


class ProductionPageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 8,
                "cmd": 0x82,
                "decoded_key": "getpos",
                "decoded_value": ("G", 456),
            }
        )
        self._app.processEvents()

        self.assertEqual(page.node_status_section.table.item(6, 2).text(), "Pass")
        self.assertEqual(page.result_summary_section._status_label.text(), "PASS")
        self.assertIn("Node 8 RZ responded successfully.", page.result_summary_section._reason_label.text())


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
        invalid_valid, invalid_message = validate_uuid_format(1223305010, 6)
        self.assertFalse(invalid_valid)
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

    def test_write_loaded_uuids_sends_uuid_write_payload(self) -> None:
        runtime_window = _FakeRuntimeWindow()
        bridge = _FakeBridge(runtime_window)
        controller = ProductionParameterController(bridge)

        csv_text = "node_id,node_name,uuid\n6,H,1223306010\n"
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "uuid_valid.csv"
            csv_path.write_text(csv_text, encoding="utf-8")
            self.assertTrue(controller.load_uuid_csv(str(csv_path)))

        ok, _message = controller.write_loaded_uuids()
        self.assertTrue(ok)
        self.assertEqual(
            runtime_window.backend_client.sent_commands[-1],
            (6, [0xE0, 0x3D, 0x00, 0x48, 0xEA, 0x2B, 0x1A]),
        )

    def test_verify_loaded_uuids_passes_for_matching_response(self) -> None:
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

        self.assertTrue(controller.verify_loaded_uuids())
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

    def test_verify_loaded_uuids_fails_for_wrong_node(self) -> None:
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

        self.assertTrue(controller.verify_loaded_uuids())
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


if __name__ == "__main__":
    unittest.main()
