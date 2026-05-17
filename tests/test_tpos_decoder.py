import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from data.binary_cmd_parser import decode_command

def test_tpos_decoding():
    # Sample data provided by user: [45 00 02 40 03]
    # 45 is 'E', 0x00024003 is 147459
    cmd = 0x81
    params = [0x45, 0x00, 0x02, 0x40, 0x03]
    
    key, value = decode_command(cmd, params)
    
    print(f"Testing Command 0x81 with params {params}")
    print(f"Decoded Key: {key}")
    print(f"Decoded Value: {value}")
    
    assert key == "tpos"
    assert "TPOS 'E' at position: 147459" in value
    print("Test Passed!")

if __name__ == "__main__":
    try:
        test_tpos_decoding()
    except Exception as e:
        print(f"Test Failed: {e}")
        sys.exit(1)
