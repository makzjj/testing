# serial_conn/firmware_log_parser.py
"""
Firmware semantic log parser.

Intercepts and parses human-readable logs from MCU firmware that contain
motor state transitions, sensor events, and initialization sequences.

Expected firmware log format:
  "MCU @[Z] reference found (SENSOR)"
  "MCU @[Z] max: 0.00"
  "MCU @[N] stopped by sensor L"
  "MCU @[N] reset physical position to 0"
  "MCU @[Y] start moving to max pos: -3.00"
  "MCU @[H] start searching reference"
  "MCU @[Y] motor reached max pos"
  "MCU @[Y] motor cleared"
"""

import re
from datetime import datetime
from typing import Optional, Dict, Any


class FirmwareLogParser:
    """Parse semantic logs from MCU firmware via UART."""
    
    # Pattern: MCU @[AXIS] EVENT [: VALUE]
    FIRMWARE_LOG_PATTERN = re.compile(
        r"MCU\s+@\[([A-Z])\]\s+(.+?)(?::\s+([-\d.]+))?$",
        re.IGNORECASE
    )
    
    # Event keywords to recognize
    RECOGNIZED_EVENTS = {
        # Reference/Initialization events
        "reference found": "reference_found",
        "searching reference": "searching_reference",
        "stopped by sensor": "stopped_by_sensor",
        "reset physical position": "reset_position",
        
        # Motor state events
        "motor cleared": "motor_cleared",
        "motor reached max pos": "motor_reached_max",
        "motor reached min pos": "motor_reached_min",
        
        # Movement events
        "start moving to max pos": "start_moving_to_max",
        "start moving to min pos": "start_moving_to_min",
        "start clearing": "start_clearing",
        
        # Calibration results
        "max": "max_position",
        "min": "min_position",
    }
    
    def __init__(self):
        """Initialize the firmware log parser."""
        pass
    
    def is_firmware_log(self, text: str) -> bool:
        """Check if text is a firmware semantic log line."""
        return bool(self.FIRMWARE_LOG_PATTERN.search(text))
    
    def parse_log_line(
        self,
        text: str,
        rx_timestamp: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a single firmware log line.
        
        Args:
            text: Raw text from firmware
            rx_timestamp: Timestamp when UART data was received
        
        Returns:
            Parsed log entry dict or None if not a valid firmware log
        
        Example output:
            {
                "timestamp": "2026-04-30T09:50:31.961000",
                "axis": "Z",
                "event": "reference_found",
                "event_raw": "reference found",
                "value": None,
                "details": "SENSOR",
                "raw": "MCU @[Z] reference found (SENSOR)",
                "source": "firmware_uart"
            }
        """
        match = self.FIRMWARE_LOG_PATTERN.search(text)
        if not match:
            return None
        
        axis, event_text, value_str = match.groups()
        
        # Try to normalize event name
        event_normalized = None
        details = None
        
        for keyword, normalized in self.RECOGNIZED_EVENTS.items():
            if keyword.lower() in event_text.lower():
                event_normalized = normalized
                break
        
        # If no match found, use lowercased event text
        if not event_normalized:
            event_normalized = event_text.lower().replace(" ", "_").replace(":", "")
        
        # Extract details in parentheses (e.g., "(SENSOR)" or "(L)" for left sensor)
        details_match = re.search(r'\(([^)]+)\)', event_text)
        if details_match:
            details = details_match.group(1)
        
        # Convert value to float if present
        value = None
        if value_str:
            try:
                value = float(value_str)
            except ValueError:
                value = value_str
        
        # Use provided timestamp or generate current one
        if rx_timestamp is None:
            rx_timestamp = datetime.now()
        
        return {
            "timestamp": rx_timestamp.isoformat(),
            "axis": axis,
            "event": event_normalized,
            "event_raw": event_text.strip(),
            "value": value,
            "details": details,
            "raw": text.strip(),
            "source": "firmware_uart"
        }
    
    def parse_log_bytes(
        self,
        payload: bytes,
        rx_timestamp: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Parse a firmware log from raw UART payload bytes.
        
        Args:
            payload: Raw bytes from UART direct_uart packet
            rx_timestamp: Timestamp when data was received
        
        Returns:
            Parsed log entry or None
        """
        try:
            text = payload.decode('utf-8', errors='ignore').strip()
            if text and self.is_firmware_log(text):
                return self.parse_log_line(text, rx_timestamp)
        except Exception:
            pass
        
        return None
