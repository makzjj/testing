"""Filesystem export and folder persistence for Firmware Integration reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Callable

from PyQt6.QtCore import QSettings, QStandardPaths

from gui.workspace.models import FirmwareFitReport


SETTINGS_ORGANIZATION = "Biobot"
SETTINGS_APPLICATION = "RobotArmTester"
REPORT_SAVE_LOCATION_KEY = "report_save_location"


@dataclass(frozen=True)
class FirmwareReportExportResult:
    success: bool
    path: Path | None = None
    message: str | None = None
    error: str | None = None


class FirmwareReportExportService:
    """Persist report export folder state and write pre-rendered HTML files."""

    def __init__(
        self,
        *,
        settings: QSettings | None = None,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
        self._wall_clock = wall_clock or datetime.now

    def last_export_directory(self) -> Path:
        saved = str(self._settings.value(REPORT_SAVE_LOCATION_KEY, "") or "").strip()
        if saved:
            candidate = Path(saved).expanduser()
            if candidate.exists() and candidate.is_dir():
                return candidate
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if documents:
            return Path(documents)
        return Path.cwd()

    def set_last_export_directory(self, path: str | Path) -> None:
        self._settings.setValue(REPORT_SAVE_LOCATION_KEY, str(Path(path)))

    def suggest_filename(self, report: FirmwareFitReport, wall_clock_time: datetime | None = None) -> str:
        stamp = (wall_clock_time or self._wall_clock()).strftime("%Y%m%d_%H%M%S")
        mode = self._sanitize_part(report.mode or "fit").lower()
        parts = ["FIT", mode]
        if report.target_node_id is not None:
            parts.append(f"node{int(report.target_node_id)}")
        parts.append(stamp)
        return "_".join(parts) + ".html"

    def resolve_available_path(self, directory: str | Path, filename: str) -> Path:
        base_directory = Path(directory)
        safe_name = self._sanitize_filename(filename)
        candidate = base_directory / safe_name
        if not candidate.exists():
            return candidate
        stem = candidate.stem
        suffix = candidate.suffix
        index = 1
        while True:
            next_candidate = base_directory / f"{stem}_{index}{suffix}"
            if not next_candidate.exists():
                return next_candidate
            index += 1

    def export_html(self, html: str, directory_or_path: str | Path, filename: str | None = None) -> FirmwareReportExportResult:
        try:
            target = Path(directory_or_path)
            if filename is not None or target.suffix.lower() != ".html":
                target = self.resolve_available_path(target, filename or "FIT_report.html")
            else:
                target = self.resolve_available_path(target.parent, target.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(html), encoding="utf-8")
            self.set_last_export_directory(target.parent)
            return FirmwareReportExportResult(
                success=True,
                path=target,
                message=f"Exported report to {target}",
            )
        except Exception as exc:
            return FirmwareReportExportResult(success=False, path=None, message="Failed to export report.", error=str(exc))

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        name = Path(str(value)).name.strip() or "FIT_report.html"
        stem = FirmwareReportExportService._sanitize_part(Path(name).stem) or "FIT_report"
        suffix = Path(name).suffix.lower()
        if suffix != ".html":
            suffix = ".html"
        return stem + suffix

    @staticmethod
    def _sanitize_part(value: object) -> str:
        sanitized = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip())
        return sanitized.strip("-_") or "fit"
