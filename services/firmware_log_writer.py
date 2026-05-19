"""File-backed firmware semantic log writer."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any


class FirmwareLogWriter:
    """Writes parsed firmware semantic logs to timestamped files."""
    
    def __init__(self, log_file_path: Path) -> None:
        """
        Initialize the firmware log writer.
        
        Args:
            log_file_path: Path to the log file to write to
        """
        self.log_file_path = log_file_path
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)
    
    @classmethod
    def create(cls, project_root: Path) -> FirmwareLogWriter:
        """
        Create a firmware log writer with auto-generated daily filename.
        
        Args:
            project_root: Root directory of the project
        
        Returns:
            FirmwareLogWriter instance
        """
        log_dir = project_root / "logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(log_dir / f"firmware_semantic_log_{timestamp}.log")
    
    def write_log_entry(self, log_entry: Dict[str, Any]) -> None:
        """
        Write a parsed firmware log entry to file.
        
        Format:
            [timestamp] @[AXIS] EVENT [: VALUE]
            Raw: MCU @[Z] reference found (SENSOR)
            Parsed: {...JSON...}
        
        Args:
            log_entry: Parsed firmware log dict from FirmwareLogParser
        """
        if not log_entry:
            return
        
        try:
            timestamp = log_entry.get("timestamp", "")
            axis = log_entry.get("axis", "?")
            event = log_entry.get("event", "unknown")
            value = log_entry.get("value", "")
            details = log_entry.get("details", "")
            raw = log_entry.get("raw", "")
            
            # Format: [timestamp] MCU @[AXIS] event: value (details)
            line = f"[{timestamp}] MCU @[{axis}] {event}"
            if value is not None:
                line += f": {value}"
            if details:
                line += f" ({details})"
            
            with self.log_file_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
                # Optionally write raw and JSON for debugging
                f.write(f"  Raw: {raw}\n")
                f.write(f"  JSON: {json.dumps(log_entry)}\n")
        
        except Exception as e:
            print(f"Failed to write firmware log: {e}")
    
    def write_raw_bytes(self, data: bytes) -> None:
        """
        Write raw UART bytes for debugging purposes.
        
        Args:
            data: Raw bytes received from UART
        """
        try:
            hex_data = " ".join(f"{byte:02X}" for byte in data)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            with self.log_file_path.open("a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] RAW: {hex_data}\n")
        except Exception as e:
            print(f"Failed to write raw bytes: {e}")
