# utils/checksum.py
"""Checksum utility functions."""

def fletcher_checksum(data: bytes) -> (int,int):
    """Calculate Fletcher checksum for given data."""
    chkA = 0
    chkB = 0
    for b in data:
        chkA = (chkA + b) % 256
        chkB = (chkB + chkA) % 256

        #print(f"Calculated checksum: {chkA:02X} {chkB:02X}")
    return chkA, chkB

def calc_checksum(data: bytes)-> (int,int):
    """Calculate Fletcher checksum for the entire data array."""
    a = b = 0
    for byte in data[2:]:  # Include ALL bytes
        a = (a + byte) & 0xFF
        b = (b + a) & 0xFF
    #print(f"Calculated checksum: {a:02X} {b:02X}")
    return a, b

# utils/logger.py
"""Logging utility functions."""

from PyQt6.QtCore import QDateTime


def get_timestamp():
    """Get current timestamp in formatted string."""
    return QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")
