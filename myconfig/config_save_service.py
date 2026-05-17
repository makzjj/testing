"""Version-aware save planning and safe YAML persistence helpers."""

from __future__ import annotations

import copy
import logging
import os
import re
from pathlib import Path

import yaml

from myconfig.config_models import ConfigDocument, SavePlan, SaveResult
from myconfig.config_schema_adapter import ConfigSchemaAdapter
from myconfig.version_utils import is_valid_version_text
from myconfig.yaml_repair_service import YamlRepairService


logger = logging.getLogger("myconfig.config_save_service")

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')
_SUPPORTED_CONFIG_SUFFIXES = {".yaml", ".yml"}
class _ConfigYamlDumper(yaml.SafeDumper):
    """YAML dumper that preserves blank config values as empty scalars."""


class _ExplicitNullValue:
    """Sentinel used to preserve explicit `null` tokens for selected YAML paths."""


def _represent_empty_null(_dumper: yaml.SafeDumper, _value) -> yaml.nodes.ScalarNode:
    """Render `None` values as blank YAML scalars instead of explicit `null`."""
    return _dumper.represent_scalar("tag:yaml.org,2002:null", "")


_ConfigYamlDumper.add_representer(type(None), _represent_empty_null)


def _represent_explicit_null(_dumper: yaml.SafeDumper, _value: _ExplicitNullValue) -> yaml.nodes.ScalarNode:
    """Render selected null values as the explicit `null` token."""
    return _dumper.represent_scalar("tag:yaml.org,2002:null", "null")


_ConfigYamlDumper.add_representer(_ExplicitNullValue, _represent_explicit_null)


