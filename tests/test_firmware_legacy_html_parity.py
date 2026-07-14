from __future__ import annotations

import unittest

from gui.workspace.models import FirmwareFitReport, FirmwareTestResult
from services.firmware_report_builder import FirmwareReportBuilder


class FirmwareLegacyHtmlParityTests(unittest.TestCase):
    def _report(self, *, mode: str = "binary") -> FirmwareFitReport:
        return FirmwareFitReport(
            run_id="fit-1",
            mode=mode,
            started_at="100.000",
            completed_at="101.000",
            duration_ms=1000.0,
            overall_status="PASSED",
            selected_case_count=1,
            completed_case_count=1,
            target_node_id=3 if mode == "binary" else None,
            passed_count=1,
            results=(
                FirmwareTestResult(
                    case_id="case-1",
                    status="PASS",
                    mode=mode,
                    case_name="<GETVER>",
                    command_display="GETVER",
                    expected="firmware",
                    actual="firmware:<v1>",
                    tx_bytes=bytes([0xC8, 0x3F]),
                    rx_bytes=bytes([0xC8, 0x3A, 0x12, 0x30, 0x01]),
                    latency_ms=12.5,
                    message='operator "ok" & note',
                    manual_verification_outcome="passed",
                ),
            ),
        )

    def test_legacy_report_section_order_and_columns_are_reproduced(self) -> None:
        html = FirmwareReportBuilder().build_html(self._report())
        self.assertLess(html.index("<div class='header'>"), html.index("<div class='summary pass'>"))
        self.assertLess(html.index("<div class='summary pass'>"), html.index("<table>"))
        expected_columns = [
            "Command Name",
            "Status",
            "Expected",
            "Actual Response",
            "Latency",
        ]
        positions = [html.index(column) for column in expected_columns]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("BioBot Firmware Integration Test Report", html)
        self.assertIn("Target Node ID", html)
        self.assertIn("Overall Result: 1 / 1 Passed", html)

    def test_html_uses_biobot_orange_and_escapes_dynamic_content(self) -> None:
        html = FirmwareReportBuilder().build_html(self._report())
        self.assertIn("#f47c20", html)
        self.assertIn("&lt;GETVER&gt;", html)
        self.assertIn("firmware:&lt;v1&gt;", html)
        self.assertIn("operator &quot;ok&quot; &amp; note", html)
        self.assertIn("TX: C8 3F<br>RX: C8 3A 12 30 01", html)

    def test_text_report_omits_binary_target_node_metadata(self) -> None:
        html = FirmwareReportBuilder().build_html(self._report(mode="text"))
        self.assertIn("Test Type</span><span class='meta-value'>TEXT", html)
        self.assertNotIn("Target Node ID", html)

    def test_html_has_no_external_dependencies(self) -> None:
        html = FirmwareReportBuilder().build_html(self._report())
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("http://", html.lower())
        self.assertNotIn("https://", html.lower())
        self.assertNotIn("<link", html.lower())


if __name__ == "__main__":
    unittest.main()
