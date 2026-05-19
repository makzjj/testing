# serial_conn/app_protocol_handler.py
"""Dedicated handler for application-level protocol logic and packet dispatch."""
from datetime import datetime
from data.binary_cmd_parser import decode_command, parse_get_interrupt
from serial_conn.packet_parser import parse_uart_rx_packets
from serial_conn.firmware_log_parser import FirmwareLogParser
from myconfig.constants import BCMD_GET_NODE_ID, BCMD_ZPOSS

class AppProtocolHandler:
    def __init__(self, callbacks=None):
        """
        Initialize the handler.
        
        callbacks: dict of functions to handle specific events:
            'node_activity': func(node_id)
            'interrupt': func(node_id, interrupt_data)
            'sys_mode': func(val)
            'status_field': func(node_id, key, val)
            'zposs': func(adc_raw, phys_val)
            'tof': func(val)
            'uuid': func(node_id, uuid, valid)
            'node_id_response': func(node_id, params)
            'comm_stats': func(stats)
            'test_packet': func(node_id, seq)
            'test_finished': func(node_id)
            'node_version': func(node_id, version)
            'mcu_version': func(version)
            'firmware_log': func(log_entry)  # NEW: Firmware semantic logs
            'log': func(msg)
            'packet_error': func(status)
        """
        self.rx_buffer = bytearray()
        self.callbacks = callbacks or {}
        self.firmware_log_parser = FirmwareLogParser()

    def _trigger(self, event, *args, **kwargs):
        """Helper to safely trigger a callback."""
        callback = self.callbacks.get(event)
        if callback:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                self._trigger('log', f"⚠️ Error in callback '{event}': {e}")

    def process_incoming_data(self, data: bytes):
        """Feed raw hardware data to the buffer and process any complete packets."""
        if not data:
            return

        self.rx_buffer += data
        
        try:
            # Reassembly delegated to standard parser
            packets, self.rx_buffer = parse_uart_rx_packets(self.rx_buffer)

            for pkt in packets:
                if pkt.get("status") == "ok":
                    self._process_ok_packet(pkt)
                else:
                    self._trigger('packet_error', pkt.get('status', 'unknown'))
        except Exception as e:
            self._trigger('log', f"❌ Critical error in AppProtocolHandler: {e}")

    def _process_ok_packet(self, pkt):
        """Internal dispatch logic for valid packets."""
        pkt_type = pkt.get("type")
        
        if pkt_type == "can_over_uart" and 'sender' in pkt:
            node_id = pkt['sender']
            cmd = pkt.get('cmd', 0)
            params = pkt.get('params', [])
            
            # 1. Communication Monitor logic
            if cmd == 0xBF: # BCMD_COMM_TEST_FRAME
                seq = (params[0] << 8) | params[1] if len(params) >= 2 else None
                if seq is not None:
                    self._trigger('test_packet', node_id, seq)
            elif cmd == 0xBD: # BCMD_COMM_TEST_FINISHED
                self._trigger('test_finished', node_id)
            elif cmd == 0xC8: # BCMD_GET_VERSION
                _, version = decode_command(cmd, params)
                self._trigger('node_version', node_id, version)

            # 2. Node tracking logic (Nodes 2-17 are CAN devices)
            if 2 <= node_id <= 17:
                self._trigger('node_activity', node_id)
                
                # Interrupts
                if cmd == 0xD8: # GET_INTERRUPT
                    interrupt_data = parse_get_interrupt(params)
                    if isinstance(interrupt_data, dict) and 'text' in interrupt_data:
                        self._trigger('interrupt', node_id, interrupt_data)

                # General decoding
                key, val = decode_command(cmd, params)
                if key == "sys_mode" and val is not None:
                    self._trigger('sys_mode', val)
                    if isinstance(val, dict) and val.get("errors"):
                        self._trigger('error_log', val)
                elif key == "comm_stats":
                    self._trigger('comm_stats', val)
                elif key:
                    self._trigger('status_field', node_id, key, val)
                
                # ZPOSS Plotting
                if 'adc_raw' in pkt and 'physical_value' in pkt:
                    self._trigger('zposs', pkt['adc_raw'], pkt['physical_value'])

                # ToF Plotting
                if key == "tof_distance":
                    self._trigger('tof', val)

                # UUID Handling
                if pkt.get("uuid_response"):
                    uuid = pkt.get("uuid", "Unknown")
                    valid = pkt.get("uuid_valid", False)
                    self._trigger('uuid', node_id, uuid, valid)

                # Node ID Confirmation
                if cmd == BCMD_GET_NODE_ID:
                    self._trigger('node_id_response', node_id, params)

        elif pkt_type == "direct_uart":
            payload = pkt.get("raw_payload", [])
            if payload:
                # NEW: Try to parse as firmware semantic log first
                payload_bytes = bytes(payload)
                try:
                    text = payload_bytes.decode('utf-8', errors='ignore').strip()
                    if text and self.firmware_log_parser.is_firmware_log(text):
                        parsed_log = self.firmware_log_parser.parse_log_line(
                            text,
                            datetime.now()
                        )
                        if parsed_log:
                            self._trigger('firmware_log', parsed_log)
                            return  # Handled as firmware log
                except Exception:
                    pass
                
                # Fall through to standard protocol handling
                cmd = payload[0]
                params = payload[1:]
                
                # Global SysMode
                key, val = decode_command(cmd, params)
                if key == "sys_mode" and val is not None:
                    self._trigger('sys_mode', val)
                    if isinstance(val, dict) and val.get("errors"):
                        self._trigger('error_log', val)
                
                # Communication Stats
                if cmd == 0xBC: # COMM_STATS
                    from data.binary_cmd_parser import parse_comm_stats
                    stats = parse_comm_stats(payload[1:])
                    if stats:
                        self._trigger('comm_stats', stats)
                
                # MCU Version
                if pkt.get("mcu_version_response"):
                    version = pkt.get("mcu_version", "Unknown")
                    self._trigger('mcu_version', version)
