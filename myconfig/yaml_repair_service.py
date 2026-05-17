"""Explicit malformed-YAML diagnostic and conservative repair helpers."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from myconfig.config_models import YamlRepairDiagnostic


logger = logging.getLogger("myconfig.yaml_repair_service")

_LEADING_TABS_PATTERN = re.compile(r"^(?P<indent>\t+)", re.MULTILINE)


class YamlRepairService:
    """Diagnose malformed YAML and apply conservative syntax-only repairs when safe."""

    def diagnose(self, path: Path) -> YamlRepairDiagnostic:
        """Inspect one YAML file before the main config flow continues."""
        # 1. Read the current file text
        source_text = self._read_source_text(path)
        # 2. Accept the file immediately when parsing already succeeds
        parse_error = self._find_parse_error(source_text)
        if parse_error is None:
            logger.info("YAML diagnostic passed without repair, path=%s", path)
            return YamlRepairDiagnostic(
                is_valid=True,
                was_repaired=False,
                message="YAML syntax is valid",
            )
        # 3. Attempt a conservative syntax-only repair pass
        repaired_text = self._attempt_conservative_repair(source_text)
        if repaired_text != source_text and self._find_parse_error(repaired_text) is None:
            logger.warning("YAML syntax repair is available, path=%s", path)
            return YamlRepairDiagnostic(
                is_valid=True,
                was_repaired=True,
                message=f"Recovered YAML syntax issue: {parse_error}",
                repaired_text=repaired_text,
            )
        # 4. Return a blocking diagnostic when safe repair is not possible
        logger.warning("YAML diagnostic failed without safe repair, path=%s error=%s", path, parse_error)
        return YamlRepairDiagnostic(
            is_valid=False,
            was_repaired=False,
            message=f"YAML syntax error: {parse_error}",
        )

    def repair_if_needed(self, path: Path) -> YamlRepairDiagnostic:
        """Persist a conservative repair before continuing with config loading."""
        # 1. Diagnose the current YAML file
        diagnostic = self.diagnose(path)
        # 2. Persist the repaired text when a safe repair is available
        if diagnostic.was_repaired and diagnostic.repaired_text is not None:
            self._persist_repaired_text(path, diagnostic.repaired_text)
        # 3. Return the final diagnostic outcome
        return diagnostic

    def _read_source_text(self, path: Path) -> str:
        logger.debug("Reading YAML source text, path=%s", path)
        return path.read_text(encoding="utf-8")

    def _find_parse_error(self, text: str) -> str | None:
        logger.debug("Attempting YAML parse during diagnostic")
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            logger.debug("YAML parse failed during diagnostic, error=%s", exc)
            return str(exc)
        return None

    def _attempt_conservative_repair(self, text: str) -> str:
        logger.debug("Running conservative YAML repair transforms")
        repaired = text.replace("\r\n", "\n").replace("\ufeff", "").replace("\x00", "")
        repaired = _LEADING_TABS_PATTERN.sub(lambda match: "  " * len(match.group("indent")), repaired)
        repaired = repaired.replace(":\t", ": ")
        if repaired and not repaired.endswith("\n"):
            repaired += "\n"
        return repaired

    def _persist_repaired_text(self, path: Path, repaired_text: str) -> None:
        logger.info("Persisting repaired YAML text, path=%s", path)
        path.write_text(repaired_text, encoding="utf-8")
