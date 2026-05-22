"""CSV-only production result logger."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .production_test_result import ProductionTestResult

_CSV_HEADERS = [
    "run_id",
    "job_id",
    "timestamp_utc",
    "node_id",
    "node_name",
    "test_type",
    "expected_value",
    "actual_value",
    "result",
    "failure_reason",
    "raw_response_hex",
]


class ProductionCsvLogger:
    """Writes one structured production result row per test action."""

    def __init__(
        self,
        output_dir: str | Path | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        self._run_id = str(run_id or uuid4())
        self._output_dir = Path(output_dir) if output_dir is not None else (Path.cwd() / "production_results")
        self._result_csv_path: Path | None = None

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def result_csv_path(self) -> Path | None:
        return self._result_csv_path

    def set_output_dir(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)
        self._result_csv_path = None

    def append_result(self, result: ProductionTestResult) -> Path:
        csv_path = self._ensure_result_csv_path()
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        file_exists = csv_path.exists()

        with csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_CSV_HEADERS)
            if not file_exists:
                writer.writeheader()
            writer.writerow(self._to_row_dict(result))

        return csv_path

    def _ensure_result_csv_path(self) -> Path:
        if self._result_csv_path is not None:
            return self._result_csv_path
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._result_csv_path = self._output_dir / f"production_result_{stamp}_{self._run_id}.csv"
        return self._result_csv_path

    def _to_row_dict(self, result: ProductionTestResult) -> dict[str, str]:
        row = {
            "run_id": result.run_id or self._run_id,
            "job_id": result.job_id,
            "timestamp_utc": result.timestamp_utc or datetime.now(timezone.utc).isoformat(),
            "node_id": result.node_id,
            "node_name": result.node_name,
            "test_type": result.test_type,
            "expected_value": result.expected_value,
            "actual_value": result.actual_value,
            "result": result.result,
            "failure_reason": result.failure_reason,
            "raw_response_hex": result.raw_response_hex,
        }
        safe: dict[str, str] = {}
        for key in _CSV_HEADERS:
            value = row.get(key)
            safe[key] = "" if value is None else str(value)
        return safe
