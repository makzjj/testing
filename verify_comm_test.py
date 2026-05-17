import sys
import os

# Add project root to path
project_root = r"D:\PycharmProjects\Biobot_Robot_Arm_Tester"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from serial_conn.packet_parser import parse_uart_rx_packets
from utils.checksum import calc_checksum

def test_parser():
    # Mock a CAN-over-UART packet for command 0xBF (COMM_TEST_FRAME)
    # 25 A5 [sender] [target] [port] [len] [cmd] [params] [chk_a] [chk_b]
    node_id = 0x03 # Ya
    seq = 0x1234
    can_payload = [0xBF, (seq >> 8) & 0xFF, seq & 0xFF]
    can_packet = [0x25, 0xA5, node_id, 0x01, 0x31, len(can_payload)] + can_payload
    chk_a, chk_b = calc_checksum(can_packet)
    can_packet += [chk_a, chk_b]
    
    # Wrap in UART frame: C8 24 [node_id] [payload_len] [payload]
    uart_packet = [0xC8, 0x24, 0x01, len(can_packet)] + can_packet
    
    buffer = bytearray(uart_packet)
    print(f"Testing with buffer: {buffer.hex(' ')}")
    
    packets, leftover = parse_uart_rx_packets(buffer)
    
    print(f"Parsed {len(packets)} packets")
    for p in packets:
        print(f"Packet: {p}")
        if p.get('cmd') == 0xBF:
            print(f"Success: Found 0xBF packet with value {p.get('decoded_value')}")
            assert p.get('decoded_value') == seq
            print("Assertion passed!")
        else:
            print(f"❌ Error: Expected 0xBF, got {p.get('cmd')}")

if __name__ == "__main__":
    test_parser()
