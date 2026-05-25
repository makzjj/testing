"""Unit tests for IPQC Excel adapter foundation behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.ipqc_excel_adapter import IpqcExcelAdapter

try:
    from openpyxl import Workbook, load_workbook

    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover - environment dependent.
    _HAS_OPENPYXL = False


@unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for IPQC Excel adapter tests.")
class IpqcExcelAdapterTests(unittest.TestCase):
    def _create_ipqc_template(self, base_dir: str | Path, filename: str = "ipqc_template.xlsx") -> Path:
        workbook = Workbook()
        summary = workbook.active
        summary.title = "3X"
        workbook.create_sheet("3X_D")
        workbook.create_sheet("3X_A")
        workbook.create_sheet("4Y")
        workbook.create_sheet("4Y_D")
        workbook.create_sheet("4Y_A")
        summary["B3"] = "operator-a"
        summary["B4"] = "1223303010"
        summary["B5"] = "100"
        summary["B6"] = "N/A"
        path = Path(base_dir) / filename
        workbook.save(path)
        return path

    def test_load_template_detects_base_sheet_groups_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            groups = adapter.load_template(template_path)

        self.assertEqual(groups, ["3X", "4Y"])
        self.assertEqual(adapter.active_sheet_group, "3X")

    def test_select_missing_sheet_group_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            with self.assertRaisesRegex(ValueError, "not available"):
                adapter.select_sheet_group("9PZ")

    def test_read_expected_summary_reads_sn_pwm_and_optional_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            expected = adapter.read_expected_summary(strict=True)

        self.assertEqual(expected.serial_number, "1223303010")
        self.assertEqual(expected.pwm, "100")
        self.assertEqual(expected.operator, "operator-a")
        self.assertEqual(expected.other_parameters, "N/A")

    def test_missing_required_expected_cell_is_reported_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            workbook = load_workbook(template_path)
            workbook["3X"]["B4"] = None
            workbook.save(template_path)

            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            with self.assertRaisesRegex(ValueError, "B4"):
                adapter.read_expected_summary(strict=True)

    def test_write_uuid_and_pwm_actual_and_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            adapter.write_uuid_actual_and_check("1223303011", "PASS")
            adapter.write_pwm_actual_and_check("98", "FAIL")
            output_path = Path(tmpdir) / "ipqc_completed.xlsx"
            adapter.save_completed_workbook(output_path)

            completed = load_workbook(output_path)
            summary = completed["3X"]

        self.assertEqual(summary["C4"].value, "1223303011")
        self.assertEqual(summary["D4"].value, "PASS")
        self.assertEqual(summary["C5"].value, "98")
        self.assertEqual(summary["D5"].value, "FAIL")

    def test_write_summary_result_maps_sn_pwm_and_other_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            adapter.write_summary_result("serial", "1223303012", "PASS")
            adapter.write_summary_result("PWM", "101", "FAIL")
            adapter.write_summary_result("Other parameters", "N/A", "PASS")
            output_path = Path(tmpdir) / "ipqc_completed.xlsx"
            adapter.save_completed_workbook(output_path)
            summary = load_workbook(output_path)["3X"]

        self.assertEqual(summary["C4"].value, "1223303012")
        self.assertEqual(summary["D4"].value, "PASS")
        self.assertEqual(summary["C5"].value, "101")
        self.assertEqual(summary["D5"].value, "FAIL")
        self.assertEqual(summary["C6"].value, "N/A")
        self.assertEqual(summary["D6"].value, "PASS")

    def test_write_summary_result_rejects_unknown_parameter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            with self.assertRaisesRegex(ValueError, "Unsupported summary parameter"):
                adapter.write_summary_result("temperature", "40", "PASS")

    def test_save_completed_workbook_uses_new_path_and_preserves_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            adapter.write_uuid_actual_and_check("1223303011", "PASS")
            output_path = Path(tmpdir) / "ipqc_completed.xlsx"
            saved_path = adapter.save_completed_workbook(output_path)

            original = load_workbook(template_path)["3X"]
            completed = load_workbook(saved_path)["3X"]

        self.assertEqual(saved_path, output_path.resolve())
        self.assertIsNone(original["C4"].value)
        self.assertEqual(completed["C4"].value, "1223303011")
        self.assertEqual(completed["D4"].value, "PASS")

    def test_save_rejects_overwriting_original_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                adapter.save_completed_workbook(template_path)

    def test_suggest_completed_output_path_is_in_template_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir, filename="line_a.xlsx")
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            suggested = adapter.suggest_completed_output_path()

        self.assertEqual(suggested.parent, template_path.parent)
        self.assertTrue(suggested.name.startswith("line_a_3X_completed_"))
        self.assertEqual(suggested.suffix, ".xlsx")


if __name__ == "__main__":
    unittest.main()
