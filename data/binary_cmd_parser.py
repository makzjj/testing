# data/binary_cmd_parser.py
"""
Binary command parser for CAN-over-UART responses.

Handles parsing of:
- 0xC8 GET_VERSION
- 0xCD GET_NODETYPE
- 0xE0 GET_UUID
- 0xD8 GET_INTERRUPT
"""

def parse_get_tof(params):
    """Decode ToF sensor response (0xAB).
    Format: 3A [raw_hi] [raw_lo] [filtered_int] [decimal_places]
    """
    if len(params) >= 5 and params[0] == 0x3A:
        raw_hi = params[1]
        raw_lo = params[2]
        filtered_val = params[3]
        decimal_places = params[4]  # Currently 0
        
        raw_mm = (raw_hi << 8) | raw_lo
        # Filtered value is currently an 8-bit integer in params[3]
        filtered_mm = float(filtered_val)
        
        return {
            "raw": float(raw_mm),
            "filtered": filtered_mm
        }
    return None


def parse_get_version(params):
    """Decode firmware version response (0xC8)."""
    if len(params) >= 4 and params[0] == 0x3A:
        verMaj = (params[1] >> 4) & 0x0F
        verMin = params[1] & 0x0F
        verSub = (params[2] >> 4) & 0x0F
        verSubNum = ((params[2] & 0x0F) << 8) | params[3]
        return f"v{verMaj}.{verMin}.{verSub}.{verSubNum}"
    return "Invalid"


def parse_get_nodetype(params):
    """Decode node type response (0xCD)."""
    if len(params) >= 2 and params[0] == 0x3A:
        type_code = params[1]
        node_types = {
            1: "MTR (Motor Controller)",
            2: "HMI (Human Interface)",
            3: "S32 (Master MCU)",
            4: "NGC (Needle Guide Controller)",
            5: "SWAB (Master SWAB)",
            6: "DSP (Master DSP)",
            7: "SENSOR (Sensor Node)",
            8: "STM32_Y (ACCuESS)",
            9: "STM32_R (ACCuESS)",
            0: "DSI (Master dsPIC)"
        }
        return node_types.get(type_code, f"Unknown({type_code})")
    return "Invalid"


def parse_get_uuid(params):
    """Decode UUID/serial number response (0xE0).
    Format: 3A [uuid_hi] [b3] [b2] [b1] [b0]
    Example: 3A 00 07 5B CD 15 -> 123456789
    """
    try:
        # Expect 6 bytes total: 3A + 5 data bytes
        if len(params) >= 6 and params[0] == 0x3A:
            # Extract the 5 UUID bytes (big-endian)
            uuid_bytes = params[1:6]

            serial_num = 0
            for b in uuid_bytes:
                serial_num = (serial_num << 8) | b

            # Return both numeric and formatted string
            return f"{serial_num} (0x{serial_num:010X})"
        else:
            return "Invalid"

    except Exception as e:
        return f"Error: {e}"




def parse_get_interrupt(params):
    """Decode sensor interrupt response (0xD8)."""
    if len(params) >= 3 and params[0] == 0x3A:
        left_ok = params[1] == 0x01
        right_ok = params[2] == 0x01

        left_status = "OK" if left_ok else "Cut"
        right_status = "OK" if right_ok else "Cut"
        left_color = "green" if left_ok else "red"
        right_color = "green" if right_ok else "red"

        return {
            'text': f"L: {left_status} R: {right_status}",
            'left_ok': left_ok,
            'right_ok': right_ok,
            'left_color': left_color,
            'right_color': right_color,
            'left_status': left_status,
            'right_status': right_status
        }
    return {
        'text': 'Invalid',
        'left_ok': False,
        'right_ok': False,
        'left_color': 'red',
        'right_color': 'red',
        'left_status': 'Invalid',
        'right_status': 'Invalid'
    }


def parse_comm_test_frame(params):
    """Decode communication test frame (0xBF).
    Format: [seq_hi] [seq_lo]
    """
    if len(params) >= 2:
        seq = (params[0] << 8) | params[1]
        return seq
    return None


def parse_comm_stats(params):
    """Decode MCU communication statistics (0xBC).
    Format: [can_rx:4] [uart_tx:4] [uart_rx:4]
    """
    if len(params) >= 12:
        can_rx = (params[0] << 24) | (params[1] << 16) | (params[2] << 8) | params[3]
        uart_tx = (params[4] << 24) | (params[5] << 16) | (params[6] << 8) | params[7]
        uart_rx = (params[8] << 24) | (params[9] << 16) | (params[10] << 8) | params[11]
        return {
            "can_rx": can_rx,
            "uart_tx": uart_tx,
            "uart_rx": uart_rx
        }
    return None


