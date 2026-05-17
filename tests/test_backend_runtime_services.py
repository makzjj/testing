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


if __name__ == "__main__":
    unittest.main()
