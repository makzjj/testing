import pytest

from serial_conn.commands import CommandBuilder
from serial_conn.packet_parser import (
    drain_packet_parser_debug_events,
    parse_uart_rx_packets,
    reset_packet_parser_state,
)


@pytest.fixture(autouse=True)
def _reset_parser_state():
    reset_packet_parser_state()
    yield
    reset_packet_parser_state()


def build_uart_frame(node_id: int, payload: bytes) -> bytes:
    return bytes([0xC8, 0x24, node_id, len(payload)]) + payload


def build_amx_frame(sender: int, target: int, payload: bytes) -> bytes:
    return bytes(CommandBuilder.build_can_over_uart_packet(sender, target, list(payload)))


def test_parser_extracts_full_legacy_amx_frame():
    amx = build_amx_frame(6, 1, bytes([0xC4, 0x3A, 0x00]))
    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, amx)))

    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["type"] == "can_over_uart"
    assert pkt["node_id"] == 6
    assert pkt["sender"] == 6
    assert pkt["cmd"] == 0xC4
    assert pkt["params"] == [0x3A, 0x00]


def test_parser_reassembles_split_amx_across_chunks():
    chunk1 = bytes.fromhex("05 25 A5 06")
    chunk2 = bytes.fromhex("05 01 31 03 C4 3A 00 39 F1")

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk1)))
    assert packets == []
    assert leftover == b""

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk2)))
    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["sender"] == 6
    assert pkt["cmd"] == 0xC4
    assert pkt["params"] == [0x3A, 0x00]


def test_parser_extracts_multiple_amx_frames_in_one_outer_stream():
    amx1 = build_amx_frame(6, 1, bytes([0xC4, 0x3A, 0x00]))
    amx2 = build_amx_frame(6, 1, bytes([0x82, 0xFF, 0xFF, 0xFF, 0xFD]))
    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, amx1 + amx2)))

    assert leftover == b""
    assert len(packets) == 2
    assert packets[0]["cmd"] == 0xC4
    assert packets[0]["params"] == [0x3A, 0x00]
    assert packets[1]["cmd"] == 0x82
    assert packets[1]["params"] == [0xFF, 0xFF, 0xFF, 0xFD]


def test_parser_drops_garbage_before_sync_and_resyncs():
    chunk1 = bytes.fromhex("05 11 22 25 A5 06")
    chunk2 = bytes.fromhex("05 01 31 03 C4 3A 00 39 F1")

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk1)))
    assert packets == []
    assert leftover == b""

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk2)))
    assert leftover == b""
    assert len(packets) == 1
    assert packets[0]["params"] == [0x3A, 0x00]

    debug_events = drain_packet_parser_debug_events()
    assert any("dropped" in msg and "AMX sync" in msg for msg in debug_events)


def test_invalid_amx_checksum_is_rejected_and_debugged():
    bad_frame = bytearray(build_amx_frame(6, 1, bytes([0xC4, 0x3A, 0x00])))
    bad_frame[-1] ^= 0xFF

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, bytes(bad_frame))))

    assert packets == []
    assert leftover == b""
    debug_events = drain_packet_parser_debug_events()
    assert any("invalid AMX checksum" in msg for msg in debug_events)


def test_protocol_example_split_frame_extracts_c7_3a_05():
    chunk1 = bytes.fromhex("05 25 A5 05 01 31 03 C7")
    chunk2 = bytes.fromhex("05 3A 05 40 F8 25 A5 05")

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk1)))
    assert packets == []
    assert leftover == b""

    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, chunk2)))
    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["sender"] == 5
    assert pkt["payload_hex"] == "C7 3A 05"
    assert pkt["cmd"] == 0xC7
    assert pkt["params"] == [0x3A, 0x05]


@pytest.mark.parametrize(
    "payload,expected_cmd,expected_params",
    [
        (bytes([0xC4, 0x3A, 0x00]), 0xC4, [0x3A, 0x00]),
        (bytes([0xC9, 0x3A, 0x09]), 0xC9, [0x3A, 0x09]),
        (bytes([0xCA, 0x3A, 0x09]), 0xCA, [0x3A, 0x09]),
        (bytes([0x82, 0xFF, 0xFF, 0xFF, 0xFD]), 0x82, [0xFF, 0xFF, 0xFF, 0xFD]),
        (bytes([0x88, 0x53, 0x10]), 0x88, [0x53, 0x10]),
        (bytes([0xE0, 0x3A, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66]), 0xE0, [0x3A, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66]),
        (bytes([0x85, 0x01, 0x02, 0x03]), 0x85, [0x01, 0x02, 0x03]),
    ],
)
def test_existing_command_payloads_still_extract(payload, expected_cmd, expected_params):
    amx = build_amx_frame(6, 1, payload)
    packets, leftover = parse_uart_rx_packets(bytearray(build_uart_frame(6, amx)))

    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["sender"] == 6
    assert pkt["cmd"] == expected_cmd
    assert pkt["params"] == expected_params
