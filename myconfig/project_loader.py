"""Shared project discovery, YAML parsing, and validation logic."""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path

import yaml

from myconfig.config_schema_adapter import ConfigSchemaAdapter
from myconfig.project_models import (
    ProjectDefinition,
    ProjectLoadResult,
    ValidationIssue,
)
from myconfig.yaml_repair_service import YamlRepairService


logger = logging.getLogger("myconfig.project_loader")

PROJECT_CONFIG_DIR = Path(__file__).resolve().parents[1] / "project_configs"
SUPPORTED_PROJECT_SUFFIXES = (".yaml", ".yml")
_YAML_REPAIR_SERVICE = YamlRepairService()
_SCHEMA_ADAPTER = ConfigSchemaAdapter()


def ensure_project_config_dir() -> Path:
    """Ensure the project config directory exists before discovery begins."""
    logger.debug("Ensuring project config directory exists, path=%s", PROJECT_CONFIG_DIR)
    PROJECT_CONFIG_DIR.mkdir(exist_ok=True)
    return PROJECT_CONFIG_DIR


def discover_project_files() -> list[Path]:
    """Discover YAML project files from the project config directory."""
    # 1. Ensure the config directory exists
    config_dir = ensure_project_config_dir()
    # 2. Collect candidate YAML files in a stable order
    project_files = [
        config_path.resolve()
        for config_path in sorted(config_dir.iterdir())
        if config_path.is_file() and config_path.suffix.lower() in SUPPORTED_PROJECT_SUFFIXES
    ]
    logger.info("Discovered %d project config file(s)", len(project_files))
    return project_files


def load_available_projects() -> ProjectLoadResult:
    """Load, parse, and validate all available project configs."""
    # 1. Discover candidate YAML files
    project_files = discover_project_files()
    # 2. Parse and validate each config file
    valid_projects, invalid_projects = _load_projects_from_files(project_files)
    valid_projects = _disambiguate_duplicate_display_names(valid_projects)
    logger.info(
        "Loaded project configs, valid=%d invalid=%d",
        len(valid_projects),
        len(invalid_projects),
    )
    return ProjectLoadResult(valid_projects=valid_projects, invalid_projects=invalid_projects)


def discover_projects() -> list[ProjectDefinition]:
    """Return only valid project definitions for selector compatibility."""
    return load_available_projects().valid_projects


def load_project_yaml(path: Path) -> dict:
    """Load one raw YAML project configuration."""
    logger.debug("Loading project YAML, path=%s", path)
    diagnostic = _YAML_REPAIR_SERVICE.repair_if_needed(path)
    if not diagnostic.is_valid:
        raise ValueError(diagnostic.message)
    with path.open("r", encoding="utf-8") as file_handle:
        raw_data = yaml.safe_load(file_handle) or {}
    if not isinstance(raw_data, dict):
        raise ValueError("Top-level YAML content must be a mapping")
    logger.debug("Loaded raw project YAML successfully, path=%s", path)
    return raw_data


def validate_project_yaml(raw: dict, path: Path) -> list[ValidationIssue]:
    """Validate the minimal YAML schema for one project config."""
    issues: list[ValidationIssue] = []

    # 1. Validate the project section
    project_section = raw.get("project")
    if not isinstance(project_section, dict):
        issues.append(_build_issue(path, "Missing or invalid 'project' section", "project"))
        return issues

    # 2. Validate the required project name
    project_name = project_section.get("name")
    if not isinstance(project_name, str) or not project_name.strip():
        issues.append(_build_issue(path, "Missing required project.name", "project.name"))

    # 3. Validate schema-specific integer fields when present
    issues.extend(_validate_optional_integer_field(raw, path, ("system", "axes"), "system.axes"))
    issues.extend(
        _validate_optional_integer_field(
            raw,
            path,
            ("robot system configuration", "axes number"),
            "robot system configuration.axes number",
        )
    )

    return issues


def build_project_definition(raw: dict, path: Path) -> ProjectDefinition:
    """Build a typed project definition from validated raw YAML data."""
    return _SCHEMA_ADAPTER.build_project_identity(raw, path)


def _load_projects_from_files(project_files: list[Path]) -> tuple[list[ProjectDefinition], list[ValidationIssue]]:
    """Load project definitions from candidate config files."""
    valid_projects: list[ProjectDefinition] = []
    invalid_projects: list[ValidationIssue] = []

    for config_path in project_files:
        # 1. Parse one YAML file
        raw_or_issue = _load_raw_yaml_or_issue(config_path)
        if isinstance(raw_or_issue, ValidationIssue):
            invalid_projects.append(raw_or_issue)
            continue

        # 2. Validate the parsed YAML structure
        validation_issues = validate_project_yaml(raw_or_issue, config_path)
        if validation_issues:
            invalid_projects.extend(validation_issues)
            logger.warning("Project config validation failed, path=%s issues=%d", config_path, len(validation_issues))
            continue

        # 3. Build a typed project definition
        valid_projects.append(build_project_definition(raw_or_issue, config_path))

    return valid_projects, invalid_projects


def _disambiguate_duplicate_display_names(projects: list[ProjectDefinition]) -> list[ProjectDefinition]:
    """Append config-version context when multiple configs would show the same display name."""
    grouped_projects: dict[str, list[ProjectDefinition]] = {}
    for project in projects:
        grouped_projects.setdefault(project.display_name.casefold(), []).append(project)

    adjusted_projects: list[ProjectDefinition] = []
    for project in projects:
        duplicates = grouped_projects.get(project.display_name.casefold(), [])
        if len(duplicates) < 2:
            adjusted_projects.append(project)
            continue

        version_text = project.config_version or "unversioned"
        disambiguated_name = f"{project.display_name} ({version_text})"
        matching_versions = [
            candidate for candidate in duplicates if (candidate.config_version or "unversioned") == version_text
        ]
        if len(matching_versions) > 1:
            disambiguated_name = f"{disambiguated_name} - {project.config_path.stem}"

        adjusted_projects.append(replace(project, display_name=disambiguated_name))

    return adjusted_projects


def _load_raw_yaml_or_issue(path: Path) -> dict | ValidationIssue:
    """Parse one YAML file or convert the failure into a validation issue."""
    try:
        return load_project_yaml(path)
    except Exception as exc:
        logger.warning("Failed to load project YAML, path=%s error=%s", path, exc)
        return _build_issue(path, f"Failed to parse YAML: {exc}", None)


def _validate_optional_integer_field(
    raw: dict,
    path: Path,
    key_path: tuple[str, ...],
    field_name: str,
) -> list[ValidationIssue]:
    """Validate one optional integer field from either schema shape."""
    value = _SCHEMA_ADAPTER.lookup_path(raw, key_path, default=None)
    if value is None:
        return []
    if isinstance(value, int):
        return []
    return [_build_issue(path, f"{field_name} must be an integer", field_name)]


def _build_issue(path: Path, message: str, field_name: str | None) -> ValidationIssue:
    """Build one validation issue object."""
    return ValidationIssue(path=path.resolve(), severity="error", message=message, field=field_name)