class ConfigSaveService:
    """Plans and persists safe versioned YAML saves for Project Config edits."""

    def __init__(
        self,
        adapter: ConfigSchemaAdapter | None = None,
        repair_service: YamlRepairService | None = None,
    ) -> None:
        self._adapter = adapter or ConfigSchemaAdapter()
        self._repair_service = repair_service or YamlRepairService()

    def prepare_save(
        self,
        document: ConfigDocument,
        current_version: str | None,
        requested_version: str | None,
        confirmed_new_version: bool,
    ) -> SavePlan:
        """Build the explicit save plan and enforce version-change rules."""
        # 1. Normalize the current and requested version values
        original_version = self._clean_optional_string(current_version)
        edited_version = self._clean_optional_string(document.version)
        target_version = self._clean_optional_string(requested_version) or edited_version or original_version
        # 2. Require an explicit new version before saving when the version was unchanged
        if original_version and target_version == original_version and not confirmed_new_version:
            target_path = self._build_target_path(document, original_version)
            return SavePlan(
                target_version=original_version,
                target_path=target_path,
                requires_confirmation=True,
                warning_text=f"Enter a new config version before saving. Current config version: {original_version}",
            )
        # 3. Block any save that still does not provide a new version
        if not target_version:
            raise ValueError("A new config version is required before saving")
        if original_version and target_version == original_version:
            raise ValueError("Saving requires a new config version that differs from the current config version")
        self._validate_config_version_format(target_version)
        # 4. Build and validate the versioned output path
        target_path = self._build_target_path(document, target_version)
        self._ensure_target_config_version_available(target_path, document.project_name, target_version)
        # 5. Return the confirmed save plan
        logger.info("Prepared config save plan, path=%s version=%s", target_path, target_version)
        return SavePlan(
            target_version=target_version,
            target_path=target_path,
            requires_confirmation=False,
            warning_text=f"Save config as {target_path.name}",
        )

    def save_document(self, document: ConfigDocument, save_plan: SavePlan) -> SaveResult:
        """Persist one edited config document using the prepared save plan."""
        # 1. Reject incomplete save plans
        if save_plan.requires_confirmation:
            raise ValueError("Cannot save a config document while a new version is still required")
        # 2. Apply the target version to the YAML-backed document
        raw_data = copy.deepcopy(document.raw_data)
        self._adapter.set_version(raw_data, save_plan.target_version)
        styled_raw_data = self._apply_null_style_hints(raw_data, document.explicit_null_paths)
        # 3. Write the YAML through a staged temp-file replacement
        self._write_yaml_atomically(save_plan.target_path, styled_raw_data)
        # 4. Return the successful save result
        logger.info("Saved config document, path=%s version=%s", save_plan.target_path, save_plan.target_version)
        return SaveResult(
            saved_path=save_plan.target_path,
            saved_version=save_plan.target_version,
            message=f"Saved project config to {save_plan.target_path.name}",
        )

    def _build_target_path(self, document: ConfigDocument, version: str) -> Path:
        logger.debug("Building target save path, project=%s version=%s", document.project_name, version)
        project_name = self._sanitize_filename_fragment(document.project_name)
        version_fragment = self._sanitize_filename_fragment(version)
        file_name = f"{project_name}_{version_fragment}.yaml"
        return document.source_path.resolve().parent / file_name

    def _ensure_target_config_version_available(
        self,
        target_path: Path,
        project_name: str,
        target_version: str,
    ) -> None:
        logger.debug("Checking config version availability, target=%s version=%s", target_path, target_version)
        config_directory = self._resolve_project_config_directory(target_path)
        existing_target = self._find_existing_config_identity(
            config_directory,
            project_name=project_name,
            target_version=target_version,
            target_stem=target_path.stem,
        )
        if existing_target is not None:
            raise FileExistsError(
                f"Config version {target_version} already exists for {project_name}: "
                f"{existing_target.name}. Choose a different config version before saving."
            )

    def _write_yaml_atomically(self, target_path: Path, raw_data: dict) -> None:
        logger.debug("Writing YAML atomically, path=%s", target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_suffix(f"{target_path.suffix}.tmp")
        try:
            yaml_text = yaml.dump(
                raw_data,
                Dumper=_ConfigYamlDumper,
                sort_keys=False,
                default_flow_style=False,
                allow_unicode=False,
            )
            temp_path.write_text(yaml_text, encoding="utf-8", newline="\n")
            os.replace(temp_path, target_path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def _sanitize_filename_fragment(self, value: str) -> str:
        cleaned_value = _INVALID_FILENAME_CHARS.sub("_", value.strip())
        cleaned_value = cleaned_value.replace(" ", "_")
        return cleaned_value or "config"

    def _resolve_project_config_directory(self, target_path: Path) -> Path:
        """Resolve the project config root so version uniqueness covers the whole config directory."""
        resolved_path = target_path.resolve()
        for candidate in (resolved_path.parent, *resolved_path.parents):
            if candidate.name.casefold() == "project_configs":
                return candidate
        return resolved_path.parent

    def _find_existing_config_identity(
        self,
        config_directory: Path,
        project_name: str,
        target_version: str,
        target_stem: str,
    ) -> Path | None:
        """Find an existing config file with the same YAML-backed config identity anywhere under the config directory."""
        normalized_project_name = project_name.strip().casefold()
        normalized_version = target_version.strip()
        normalized_stem = target_stem.casefold()
        fallback_match: Path | None = None

        for candidate in config_directory.rglob("*"):
            if not candidate.is_file():
                continue
            if candidate.suffix.lower() not in _SUPPORTED_CONFIG_SUFFIXES:
                continue

            candidate_identity = self._read_candidate_config_identity(candidate)
            if candidate_identity is not None:
                candidate_project_name, candidate_version = candidate_identity
                if candidate_project_name.casefold() == normalized_project_name and candidate_version == normalized_version:
                    return candidate.resolve()
                continue

            if candidate.stem.casefold() == normalized_stem and fallback_match is None:
                fallback_match = candidate.resolve()

        return fallback_match

    def _clean_optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        cleaned_value = str(value).strip()
        return cleaned_value or None

    def _validate_config_version_format(self, version: str) -> None:
        if is_valid_version_text(version):
            return
        raise ValueError(
            "Config version must use digits separated by dots, for example 1, 1.2, 1.2.3, or 0.0.0.1"
        )

    def _read_candidate_config_identity(self, candidate_path: Path) -> tuple[str, str] | None:
        """Read one candidate file's internal config identity without modifying it on disk."""
        try:
            diagnostic = self._repair_service.diagnose(candidate_path)
            if not diagnostic.is_valid and diagnostic.repaired_text is None:
                return None

            source_text = (
                diagnostic.repaired_text
                if diagnostic.was_repaired and diagnostic.repaired_text is not None
                else candidate_path.read_text(encoding="utf-8")
            )
            raw_data = yaml.safe_load(source_text) or {}
            if not isinstance(raw_data, dict):
                return None

            candidate_project_name = self._adapter.extract_project_name(raw_data)
            candidate_version = self._adapter.extract_version(raw_data)
            if candidate_project_name == "unnamed_project" or not candidate_version:
                return None
            return candidate_project_name, candidate_version
        except Exception:
            return None

    def _apply_null_style_hints(
        self,
        raw_data: object,
        explicit_null_paths: set[tuple[str | int, ...]],
        path: tuple[str | int, ...] = (),
    ) -> object:
        if isinstance(raw_data, dict):
            return {
                key: self._apply_null_style_hints(value, explicit_null_paths, path + (key,))
                for key, value in raw_data.items()
            }
        if isinstance(raw_data, list):
            return [
                self._apply_null_style_hints(value, explicit_null_paths, path + (index,))
                for index, value in enumerate(raw_data)
            ]
        if raw_data is None and path in explicit_null_paths:
            return _ExplicitNullValue()
        return raw_data
