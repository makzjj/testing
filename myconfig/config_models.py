"""Typed models for YAML-driven config loading, editing, and saving."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeAlias


PathSegment: TypeAlias = str | int


@dataclass(frozen=True)
class ConfigValidationIssue:
    """One validation issue found while preparing or saving a config document."""

    path: tuple[PathSegment, ...]
    severity: str
    message: str


@dataclass(frozen=True)
class YamlRepairDiagnostic:
    """Outcome of the explicit YAML syntax diagnostic/repair step."""

    is_valid: bool
    was_repaired: bool
    message: str
    repaired_text: str | None = None


@dataclass
class LiveHardwareFieldValue:
    """One read-only live hardware mismatch overlay for a YAML-backed field."""

    path: tuple[PathSegment, ...]
    label: str
    yaml_value: object
    live_value: object
    display_text: str
    highlight_tone: str = "warning"


@dataclass
class ConfigFieldModel:
    """Recursive field model used to render editable YAML content."""

    path: tuple[PathSegment, ...]
    label: str
    value: object
    value_type: str
    editable: bool
    children: list["ConfigFieldModel"] = field(default_factory=list)
    live_overlay: LiveHardwareFieldValue | None = None


@dataclass
class ConfigSectionModel:
    """One top-level YAML section prepared for the Project Config page."""

    section_key: str
    title: str
    raw_value_type: str
    preserve_empty_as_null: bool = False
    fields: list[ConfigFieldModel] = field(default_factory=list)


@dataclass
class ConfigDocument:
    """Canonical in-memory representation of one loaded project YAML file."""

    raw_data: dict
    source_path: Path
    project_name: str
    version: str | None
    explicit_null_paths: set[tuple[PathSegment, ...]] = field(default_factory=set)


@dataclass
class ConfigEditorModel:
    """Bridge-friendly editor model for the Project Config page."""

    sections: list[ConfigSectionModel]
    source_path: Path
    project_name: str
    version: str | None
    validation_issues: list[ConfigValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class SavePlan:
    """Explicit save plan returned before a config write occurs."""

    target_version: str
    target_path: Path
    requires_confirmation: bool
    warning_text: str


@dataclass(frozen=True)
class SaveResult:
    """Outcome returned after a config file is written successfully."""

    saved_path: Path
    saved_version: str
    message: str
