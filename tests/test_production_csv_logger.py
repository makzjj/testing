"""Unit tests for structured Production CSV result logging."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from services.production_csv_logger import ProductionCsvLogger
from services.production_test_result import ProductionTestResult


class ProductionCsvLoggerTests(unittest.TestCase):
    def _read_rows(self, csv_path: Path) -> list[dict[str, str]]:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def test_result_csv_header_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-1")
            csv_path = logger.append_result(
                ProductionTestResult(node_id=6, node_name="H", test_type="UUID_VERIFY", result="PASS")
            )

            rows = self._read_rows(csv_path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0].keys(),
                {
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
                },
            )

    def test_result_row_is_appended_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-2")
            csv_path = logger.append_result(
                ProductionTestResult(
                    job_id="job-a",
                    node_id=8,
                    node_name="RZ",
                    test_type="NODE_COMMUNICATION_TEST",
                    expected_value="Expected",
                    actual_value="Actual",
                    result="PASS",
                    failure_reason="",
                    raw_response_hex="82 01",
                )
            )

            rows = self._read_rows(csv_path)
            self.assertEqual(rows[0]["run_id"], "run-2")
            self.assertEqual(rows[0]["job_id"], "job-a")
            self.assertEqual(rows[0]["node_id"], "8")
            self.assertEqual(rows[0]["raw_response_hex"], "82 01")

    def test_multiple_result_rows_append_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-3")
            csv_path = logger.append_result(
                ProductionTestResult(node_id=3, node_name="X", test_type="NODE_COMMUNICATION_TEST", result="PASS")
            )
            logger.append_result(
                ProductionTestResult(node_id=4, node_name="Y", test_type="NODE_COMMUNICATION_TEST", result="FAIL")
            )

            rows = self._read_rows(csv_path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["node_id"], "3")
            self.assertEqual(rows[1]["node_id"], "4")

    def test_input_csv_is_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_csv = Path(tmpdir) / "uuid_input.csv"
            original_text = "node_id,node_name,uuid\n6,H,1223306010\n"
            input_csv.write_text(original_text, encoding="utf-8")

            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-4")
            logger.append_result(ProductionTestResult(node_id=6, node_name="H", test_type="UUID_VERIFY", result="PASS"))

            self.assertEqual(input_csv.read_text(encoding="utf-8"), original_text)

    def test_uuid_verify_result_can_be_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-5")
            csv_path = logger.append_result(
                ProductionTestResult(
                    node_id=6,
                    node_name="H",
                    test_type="UUID_VERIFY",
                    expected_value="1223306010",
                    actual_value="1223306010",
                    result="PASS",
                    failure_reason="",
                    raw_response_hex="E0 3A 00 48 EA 2B 1A",
                )
            )

            row = self._read_rows(csv_path)[0]
            self.assertEqual(row["test_type"], "UUID_VERIFY")
            self.assertEqual(row["result"], "PASS")

    def test_node_test_result_can_be_logged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-6")
            csv_path = logger.append_result(
                ProductionTestResult(
                    node_id=8,
                    node_name="RZ",
                    test_type="NODE_COMMUNICATION_TEST",
                    expected_value="CAN response with decoded getpos payload",
                    actual_value="456",
                    result="PASS",
                )
            )

            row = self._read_rows(csv_path)[0]
            self.assertEqual(row["node_name"], "RZ")
            self.assertEqual(row["actual_value"], "456")

    def test_missing_optional_values_do_not_crash_logger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = ProductionCsvLogger(output_dir=tmpdir, run_id="run-7")
            csv_path = logger.append_result(
                ProductionTestResult(
                    node_id=10,
                    node_name="HMI",
                    test_type="NODE_COMMUNICATION_TEST",
                    expected_value=None,
                    actual_value={"raw": 1},
                    result="FAIL",
                    failure_reason=None,
                    raw_response_hex=None,
                )
            )

            row = self._read_rows(csv_path)[0]
            self.assertEqual(row["expected_value"], "")
            self.assertEqual(row["actual_value"], "{'raw': 1}")
            self.assertEqual(row["failure_reason"], "")


if __name__ == "__main__":
    unittest.main()
