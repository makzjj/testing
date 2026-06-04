# serial/packet_parser.py
"""UART packet parsing utilities."""
from data.binary_cmd_parser import decode_command, parse_get_uuid
from myconfig.constants import (
    BCMD_GET_NODE_ID,
    BCMD_ZPOSS,
    BCMD_PSDGFLAG,
    BCMD_GET_MCU_VERSION,
    BCMD_NODE_ID_RESPONSE,
    BCMD_COMM_TEST_FRAME,
)
from utils.checksum import fletcher_checksum


_INNER_AMX_BUFFERS: dict[int, bytearray] = {}
_PARSER_DEBUG_EVENTS: list[str] = []


def reset_packet_parser_state() -> None:
    """Reset buffered parser state for tests."""
    _INNER_AMX_BUFFERS.clear()
    _PARSER_DEBUG_EVENTS.clear()


def drain_packet_parser_debug_events() -> list[str]:
    """Return and clear parser debug messages."""
    events = list(_PARSER_DEBUG_EVENTS)
    _PARSER_DEBUG_EVENTS.clear()
    return events


def _record_parser_debug(message: str) -> None:
    _PARSER_DEBUG_EVENTS.append(message)


def _validate_amx_checksum(frame: bytes) -> bool:
    if len(frame) < 8 or frame[0] != 0x25 or frame[1] != 0xA5:
        return False
    expected = fletcher_checksum(frame[2:-2])
    return expected == (frame[-2], frame[-1])


def _drop_garbage_before_sync(buffer: bytearray) -> int:
    sync_idx = buffer.find(b"\x25\xA5")
    if sync_idx < 0:
        if not buffer:
            return 0
        keep_len = 1 if buffer[-1] == 0x25 else 0
        dropped = len(buffer) - keep_len
        if dropped > 0:
            del buffer[:dropped]
            _record_parser_debug(f"dropped {dropped} byte(s) before AMX sync")
        return dropped

    if sync_idx > 0:
        del buffer[:sync_idx]
        _record_parser_debug(f"dropped {sync_idx} byte(s) before AMX sync")
    return sync_idx


def _build_can_packet(frame: bytes, uart_node_id: int) -> dict:
    sender = frame[2]
    target = frame[3]
    port = frame[4]
    can_data_len = frame[5]
    can_data = frame[6: 6 + can_data_len]
    cmd = can_data[0]
    params = list(can_data[1:]) if len(can_data) > 1 else []

    pkt = {
        "status": "ok",
        "type": "can_over_uart",
        "node_id": uart_node_id,
        "sender": sender,
        "target": target,
        "port": port,
        "cmd": cmd,
        "params": params,
        "payload_hex": " ".join(f"{b:02X}" for b in can_data),
    }

    try:
        key, value = decode_command(cmd, params)
        if key:
            pkt["decoded_key"] = key
            pkt["decoded_value"] = value

        if cmd == 0xE0:
            uuid_result = parse_get_uuid(params)
            if uuid_result != "Invalid":
                pkt["uuid_response"] = True
                pkt["uuid"] = uuid_result
                pkt["uuid_valid"] = True
            else:
                pkt["uuid_response"] = True
                pkt["uuid_valid"] = False
    except Exception as exc:
        pkt["decode_error"] = str(exc)

    return pkt


def _extract_complete_amx_frames(buffer: bytearray, uart_node_id: int) -> list[dict]:
    packets: list[dict] = []

    while buffer:
        _drop_garbage_before_sync(buffer)
        if len(buffer) < 8:
            break
        if buffer[0] != 0x25 or buffer[1] != 0xA5:
            break

        payload_len = buffer[5]
        total_len = payload_len + 8
        if len(buffer) < total_len:
            break

        frame = bytes(buffer[:total_len])
        if not _validate_amx_checksum(frame):
            _record_parser_debug(
                f"invalid AMX checksum for node {frame[2]}: {frame[-2]:02X} {frame[-1]:02X}"
            )
            del buffer[0]
            continue

        packets.append(_build_can_packet(frame, uart_node_id))
        del buffer[:total_len]

    return packets


def _looks_like_can_chunk(payload: bytes) -> bool:
    return bool(payload) and (0 < payload[0] <= 0x1F or (len(payload) >= 2 and payload[0] == 0x25 and payload[1] == 0xA5))


def _parse_mcu_version_from_bytes(params_list):
    """Parse MCU version from parameters."""
    try:
        if not params_list or params_list[0] != 0x3A:
            return None
        if len(params_list) < 4:
            return None
        b1, b2, b3 = params_list[1], params_list[2], params_list[3]
        ver_maj = (b1 >> 4) & 0x0F
        ver_min = b1 & 0x0F
        ver_sub = (b2 >> 4) & 0x0F
        ver_sub_num = ((b2 & 0x0F) << 8) | b3
        return f"v{ver_maj}.{ver_min}.{ver_sub}.{ver_sub_num}"
    except Exception:
        return None


