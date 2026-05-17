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

        # Parse CAN frames within this UART payload
        can_packets = parse_can_frames_from_uart_payload(payload, node_id)
        packets.extend(can_packets)

        # If no CAN frames found, treat as direct UART
        if not can_packets:
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
    Parse multiple CAN frames from a single UART payload.
    Handles the case where multiple CAN frames are concatenated.
    """
    can_packets = []
    sub_idx = 0
    payload_len = len(payload)

    while sub_idx + 6 <= payload_len:
        # Look for CAN header 0x25 0xA5
        if payload[sub_idx] == 0x25 and payload[sub_idx + 1] == 0xA5:
            # Parse CAN header
            sender = payload[sub_idx + 2]
            target = payload[sub_idx + 3]
            port = payload[sub_idx + 4]
            can_data_len = payload[sub_idx + 5]

            total_can_len = 6 + can_data_len

            # Check if we have complete CAN frame
            if sub_idx + total_can_len > payload_len:
                # Incomplete CAN frame - wait for more data
                break

            # Extract CAN data
            can_data = payload[sub_idx + 6: sub_idx + total_can_len]

            if len(can_data) >= 1:
                cmd = can_data[0]
                params = list(can_data[1:]) if len(can_data) > 1 else []

                # Create CAN packet
                pkt = {
                    "status": "ok",
                    "type": "can_over_uart",
                    "node_id": uart_node_id,  # UART receiver node
                    "sender": sender,  # CAN sender node
                    "target": target,
                    "port": port,
                    "cmd": cmd,
                    "params": params,
                    "payload_hex": " ".join(f"{b:02X}" for b in can_data),
                }

                # Use the imported decode_command function
                try:
                    key, value = decode_command(cmd, params)
                    if key:
                        pkt["decoded_key"] = key
                        pkt["decoded_value"] = value

                    # Special handling for UUID responses
                    if cmd == 0xE0:  # UUID command
                        uuid_result = parse_get_uuid(params)
                        if uuid_result != "Invalid":
                            pkt["uuid_response"] = True
                            pkt["uuid"] = uuid_result
                            pkt["uuid_valid"] = True
                        else:
                            pkt["uuid_response"] = True
                            pkt["uuid_valid"] = False
                except Exception as e:
                    # Log decoding errors but don't crash
                    pkt["decode_error"] = str(e)

                can_packets.append(pkt)

            # Move to next potential CAN frame
            sub_idx += total_can_len
        else:
            # No CAN header found, move to next byte
            sub_idx += 1

    return can_packets


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
