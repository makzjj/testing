"""File-backed raw RX logging used by runtime UIs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class RxLogWriter:
    """Writes raw RX bytes to a timestamped log file."""

    def __init__(self, log_file_path: Path) -> None:
        self.log_file_path = log_file_path

    @classmethod
    def create(cls, project_root: Path) -> "RxLogWriter":
        log_dir = project_root / "logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(log_dir / f"rx_data_log_{timestamp}.txt")

    def write_rx_data(self, data: bytes) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        hex_data = " ".join(f"{byte:02X}" for byte in data)
        with self.log_file_path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(f"[{timestamp}] RX: {hex_data}\n")
