import pytest

from serial_conn.packet_parser import parse_uart_rx_packets


def build_uart_frame(node_id: int, inner_payload: bytes) -> bytes:
    # UART frame: C8 24 <node_id> <len> <payload...>
    return bytes([0xC8, 0x24, node_id, len(inner_payload)]) + inner_payload


def build_can_over_uart(sender: int, target: int, port: int, can_data: bytes) -> bytes:
    # CAN-over-UART payload: 25 A5 <sender> <target> <port> <len> <data...>
    return bytes([0x25, 0xA5, sender, target, port, len(can_data)]) + can_data


def hexify(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)


def test_parser_handles_split_uart_frame_across_two_chunks():
    # Inner CAN data: C4 3A 00 (NODECONFIG response)
    can_data = bytes([0xC4, 0x3A, 0x00])
    inner = build_can_over_uart(sender=6, target=1, port=0x31, can_data=can_data)
    frame = build_uart_frame(node_id=6, inner_payload=inner)

    # Split the frame across two chunks at an arbitrary position
    split_at = 7
    chunk1 = frame[:split_at]
    chunk2 = frame[split_at:]

    rx = bytearray()

    # First chunk: should return no packets, all bytes kept as leftover
    rx += chunk1
    packets, leftover = parse_uart_rx_packets(rx)
    assert packets == []
    assert leftover == chunk1

    # Second chunk appended: should now parse a complete packet
    rx = leftover + chunk2
    packets, leftover = parse_uart_rx_packets(rx)
    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["type"] == "can_over_uart"
    assert pkt["sender"] == 6
    assert pkt["cmd"] == 0xC4
    assert pkt["params"] == [0x3A, 0x00]


def test_parser_handles_two_uart_frames_in_one_chunk():
    # First: NODECONFIG response from node 6
    can1 = bytes([0xC4, 0x3A, 0x00])
    inner1 = build_can_over_uart(6, 1, 0x31, can1)
    frame1 = build_uart_frame(6, inner1)

    # Second: simple GETPOS echo from node 6: 82 00 00 00 00
    can2 = bytes([0x82, 0x00, 0x00, 0x00, 0x00])
    inner2 = build_can_over_uart(6, 1, 0x31, can2)
    frame2 = build_uart_frame(6, inner2)

    chunk = frame1 + frame2
    packets, leftover = parse_uart_rx_packets(bytearray(chunk))
    assert leftover == b""
    assert len(packets) == 2
    assert packets[0]["cmd"] == 0xC4 and packets[0]["params"] == [0x3A, 0x00]
    assert packets[1]["cmd"] == 0x82 and packets[1]["params"] == [0x00, 0x00, 0x00, 0x00]


def test_parser_ignores_garbage_before_uart_header():
    garbage = bytes([0x00, 0x11, 0x22, 0x33])
    can_data = bytes([0xC4, 0x3A, 0x00])
    inner = build_can_over_uart(6, 1, 0x31, can_data)
    frame = build_uart_frame(6, inner)
    chunk = garbage + frame

    packets, leftover = parse_uart_rx_packets(bytearray(chunk))
    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["type"] == "can_over_uart"
    assert pkt["sender"] == 6
    assert pkt["cmd"] == 0xC4
    assert pkt["params"] == [0x3A, 0x00]


def test_parser_extracts_node6_nodeconfig_from_wrapped_frame():
    can_data = bytes([0xC4, 0x3A, 0x00])
    inner = build_can_over_uart(6, 1, 0x31, can_data)
    frame = build_uart_frame(6, inner)

    packets, leftover = parse_uart_rx_packets(bytearray(frame))
    assert leftover == b""
    assert len(packets) == 1
    pkt = packets[0]
    assert pkt["type"] == "can_over_uart"
    assert pkt["sender"] == 6
    assert pkt["cmd"] == 0xC4
    assert pkt["params"] == [0x3A, 0x00]
