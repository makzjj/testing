"""Unit tests for reusable backend/runtime service modules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services import (
    RuntimePacketHandler,
    RxLogWriter,
    build_default_node_status,
    connected_node_ids,
    ensure_node_status,
    reset_node_status,
)
from services.communication_log_store import CommunicationLogStore
from services.robot_backend_client import RobotBackendClient
from serial_conn.commands import CommandBuilder
from serial_conn.connection import SerialConnection
from myconfig.constants import COMMANDS


class NodeStatusStoreTests(unittest.TestCase):
    """Verifies the shared node-status helpers used across UI layers."""

    def test_helpers_create_and_reset_default_node_records(self) -> None:
        node_status = build_default_node_status([2, 3])

        self.assertEqual(sorted(node_status.keys()), [2, 3])
        self.assertFalse(node_status[2]["connected"])

        node_record = ensure_node_status(node_status, 5)
        node_record["connected"] = True
        node_record["firmware"] = "v1.2.3.4"

        self.assertEqual(connected_node_ids(node_status), [5])

        reset_node_status(node_status, [2, 3])

        self.assertEqual(sorted(node_status.keys()), [2, 3])
        self.assertEqual(connected_node_ids(node_status), [])
        self.assertEqual(node_status[2]["firmware"], "")


class RuntimePacketHandlerTests(unittest.TestCase):
    """Ensures runtime packet parsing stays reusable outside MainWindow."""

    def setUp(self) -> None:
        self.handler = RuntimePacketHandler()
        self.node_status = build_default_node_status()

    def test_can_packet_emits_node_activity_and_node_id_events(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 3,
            "cmd": 0x86,
            "params": [0x3A, 0x03],
        }

        events = self.handler.handle_packet(packet, self.node_status)
        event_kinds = [event.kind for event in events]

        self.assertIn("node_activity", event_kinds)
        self.assertIn("node_id_response", event_kinds)
        self.assertTrue(any(event.kind == "log" and "RX[CAN]" in (event.message or "") for event in events))

    def test_direct_uart_packet_emits_comm_stats_and_mcu_version_events(self) -> None:
        packet = {
            "status": "ok",
            "type": "direct_uart",
            "raw_payload": [0xBC, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00, 0x09],
            "mcu_version_response": True,
            "mcu_version": "v1.2.3.4",
        }

        events = self.handler.handle_packet(packet, self.node_status)
        comm_stats_event = next(event for event in events if event.kind == "comm_stats")
        mcu_version_event = next(event for event in events if event.kind == "mcu_version")

        self.assertEqual(comm_stats_event.value["can_rx"], 5)
        self.assertEqual(comm_stats_event.value["uart_tx"], 7)
        self.assertEqual(comm_stats_event.value["uart_rx"], 9)
        self.assertEqual(mcu_version_event.value, "v1.2.3.4")


class RxLogWriterTests(unittest.TestCase):
    """Covers the reusable runtime RX log writer."""

    def test_writer_creates_log_file_and_appends_rx_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = RxLogWriter.create(Path(temp_dir))
            writer.write_rx_data(bytes([0x01, 0xAB, 0x7F]))

            content = writer.log_file_path.read_text(encoding="utf-8")

        self.assertIn("RX: 01 AB 7F", content)


class RobotBackendClientTests(unittest.TestCase):
    """Confirms the backend writes the exact CAN-over-UART bytes it builds."""

    def test_send_command_bytes_writes_raw_payload_to_serial(self) -> None:
        class _FakeSerialConnection:
            def __init__(self) -> None:
                self.baudrate = 345600
                self.serial = object()
                self.writes: list[bytes] = []

            def connect(self, port: str) -> bool:
                return True

            def disconnect(self) -> None:
                return None

            def is_connected(self) -> bool:
                return True

            def write(self, data, is_virt: bool = False) -> int:
                self.writes.append(bytes(data))
                return len(data)

            def read_all(self, is_virt: bool = False) -> bytes:
                return b""

            def get_available_ports(self):
                return []

        fake_serial = _FakeSerialConnection()
        client = RobotBackendClient(serial_connection=fake_serial, command_builder=CommandBuilder())

        payload = client.send_command_bytes(6, [0xC4, 0x3F], sender_node_id=0x01)
        expected = CommandBuilder.build_can_over_uart_packet(0x01, 0x06, [0xC4, 0x3F])

        self.assertEqual(payload, expected)
        self.assertEqual(fake_serial.writes[-1], bytes(expected))

    def test_get_command_bytes_reuses_legacy_robot_power_payloads(self) -> None:
        class _FakeSerialConnection:
            def __init__(self) -> None:
                self.baudrate = 345600
                self.serial = object()

            def connect(self, port: str) -> bool:
                return True

            def disconnect(self) -> None:
                return None

            def is_connected(self) -> bool:
                return True

            def write(self, data, is_virt: bool = False) -> int:
                return len(data)

            def read_all(self, is_virt: bool = False) -> bytes:
                return b""

            def get_available_ports(self):
                return []

        client = RobotBackendClient(serial_connection=_FakeSerialConnection(), command_builder=CommandBuilder())

        self.assertEqual(client.get_command_bytes("ROBOT On"), COMMANDS["ROBOT On"])
        self.assertEqual(client.get_command_bytes("ROBOT Off"), COMMANDS["ROBOT Off"])


class SerialConnectionCommunicationLogTests(unittest.TestCase):
    """Confirms log filtering does not interfere with actual writes."""

    def test_filtered_polling_frame_still_writes_to_serial(self) -> None:
        class _FakeSerial:
            def __init__(self) -> None:
                self.is_open = True
                self.writes: list[bytes] = []

            def write(self, data) -> int:
                payload = bytes(data)
                self.writes.append(payload)
                return len(payload)

        fake_serial = _FakeSerial()
        connection = SerialConnection()
        connection._set_target(fake_serial)
        store = CommunicationLogStore()
        connection.set_communication_log_store(store)

        payload = CommandBuilder.build_can_over_uart_packet(0x01, 0x01, [0xB5, 0x3F])
        written = connection.write(payload)

        self.assertEqual(written, len(payload))
        self.assertEqual(fake_serial.writes[-1], bytes(payload))
        self.assertEqual(store.entries(), [])


if __name__ == "__main__":
    unittest.main()
