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
from gui.workspace.widgets import ResponsiveRow
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
        pass_item = page.node_status_section.table.item(6, 2)
        self.assertTrue(pass_item.font().bold())
        self.assertEqual(pass_item.foreground().color().name().lower(), "#2e7d32")
        self.assertEqual(page.result_summary_section._status_label.text(), "PASS")
        self.assertIn("Node 8 RZ responded successfully.", page.result_summary_section._reason_label.text())

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
        self.assertEqual(getattr(first_row, "_stretches", []), [1, 2])
        self.assertEqual(getattr(third_row, "_stretches", []), [1, 2])

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