def parse_get_sys_mode(params):
    """Decode system mode response (0xB5).
    Format: 3A [node_id] [state_value] [error_count] [err0:4] ...
    """
    if len(params) >= 4 and params[0] == 0x3A:
        node_id = params[1]
        state = params[2]
        error_count = min(params[3], 5)
        available_errors = max(0, (len(params) - 4) // 4)
        parsed_error_count = min(error_count, available_errors)

        errors = []
        offset = 4
        for _ in range(parsed_error_count):
            code = (
                (params[offset] << 24)
                | (params[offset + 1] << 16)
                | (params[offset + 2] << 8)
                | params[offset + 3]
            )
            errors.append(code)
            offset += 4

        states = {
            0: {"text": "System Off", "color": "#000000", "blink": 0},
            1: {"text": "Boot", "color": "#0066FF", "blink": 1},
            2: {"text": "Ready", "color": "#00C800", "blink": 0},
            3: {"text": "Moving", "color": "#FFCC00", "blink": 0},
            4: {"text": "Needle Ready", "color": "#00C800", "blink": 0},
            5: {"text": "Fault", "color": "#FF0000", "blink": 3},
            6: {"text": "Manual Rotate", "color": "#FFCC00", "blink": 0},
            7: {"text": "Custom", "color": "#00C800", "blink": 0},
        }

        # Board responses use state 0 as OK. MCU node 0x01 uses state 0 as System Off.
        if node_id != 0x01 and state == 0:
            result = {"text": "Board OK", "color": "#00C800", "blink": 0}
        else:
            result = states.get(state, {"text": f"Unknown({state})", "color": "#808080", "blink": 0})

        if errors and result["text"] != "Fault":
            result = {"text": "Fault", "color": "#FF0000", "blink": 3}

        error_hex = [f"0x{code:08X}" for code in errors]
        result.update({
            "node_id": node_id,
            "state_value": state,
            "error_count": error_count,
            "errors": error_hex,
            "error_code": error_hex[0] if error_hex else None,
        })
        return result

    # Legacy support for older responses: 3A [state_byte].
    if len(params) >= 2 and params[0] == 0x3A:
        return parse_get_sys_mode([0x3A, 0x01, params[1], 0x00])
    return None


def parse_tpos(params):
    """Decode TPOS (Target/Total Position) response (0x81).
    Format: [type_char] [pos_hi] [pos_mid_hi] [pos_mid_lo] [pos_lo]
    Example: 45 00 02 40 03 -> ('E', 147459)
    """
    if len(params) >= 5:
        try:
            type_char = chr(params[0])
            # Use int.from_bytes for signed 32-bit big-endian position
            position = int.from_bytes(bytes(params[1:5]), byteorder='big', signed=True)
            return type_char, position
        except Exception:
            return None
def parse_getpos(params):
    """Decode GETPOS response (0x82).
    Format 1: 3A [pos:4]
    Format 2: [pos:4]
    Returns: ('G', position)
    """
    if len(params) >= 5 and params[0] == 0x3A:
        try:
            position = int.from_bytes(bytes(params[1:5]), byteorder='big', signed=True)
            return 'G', position
        except Exception: return None
    elif len(params) >= 4:
        try:
            position = int.from_bytes(bytes(params[0:4]), byteorder='big', signed=True)
            return 'G', position
        except Exception: return None
    return None


def decode_command(cmd, params):
    """Generic command dispatcher for decoding."""
    if cmd == 0xC8:
        return ("firmware", parse_get_version(params))
    elif cmd == 0xCD:
        return ("type", parse_get_nodetype(params))
    elif cmd == 0xE0:
        return ("uuid", parse_get_uuid(params))
    elif cmd == 0xD8:
        interrupt_data = parse_get_interrupt(params)
        return 'interrupt', interrupt_data['text']
    elif cmd == 0xAB:
        return ("tof_distance", parse_get_tof(params))
    elif cmd == 0xBF:
        return ("comm_test_val", parse_comm_test_frame(params))
    elif cmd == 0xBC:
        return ("comm_stats", parse_comm_stats(params))
    elif cmd == 0x81:
        # Return raw (type_char, position) tuple for cleaner processing
        return ("tpos", parse_tpos(params))
    elif cmd == 0x82:
        return ("getpos", parse_getpos(params))
    elif cmd == 0xBE:
        # ACK response from MCU: 3A 41 43 4B ('ACK')
        if len(params) >= 4 and params[0] == 0x3A and params[1:4] == [0x41, 0x43, 0x4B]:
            return ("comm_test_start", "ACK")
        return ("comm_test_start", "NACK")
    elif cmd == 0xB5:
        return ("sys_mode", parse_get_sys_mode(params))
    elif cmd == 0xB7:
        if len(params) > 0 and params[0] == 0x53: # 'S'
            return ("move_yayb", "OK")
        return ("move_yayb", "Unknown")
    else:
        return (None, None)
