"""Pure HTML report rendering for Firmware Integration Test runs."""

from __future__ import annotations

from html import escape

from gui.workspace.models import FirmwareFitReport, FirmwareTestResult


_FAILURE_STATUSES = {"FAIL", "FAILED", "TIMEOUT", "ERROR", "UNSUPPORTED"}


def derive_fit_overall_status(results: tuple[FirmwareTestResult, ...], *, cancelled: bool = False) -> str:
    """Return the shared run-level status for a completed FIT result set."""

    if cancelled or any(str(result.status).upper() == "CANCELLED" for result in results):
        return "CANCELLED"
    if not results:
        return "FAILED"
    if any(str(result.status).upper() in _FAILURE_STATUSES for result in results):
        return "FAILED"
    return "PASSED"


class FirmwareReportBuilder:
    """Render one in-memory HTML report from immutable FIT report data."""

    def build_html(self, report: FirmwareFitReport) -> str:
        rows = "\n".join(self._render_result_row(result) for result in report.results)
        passed = report.passed_count
        total = len(report.results)
        pass_percent = (passed / total * 100.0) if total else 0.0
        summary_class = "pass" if total and passed == total else "fail"
        timestamp = report.completed_at or report.started_at or "N/A"
        mode_label = self._mode_label(report.mode).replace(" FIT", "").upper()

        return "\n".join(
            [
                "<!DOCTYPE html>",
                "<html>",
                "<head>",
                "<style>",
                "body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; background-color: #f4f7f6; }",
                ".container { max-width: 1100px; margin: auto; background: #fff; padding: 40px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.05); border-top: 4px solid #f47c20; }",
                ".header { display: flex; justify-content: space-between; align-items: center; border-bottom: 2px solid #eee; padding-bottom: 20px; margin-bottom: 30px; }",
                "h1 { color: #2c3e50; margin: 0; font-size: 24px; }",
                ".meta-info { display: flex; gap: 30px; font-size: 14px; color: #555; flex-wrap: wrap; }",
                ".meta-item { display: flex; flex-direction: column; }",
                ".meta-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #888; font-weight: bold; margin-bottom: 4px; }",
                ".meta-value { font-size: 15px; font-weight: 500; color: #333; }",
                ".summary { font-size: 18px; font-weight: bold; margin-bottom: 30px; padding: 20px; border-radius: 8px; display: flex; align-items: center; justify-content: space-between; }",
                ".summary.pass { background-color: #eafaf1; color: #27ae60; border: 1px solid #d5f5e3; }",
                ".summary.fail { background-color: #fff3e8; color: #c25f00; border: 1px solid #f47c20; }",
                "table { width: 100%; border-collapse: collapse; font-size: 14px; }",
                "th, td { padding: 15px 15px; text-align: left; border-bottom: 1px solid #eee; vertical-align: top; }",
                "th { background-color: #f47c20; font-weight: 600; color: #fff; text-transform: uppercase; font-size: 12px; letter-spacing: 0.5px; }",
                "tr:hover { background-color: #fcfcfc; }",
                ".badge { padding: 5px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; color: #fff; text-transform: uppercase; letter-spacing: 0.5px; }",
                ".badge.pass { background-color: #2ecc71; }",
                ".badge.fail { background-color: #e74c3c; }",
                ".badge.timeout { background-color: #f39c12; }",
                ".details { font-family: 'Consolas', 'Courier New', monospace; font-size: 12px; color: #7f8c8d; display: block; margin-top: 8px; background: #f8f9fa; padding: 8px; border-radius: 4px; }",
                "</style>",
                "</head>",
                "<body>",
                "    <div class='container'>",
                "        <div class='header'>",
                "            <h1>BioBot Firmware Integration Test Report</h1>",
                "            <div class='meta-info'>",
                f"                <div class='meta-item'><span class='meta-label'>Timestamp</span><span class='meta-value'>{self._text(timestamp)}</span></div>",
                f"                <div class='meta-item'><span class='meta-label'>Test Type</span><span class='meta-value'>{self._text(mode_label)}</span></div>",
                (
                    f"                <div class='meta-item'><span class='meta-label'>Target Node ID</span><span class='meta-value'>{self._text(report.target_node_id)}</span></div>"
                    if report.mode == "binary"
                    else ""
                ),
                "            </div>",
                "        </div>",
                f"        <div class='summary {summary_class}'>",
                f"            <span>Overall Result: {passed} / {total} Passed</span>",
                f"            <span>{pass_percent:.1f}%</span>",
                "        </div>",
                "        <table>",
                "            <thead>",
                "                <tr>",
                "                    <th width='30%'>Command Name</th>",
                "                    <th width='10%'>Status</th>",
                "                    <th width='15%'>Expected</th>",
                "                    <th width='35%'>Actual Response</th>",
                "                    <th width='10%'>Latency</th>",
                "                </tr>",
                "            </thead>",
                f"            <tbody>{rows}</tbody>",
                "        </table>",
                "    </div>",
                "</body>",
                "</html>",
            ]
        )

    def _render_result_row(self, result: FirmwareTestResult) -> str:
        status = str(result.status or "UNKNOWN")
        badge_class = status.lower().split()[0]
        if badge_class not in {"pass", "fail", "timeout"}:
            badge_class = "fail"
        details = f"TX: {self._format_bytes(result.tx_bytes)}<br>RX: {self._format_bytes(result.rx_bytes)}"
        actual_parts = [str(result.actual or result.message or "N/A")]
        if result.manual_verification_outcome:
            actual_parts.append(f"Manual: {result.manual_verification_outcome}")
        if result.message and result.actual:
            actual_parts.append(str(result.message))
        actual = "<br>".join(self._text(part) for part in actual_parts)
        return "\n".join(
            [
                "                <tr>",
                f"                    <td>{self._text(result.case_name or result.command_display or result.case_id)}</td>",
                f"                    <td><span class='badge {badge_class}'>{self._text(status)}</span></td>",
                f"                    <td>{self._text(result.expected)}</td>",
                f"                    <td>{actual}<span class='details'>{details}</span></td>",
                f"                    <td>{self._text(self._format_latency(result.latency_ms))}</td>",
                "                </tr>",
            ]
        )

    @staticmethod
    def _mode_label(mode: str | None) -> str:
        normalized = str(mode or "FIT").strip().lower()
        if normalized == "binary":
            return "Binary FIT"
        if normalized == "text":
            return "Text FIT"
        return "Firmware Integration Test"

    @staticmethod
    def _format_bytes(value: bytes | None) -> str:
        if not value:
            return "N/A"
        return " ".join(f"{byte:02X}" for byte in bytes(value))

    @staticmethod
    def _format_duration(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{float(value):.1f} ms"

    @staticmethod
    def _format_latency(value: float | None) -> str:
        if value is None:
            return "N/A"
        return f"{float(value):.1f} ms"

    @staticmethod
    def _format_node(value: int | None) -> str:
        if value is None:
            return "N/A"
        return f"Node {int(value):02d}"

    @staticmethod
    def _text(value: object | None) -> str:
        if value is None or value == "":
            return "N/A"
        return escape(str(value), quote=True)