def parse_uart_rx_packets(rx_buffer: bytearray) -> tuple[list, bytearray]:
    """
    Parse UART rx buffer into packet dicts.
    Returns (packets_list, leftover_bytes).
    """

    packets = []
    idx = 0
    buf_len = len(rx_buffer)

    # Parse UART frames
    while idx + 4 <= buf_len:
        # Search for UART header 0xC8 0x24
        if rx_buffer[idx] != 0xC8 or rx_buffer[idx + 1] != 0x24:
            idx += 1
            continue

        # Parse UART header
        node_id = rx_buffer[idx + 2]
        payload_len = rx_buffer[idx + 3]
        total_uart_len = 4 + payload_len

        # Wait for complete UART frame
        if idx + total_uart_len > buf_len:
            break

        # Extract payload
        payload = bytes(rx_buffer[idx + 4: idx + 4 + payload_len])

        # Parse CAN frames within this UART payload. A payload that looks like a
        # CAN chunk must not fall through to the direct-UART path just because
        # it only contains a partial AMX frame.
        if _looks_like_can_chunk(payload):
            can_packets = parse_can_frames_from_uart_payload(payload, node_id)
            packets.extend(can_packets)
        else:
            pkt = {
                "status": "ok",
                "type": "direct_uart",
                "node_id": node_id,
                "payload_hex": " ".join(f"{b:02X}" for b in payload),
                "raw_payload": list(payload),
            }

            # Only detect MCU version if payload starts with 0xC8 (BCMD_GET_MCU_VERSION) and has a colon at index 1
            if len(payload) == 5 and payload[0] == 0xC8 and payload[1] == 0x3A:
                ver = _parse_mcu_version_from_bytes(list(payload[1:5]))
                if ver:
                    pkt["mcu_version_response"] = True
                    pkt["mcu_version"] = ver

            packets.append(pkt)

        # Move to next UART frame
        idx += total_uart_len

    leftover = rx_buffer[idx:]
    return packets, leftover


def parse_can_frames_from_uart_payload(payload: bytes, uart_node_id: int) -> list:
    """
    Parse AMX frames from a UART payload.

    Supports two cases:
    - legacy direct AMX payloads that start with 25 A5
    - source-prefixed CAN chunks that start with <source_node_id>
    """
    if len(payload) >= 2 and payload[0] == 0x25 and payload[1] == 0xA5:
        return _extract_complete_amx_frames(bytearray(payload), uart_node_id)

    if not payload:
        return []

    if 0 < payload[0] <= 0x1F:
        source_node = int(payload[0])
        inner_buffer = _INNER_AMX_BUFFERS.setdefault(source_node, bytearray())
        inner_buffer.extend(payload[1:])
        packets = _extract_complete_amx_frames(inner_buffer, uart_node_id)
        if not inner_buffer:
            _INNER_AMX_BUFFERS.pop(source_node, None)
        return packets

    sync_idx = payload.find(b"\x25\xA5")
    if sync_idx >= 0:
        if sync_idx > 0:
            _record_parser_debug(f"dropped {sync_idx} byte(s) before AMX sync")
        return _extract_complete_amx_frames(bytearray(payload[sync_idx:]), uart_node_id)

    return []


def parse_uart_rx_packets_singale_frame(rx_buffer: bytearray) -> tuple[list[dict], bytearray]:
    """Parse UART packets from receive buffer."""
    parsed_packets = []
    idx = 0

    while idx + 4 <= len(rx_buffer):
        if rx_buffer[idx] != 0xC8 or rx_buffer[idx + 1] != 0x24:
            idx += 1
            continue

        if idx + 4 > len(rx_buffer):
            break

        node_id = rx_buffer[idx + 2]
        payload_len = rx_buffer[idx + 3]
        total_uart_len = 4 + payload_len

        if idx + total_uart_len > len(rx_buffer):
            break

        payload = rx_buffer[idx + 4: idx + 4 + payload_len]

        packet_info = {
            "status": "ok",
            "node_id": node_id,
            "payload": payload,
            "payload_hex": " ".join(f"{b:02X}" for b in payload),
            "params": [],
            "debug_note": f"UART Node:{node_id:02X} Len:{payload_len}"
        }

        if len(payload) >= 8 and payload[0] == 0x25 and payload[1] == 0xA5:
            packet_info["type"] = "can_over_uart"
            sender = payload[2]
            packet_info["sender"] = sender
            packet_info["debug_note"] += f" → CAN Node:{sender:02X}"

            target = payload[3]
            port = payload[4]
            n = payload[5]

            packet_info["debug_note"] += f" CAN_Len:{n}"

            if len(payload) >= 6 + n:
                can_data = payload[6: 6 + n]
                if len(can_data) > 0:
                    cmd = can_data[0]
                    packet_info["cmd"] = cmd
                    params = list(can_data[1:]) if len(can_data) > 1 else []
                    packet_info["params"] = params

                    packet_info["debug_note"] += f" Cmd:{cmd:02X} Params:{len(params)}"

                    if cmd == BCMD_GET_NODE_ID:
                        packet_info["node_id_response"] = True
                        packet_info["debug_note"] += " ← NODE_ID_RESPONSE!"

                    if cmd == BCMD_ZPOSS and len(params) >= 5:
                        from data.zposs_decoder import decode_zposs
                        adc_raw, physical_value = decode_zposs(params)
                        packet_info["adc_raw"] = adc_raw
                        packet_info["physical_value"] = physical_value

                    if cmd == BCMD_COMM_TEST_FRAME and len(params) >= 2:
                        seq = (params[0] << 8) | params[1]
                        packet_info["comm_test_val"] = seq
                        packet_info["debug_note"] += f" CommTestSeq:{seq}"

        else:
            packet_info["type"] = "direct_uart"

            if len(payload) >= 5 and payload[0] == 0xC8 and payload[1] == 0x3A:
                packet_info["mcu_version_response"] = True
                if len(payload) >= 5:
                    major = payload[2]
                    minor = payload[3]
                    patch = payload[4]
                    version_string = f"{major:02d}.{minor:02d}.{patch:02d}"
                    packet_info["mcu_version"] = version_string
                    packet_info["mcu_version_major"] = major
                    packet_info["mcu_version_minor"] = minor
                    packet_info["mcu_version_patch"] = patch

        parsed_packets.append(packet_info)
        idx += total_uart_len

    return parsed_packets, rx_buffer[idx:]
