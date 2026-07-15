"""Unit tests for reusable backend/runtime service modules."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QCoreApplication

from services import (
    NodeDiscoveryCoordinator,
    ReleaseWatchHelper,
    RuntimePacketHandler,
    RxLogWriter,
    build_default_node_status,
    connected_node_ids,
    ensure_node_status,
    reset_node_status,
)
from services.communication_log_store import CommunicationLogStore, format_packet_decoded_text
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
        self.assertIn("motor_current", node_record)
        self.assertEqual(node_record["motor_current"]["latest_mA"], None)

        reset_node_status(node_status, [2, 3])

        self.assertEqual(sorted(node_status.keys()), [2, 3])
        self.assertEqual(connected_node_ids(node_status), [])
        self.assertEqual(node_status[2]["firmware"], "")
        self.assertEqual(node_status[2]["motor_current"]["samples"], [])


class NodeDiscoveryCoordinatorTests(unittest.TestCase):
    def test_coordinator_schedules_once_per_cycle_and_clears_pending_on_dispatch(self) -> None:
        coordinator = NodeDiscoveryCoordinator()

        self.assertEqual(coordinator.begin_cycle(), 1)
        self.assertTrue(coordinator.request_node_info_once(5))
        self.assertTrue(coordinator.is_pending(5))
        self.assertFalse(coordinator.request_node_info_once(5))

        coordinator.mark_dispatch_started(5)

        self.assertFalse(coordinator.is_pending(5))
        self.assertEqual(coordinator.scheduled_nodes(), {5})

    def test_new_cycle_allows_rescheduling_same_node(self) -> None:
        coordinator = NodeDiscoveryCoordinator()

        coordinator.begin_cycle()
        self.assertTrue(coordinator.request_node_info_once(5))
        self.assertFalse(coordinator.request_node_info_once(5))

        coordinator.begin_cycle()
        self.assertTrue(coordinator.request_node_info_once(5))


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

    def test_direct_uart_text_ver_response_emits_mcu_version_event(self) -> None:
        packet = {
            "status": "ok",
            "type": "direct_uart",
            "raw_payload": list(b"ver:1.2.3_4\r\n"),
        }

        events = self.handler.handle_packet(packet, self.node_status)
        mcu_version_event = next(event for event in events if event.kind == "mcu_version")

        self.assertEqual(mcu_version_event.value, "v1.2.3.4")

    def test_can_version_packet_updates_runtime_node_state_and_emits_event(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 5,
            "cmd": 0xC8,
            "params": [0x3A, 0x12, 0x34, 0x56],
        }

        events = self.handler.handle_packet(packet, self.node_status)
        node_version_event = next(event for event in events if event.kind == "node_version")

        self.assertEqual(node_version_event.node_id, 5)
        self.assertEqual(node_version_event.value, "v1.2.3.1110")
        self.assertEqual(self.node_status[5]["firmware"], "v1.2.3.1110")

    def test_mcu_master_interrupt_packet_emits_emergency_stop_active_and_release_events(self) -> None:
        active_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 1,
            "cmd": 0xD8,
            "params": [0x3A, 0x00, 0x00],
        }
        released_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 1,
            "cmd": 0xD8,
            "params": [0x3A, 0x00, 0x01],
        }

        active_events = self.handler.handle_packet(active_packet, self.node_status)
        released_events = self.handler.handle_packet(released_packet, self.node_status)

        self.assertTrue(any(event.kind == "emergency_stop" and event.value is True for event in active_events))
        self.assertTrue(any(event.kind == "emergency_stop" and event.value is False for event in released_events))

    def test_tpos_zl_sets_left_cut_and_right_not_cut_for_sender_only(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 8,
            "cmd": 0x81,
            "params": [0x5A, 0x4C],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertTrue(self.node_status[8]["interrupt_state"]["left_cut"])
        self.assertFalse(self.node_status[8]["interrupt_state"]["right_cut"])
        self.assertEqual(self.node_status[8]["interrupt_state"]["last_source"], "tpos_cut")
        self.assertIsNone(self.node_status[7]["interrupt_state"]["left_cut"])

    def test_tpos_zr_sets_right_cut_and_left_not_cut(self) -> None:
        self.node_status[8]["interrupt_state"]["left_cut"] = True
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 8,
            "cmd": 0x81,
            "params": [0x5A, 0x52],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertFalse(self.node_status[8]["interrupt_state"]["left_cut"])
        self.assertTrue(self.node_status[8]["interrupt_state"]["right_cut"])
        self.assertEqual(self.node_status[8]["interrupt_state"]["last_source"], "tpos_cut")

    def test_tpos_direct_left_event_sets_left_cut_and_right_not_cut(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 9,
            "cmd": 0x81,
            "params": [0x4C],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertTrue(self.node_status[9]["interrupt_state"]["left_cut"])
        self.assertFalse(self.node_status[9]["interrupt_state"]["right_cut"])

    def test_tpos_direct_right_event_sets_right_cut_and_left_not_cut(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 9,
            "cmd": 0x81,
            "params": [0x52],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertFalse(self.node_status[9]["interrupt_state"]["left_cut"])
        self.assertTrue(self.node_status[9]["interrupt_state"]["right_cut"])

    def test_d8_interrupt_response_updates_both_sensor_states_and_raw_int_values(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xD8,
            "params": [0x3A, 0x00, 0x01],
        }

        self.handler.handle_packet(packet, self.node_status)

        interrupt_state = self.node_status[6]["interrupt_state"]
        self.assertEqual(interrupt_state["int0"], 0x00)
        self.assertEqual(interrupt_state["int1"], 0x01)
        self.assertTrue(interrupt_state["left_cut"])
        self.assertFalse(interrupt_state["right_cut"])
        self.assertEqual(interrupt_state["last_source"], "d8_query")

    def test_d8_interrupt_response_updates_right_cut_and_left_not_cut_for_1_0(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xD8,
            "params": [0x3A, 0x01, 0x00],
        }

        self.handler.handle_packet(packet, self.node_status)

        interrupt_state = self.node_status[6]["interrupt_state"]
        self.assertEqual(interrupt_state["int0"], 0x01)
        self.assertEqual(interrupt_state["int1"], 0x00)
        self.assertFalse(interrupt_state["left_cut"])
        self.assertTrue(interrupt_state["right_cut"])
        self.assertEqual(interrupt_state["last_source"], "d8_query")

    def test_nodeconfig_response_is_stored_in_runtime_node_status(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xC4,
            "params": [0x3A, 0x02],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertEqual(self.node_status[6]["nodeconfig"], 0x02)

    def test_motor_current_response_updates_only_sender_node_and_emits_bounded_series(self) -> None:
        first_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x3A, 0x04, 0xD2],
        }
        second_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x3A, 0x07, 0xD0],
        }

        events = self.handler.handle_packet(first_packet, self.node_status)
        self.handler.handle_packet(second_packet, self.node_status)

        motor_current = self.node_status[6]["motor_current"]
        self.assertEqual(motor_current["latest_mA"], 2000)
        self.assertEqual(motor_current["last_updated"], 2)
        self.assertEqual(motor_current["samples"][0]["current_mA"], 1234)
        self.assertEqual(motor_current["samples"][1]["current_mA"], 2000)
        self.assertEqual(self.node_status[7]["motor_current"]["latest_mA"], None)
        self.assertTrue(any(event.kind == "motor_current_sample" for event in events))

    def test_motor_current_response_accepts_minimal_hi_lo_form(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x00, 0x64],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertEqual(self.node_status[6]["motor_current"]["latest_mA"], 100)
        self.assertEqual(self.node_status[6]["motor_current"]["samples"][-1]["index"], 1)

    def test_motor_current_response_accepts_explicit_cf_hi_lo_form(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0xCF, 0x00, 0x64],
        }

        self.handler.handle_packet(packet, self.node_status)

        self.assertEqual(self.node_status[6]["motor_current"]["latest_mA"], 100)
        self.assertEqual(self.node_status[6]["motor_current"]["samples"][-1]["index"], 1)

    def test_motor_current_response_from_parser_decoded_key_path_updates_runtime(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x04, 0xD2],
            "decoded_key": "motor_current_mA",
            "decoded_value": 1234,
        }

        events = self.handler.handle_packet(packet, self.node_status)

        self.assertEqual(self.node_status[6]["motor_current"]["latest_mA"], 1234)
        self.assertEqual(self.node_status[6]["motor_current"]["samples"][-1]["current_mA"], 1234)
        self.assertTrue(any(event.kind == "motor_current_sample" for event in events))

    def test_bundled_getpos_and_motor_current_packets_both_update_runtime(self) -> None:
        packets = [
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 6,
                "cmd": 0x82,
                "params": [0x00, 0x00, 0x00, 0x2A],
                "decoded_key": "getpos",
                "decoded_value": ("G", 42),
            },
            {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 6,
                "cmd": 0xCF,
                "params": [0xCF, 0x04, 0xD2],
                "decoded_key": "motor_current_mA",
                "decoded_value": 1234,
            },
        ]

        self.handler.handle_packets(packets, self.node_status)

        self.assertEqual(self.node_status[6]["getpos"], ("G", 42))
        self.assertEqual(self.node_status[6]["motor_current"]["latest_mA"], 1234)
        self.assertEqual(self.node_status[6]["motor_current"]["samples"][-1]["current_mA"], 1234)

    def test_motor_current_short_or_invalid_response_is_ignored_safely(self) -> None:
        short_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x3A, 0x04],
        }
        invalid_prefix_packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0x41, 0x04, 0xD2],
        }

        self.handler.handle_packet(short_packet, self.node_status)
        self.handler.handle_packet(invalid_prefix_packet, self.node_status)

        self.assertEqual(self.node_status[6]["motor_current"]["latest_mA"], None)
        self.assertEqual(self.node_status[6]["motor_current"]["samples"], [])

    def test_motor_current_series_is_bounded(self) -> None:
        for value in range(1, 305):
            packet = {
                "status": "ok",
                "type": "can_over_uart",
                "sender": 6,
                "cmd": 0xCF,
                "params": [0x3A, (value >> 8) & 0xFF, value & 0xFF],
            }
            self.handler.handle_packet(packet, self.node_status)

        motor_current = self.node_status[6]["motor_current"]
        self.assertEqual(len(motor_current["samples"]), 300)
        self.assertEqual(motor_current["samples"][0]["index"], 5)
        self.assertEqual(motor_current["samples"][0]["current_mA"], 5)
        self.assertEqual(motor_current["samples"][-1]["index"], 304)
        self.assertEqual(motor_current["samples"][-1]["current_mA"], 304)


class _ManualTime:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance_ms(self, milliseconds: int) -> None:
        self.value += float(milliseconds) / 1000.0


class _FakeReleaseWatchBridge:
    def __init__(self) -> None:
        self.connected = True
        self.state_by_node: dict[int, dict[str, object]] = {}

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        return self.connected, self.connected

    def get_runtime_node_interrupt_state(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        state = self.state_by_node.get(int(node_id), {})
        return {
            "node_id": int(node_id),
            "int0": state.get("int0"),
            "int1": state.get("int1"),
            "left_cut": state.get("left_cut"),
            "right_cut": state.get("right_cut"),
            "last_source": state.get("last_source"),
        }


class ReleaseWatchHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.bridge = _FakeReleaseWatchBridge()
        self.clock = _ManualTime()
        self.sent_payloads: list[list[int]] = []
        self.released: list[tuple[int, str]] = []
        self.timed_out: list[tuple[int, str]] = []
        self.stopped: list[tuple[int, str, str]] = []
        self.helper = ReleaseWatchHelper(
            self.bridge,
            poll_interval_ms=50,
            timeout_ms=160,
            time_source=self.clock,
        )

    def _send_query(self, payload: list[int]) -> None:
        self.sent_payloads.append(list(payload))

    def _on_released(self, node_id: int, sensor: str) -> None:
        self.released.append((node_id, sensor))

    def _on_timeout(self, node_id: int, sensor: str) -> None:
        self.timed_out.append((node_id, sensor))

    def _on_stopped(self, node_id: int, sensor: str, reason: str) -> None:
        self.stopped.append((node_id, sensor, reason))

    def test_release_watch_starts_with_immediate_d8_query(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}

        started = self.helper.start_release_watch(
            8,
            "L",
            self._send_query,
            on_released=self._on_released,
            on_timeout=self._on_timeout,
            on_stopped=self._on_stopped,
        )

        self.assertTrue(started)
        self.assertTrue(self.helper.is_active)
        self.assertEqual(self.sent_payloads, [[0xD8, 0x3F]])
        self.assertEqual(self.helper.query_count, 1)

    def test_release_watch_stops_when_runtime_state_shows_release(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}
        self.helper.start_release_watch(
            8,
            "L",
            self._send_query,
            on_released=self._on_released,
            on_timeout=self._on_timeout,
            on_stopped=self._on_stopped,
        )

        self.bridge.state_by_node[8]["left_cut"] = False
        self.bridge.state_by_node[8]["right_cut"] = False
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertFalse(self.helper.is_active)
        self.assertEqual(self.released, [(8, "L")])
        self.assertEqual(self.timed_out, [])
        self.assertEqual(self.stopped, [(8, "L", "released")])

    def test_release_watch_times_out_with_bounded_poll_count(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}
        self.helper.start_release_watch(
            8,
            "L",
            self._send_query,
            on_released=self._on_released,
            on_timeout=self._on_timeout,
            on_stopped=self._on_stopped,
        )

        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()
        self.clock.advance_ms(60)
        self.helper._handle_poll_tick()

        self.assertFalse(self.helper.is_active)
        self.assertEqual(self.released, [])
        self.assertEqual(self.timed_out, [(8, "L")])
        self.assertEqual(self.stopped, [(8, "L", "timeout")])
        self.assertEqual(self.helper.query_count, 3)
        self.assertEqual(self.sent_payloads, [[0xD8, 0x3F], [0xD8, 0x3F], [0xD8, 0x3F]])

    def test_release_watch_rejects_duplicate_active_session(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}
        self.assertTrue(self.helper.start_release_watch(8, "L", self._send_query))
        self.assertFalse(self.helper.start_release_watch(8, "L", self._send_query))
        self.assertEqual(self.sent_payloads, [[0xD8, 0x3F]])

    def test_release_watch_stop_cancels_future_polling(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}
        self.helper.start_release_watch(8, "L", self._send_query, on_stopped=self._on_stopped)

        self.assertTrue(self.helper.stop_release_watch("workflow_abort"))
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertFalse(self.helper.is_active)
        self.assertEqual(self.sent_payloads, [[0xD8, 0x3F]])
        self.assertEqual(self.stopped, [(8, "L", "workflow_abort")])

    def test_release_watch_stops_on_disconnect(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": False}
        self.helper.start_release_watch(8, "L", self._send_query, on_stopped=self._on_stopped)
        self.bridge.connected = False

        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertFalse(self.helper.is_active)
        self.assertEqual(self.stopped, [(8, "L", "disconnect")])

    def test_release_watch_continues_when_watched_sensor_releases_but_opposite_sensor_is_still_cut(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": True}
        self.helper.start_release_watch(8, "L", self._send_query, on_released=self._on_released, on_stopped=self._on_stopped)

        self.bridge.state_by_node[8]["left_cut"] = False
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertTrue(self.helper.is_active)
        self.assertEqual(self.released, [])
        self.assertEqual(self.sent_payloads, [[0xD8, 0x3F], [0xD8, 0x3F]])

    def test_release_watch_stops_only_when_both_sensors_are_not_cut(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": True}
        self.helper.start_release_watch(8, "L", self._send_query, on_released=self._on_released, on_stopped=self._on_stopped)

        self.bridge.state_by_node[8]["left_cut"] = False
        self.bridge.state_by_node[8]["right_cut"] = False
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertFalse(self.helper.is_active)
        self.assertEqual(self.released, [(8, "L")])
        self.assertEqual(self.stopped, [(8, "L", "released")])

    def test_release_watch_continues_when_other_side_is_unknown(self) -> None:
        self.bridge.state_by_node[8] = {"left_cut": True, "right_cut": None}
        self.helper.start_release_watch(8, "L", self._send_query, on_released=self._on_released)

        self.bridge.state_by_node[8]["left_cut"] = False
        self.clock.advance_ms(50)
        self.helper._handle_poll_tick()

        self.assertTrue(self.helper.is_active)
        self.assertEqual(self.released, [])


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

    def test_motor_current_packet_formats_with_clear_comm_label(self) -> None:
        packet = {
            "status": "ok",
            "type": "can_over_uart",
            "sender": 6,
            "cmd": 0xCF,
            "params": [0xCF, 0x04, 0xD2],
        }

        decoded = format_packet_decoded_text(packet)

        self.assertIsNotNone(decoded)
        assert decoded is not None
        self.assertIn("MOTOR_I 1234 mA", decoded)


if __name__ == "__main__":
    unittest.main()
