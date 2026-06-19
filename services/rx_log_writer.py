"""File-backed raw RX logging used by runtime UIs."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from utils.deployment_paths import get_runtime_logs_dir


class RxLogWriter:
    """Writes raw RX bytes to a timestamped log file."""

    def __init__(self, log_file_path: Path) -> None:
        self.log_file_path = log_file_path

    @classmethod
    def create(cls, project_root: Path | None = None) -> "RxLogWriter":
        log_dir = (Path(project_root) / "logs") if project_root is not None else get_runtime_logs_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(log_dir / f"rx_data_log_{timestamp}.txt")

    def write_rx_data(self, data: bytes) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        hex_data = " ".join(f"{byte:02X}" for byte in data)
        with self.log_file_path.open("a", encoding="utf-8") as file_handle:
            file_handle.write(f"[{timestamp}] RX: {hex_data}\n")
