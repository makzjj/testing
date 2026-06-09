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
        summary["A1"] = "Programming"
        summary["B2"] = "Source"
        summary["C2"] = "Programmed"
        summary["D2"] = "Check"
        summary["A3"] = "Operator"
        summary["A4"] = "UUID"
        summary["A5"] = "PWM"
        summary["A6"] = "Proportionate (P)"
        summary["A7"] = "Integral (I)"
        summary["A8"] = "Derivative (D)"
        summary["A9"] = "PID_SlewRate"
        summary["A10"] = "RampDown_Slope"
        summary["A11"] = "RampDown_Step"
        summary["A12"] = "RampDown_MinVel"
        summary["A13"] = "RampDown_TargetOffset"
        summary["A14"] = "RampDown_Region"
        summary["A15"] = "Acceptable_Error"
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

    def test_read_expected_uuid_serial_reads_b4_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            workbook = load_workbook(template_path)
            workbook["3X"]["B5"] = None
            workbook["3X"]["B6"] = None
            workbook.save(template_path)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            serial = adapter.read_expected_uuid_serial()

        self.assertEqual(serial, "1223303010")

    def test_read_expected_pwm_value_reads_b5(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            pwm_value = adapter.read_expected_pwm_value()

        self.assertEqual(pwm_value, "100")

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

    def test_resolve_programming_row_maps_new_layout_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)

            self.assertEqual(adapter.resolve_programming_row("UUID"), 4)
            self.assertEqual(adapter.resolve_programming_row("Proportionate (P)"), 6)
            self.assertEqual(adapter.resolve_programming_row("PID_SlewRate"), 9)
            self.assertEqual(adapter.resolve_programming_row("RampDown_TargetOffset"), 13)

    def test_discover_programming_parameter_rows_scans_column_a_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)

            discovered_rows, raw_labels = adapter.discover_programming_parameter_rows()

        self.assertEqual(raw_labels, ["Operator", "UUID", "PWM", "Proportionate (P)", "Integral (I)", "Derivative (D)", "PID_SlewRate", "RampDown_Slope", "RampDown_Step", "RampDown_MinVel", "RampDown_TargetOffset", "RampDown_Region", "Acceptable_Error"])
        self.assertEqual(discovered_rows["uuid"], 4)
        self.assertEqual(discovered_rows["pwm"], 5)
        self.assertEqual(discovered_rows["proportionate (p)"], 6)
        self.assertEqual(discovered_rows["integral (i)"], 7)
        self.assertEqual(discovered_rows["derivative (d)"], 8)
        self.assertEqual(discovered_rows["pid_slewrate"], 9)
        self.assertEqual(discovered_rows["rampdown_slope"], 10)
        self.assertEqual(discovered_rows["rampdown_step"], 11)
        self.assertEqual(discovered_rows["rampdown_minvel"], 12)
        self.assertEqual(discovered_rows["rampdown_targetoffset"], 13)
        self.assertEqual(discovered_rows["rampdown_region"], 14)
        self.assertEqual(discovered_rows["acceptable_error"], 15)

    def test_write_programming_parameter_result_writes_row_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            template_path = self._create_ipqc_template(tmpdir)
            adapter = IpqcExcelAdapter()
            adapter.load_template(template_path)
            adapter.write_programming_parameter_result("RampDown_Region", "75", "PASS")
            output_path = Path(tmpdir) / "ipqc_completed.xlsx"
            adapter.save_completed_workbook(output_path)
            summary = load_workbook(output_path)["3X"]

        self.assertEqual(summary["C14"].value, "75")
        self.assertEqual(summary["D14"].value, "PASS")

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
