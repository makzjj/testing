"""
Dedicated handler for Serial Monitor protocol reassembly and decoding.
"""

from serial_conn.packet_parser import parse_can_frames_from_uart_payload
from data.binary_cmd_parser import decode_command
from myconfig.constants import COMMANDS

class MonitorHandler:
    def __init__(self, direction):
        self.direction = direction
        self.buffer = bytearray()
        self.monitor_dialog = None # Will be set or used for callback
        
    def process_data(self, data):
        """
        Processes new raw bytes.
        Returns a list of decoded packet tuples:
        (direction, raw_frame, node_disp, cmd_name, decoded_info)
        """
        self.buffer.extend(data)
        decoded_packets = []
        
        idx = 0
        while idx < len(self.buffer):
            # 1. Look for a protocol header: Bridge: C8 24 or MCU: 25 A5
            found_header = False
            header_type = None
            
            if self.buffer[idx] == 0xC8:
                if idx + 1 < len(self.buffer):
                    if self.buffer[idx + 1] == 0x24:
                        found_header = True
                        header_type = "BRIDGE"
                else:
                    break 
            elif self.buffer[idx] == 0x25:
                if idx + 1 < len(self.buffer):
                    if self.buffer[idx + 1] == 0xA5:
                        found_header = True
                        header_type = "MCU"
                else:
                    break

            if found_header:
                # 2. Try to parse the packet
                packet_len = 0
                if header_type == "BRIDGE":
                    if idx + 4 <= len(self.buffer):
                        payload_len = self.buffer[idx + 3]
                        packet_len = 4 + payload_len
                    else:
                        break
                else: # MCU
                    if idx + 6 <= len(self.buffer):
                        payload_len = self.buffer[idx + 5]
                        packet_len = 8 + payload_len
                    else:
                        break

                if idx + packet_len <= len(self.buffer):
                    raw_frame = self.buffer[idx : idx + packet_len]
                    decoded_packets.append(self._decode_packet(header_type, raw_frame))
                    idx += packet_len
                    continue
                else:
                    break
            else:
                # 3. Handle noise until next potential header
                noise_start = idx
                while idx < len(self.buffer):
                    if self.buffer[idx] in [0xC8, 0x25]:
                        break
                    idx += 1
                
                noise_chunk = self.buffer[noise_start:idx]
                if noise_chunk:
                    decoded_packets.append((self.direction, noise_chunk, "---", "RAW", ""))

        # Update persistent buffer
        self.buffer = self.buffer[idx:]
        
        if len(self.buffer) > 8192: # Safety limit
            self.buffer.clear()
            
        return decoded_packets

    def _decode_packet(self, p_type, raw_frame):
        """Helper to decode a single reassembled frame."""
        node_id = None
        cmd_name = "Unknown"
        decoded_info = ""
        node_disp = "??"

        try:
            if p_type == "BRIDGE":
                node_id = raw_frame[2]
                payload = raw_frame[4:]
                node_disp = f"{node_id:02d}"
                
                # Check for nested MCU protocol (25 A5) inside the Bridge payload
                if len(payload) >= 2 and payload[0] == 0x25 and payload[1] == 0xA5:
                    inner_payload_len = payload[5] if len(payload) > 5 else 0
                    cmd_bytes = list(payload[6 : 6 + inner_payload_len])
                    cmd_name = "CAN_CMD"
                    
                    if len(cmd_bytes) > 0:
                        cmd_id = cmd_bytes[1] if len(cmd_bytes) >= 2 else cmd_bytes[0]
                        for name, val in COMMANDS.items():
                            if isinstance(val, list) and len(val) > 0 and val[0] == cmd_id:
                                cmd_name = name
                                break
                        if cmd_name == "Unknown": cmd_name = f"0x{cmd_id:02X}"
                    decoded_info = f"Data: {' '.join(f'{b:02X}' for b in cmd_bytes)}"
                else:
                    # Standard Bridge parsing
                    packets = parse_can_frames_from_uart_payload(bytes(payload), node_id)
                    if packets:
                        pkt = packets[0]
                        cmd = pkt.get("cmd", 0)
                        params = pkt.get("params", [])
                        
                        for name, val in COMMANDS.items():
                            if isinstance(val, list) and len(val) > 0 and val[0] == cmd:
                                cmd_name = name
                                break
                        if cmd_name == "Unknown": cmd_name = f"0x{cmd:02X}"

                        try:
                            res = decode_command(cmd, params)
                            if isinstance(res, tuple):
                                k, v = res
                                if k: decoded_info = f"{k}: {v}"
                            elif isinstance(res, dict):
                                decoded_info = ", ".join([f"{k}: {v}" for k, v in res.items() if k != "cmd"])
                        except: pass
                    else:
                        # Direct MCU response on UART
                        if len(payload) > 0:
                            cmd_bytes = list(payload)
                            for name, val in COMMANDS.items():
                                if isinstance(val, list) and len(val) > 0:
                                    if val[0] == cmd_bytes[0]:
                                        cmd_name = name
                                        break
                                    elif len(cmd_bytes) >= 2 and val[0] == cmd_bytes[1]:
                                        cmd_name = name
                                        break
                            if cmd_name == "Unknown": cmd_name = "DIRECT_UART"
                            decoded_info = f"Raw: {' '.join(f'{b:02X}' for b in cmd_bytes)}"
            
            else: # MCU Protocol (25 A5)
                node_id = raw_frame[3]
                node_disp = f"{node_id:02d}"
                payload_len = raw_frame[5]
                cmd_bytes = list(raw_frame[6 : 6 + payload_len])
                cmd_name = "APP_CMD"
                
                if len(cmd_bytes) > 0:
                    cmd_id = cmd_bytes[1] if len(cmd_bytes) >= 2 else cmd_bytes[0]
                    for name, val in COMMANDS.items():
                        if isinstance(val, list) and len(val) > 0 and val[0] == cmd_id:
                            cmd_name = name
                            break
                    if cmd_name == "Unknown": cmd_name = f"0x{cmd_id:02X}"
                    decoded_info = f"Data: {' '.join(f'{b:02X}' for b in cmd_bytes)}"

        except Exception as e:
            cmd_name = "PARSE_ERR"
            decoded_info = f"{type(e).__name__}: {str(e)}"

        return (self.direction, raw_frame, node_disp, cmd_name, decoded_info)
