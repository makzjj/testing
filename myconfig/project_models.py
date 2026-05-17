"""Typed project configuration models for the selector and future workspace shell."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ProjectFeatures:
    """Feature toggles loaded from project configuration."""

    firmware_tools: bool = False
    mechanical_tools: bool = False
    application_tools: bool = False
    stress_test: bool = False
    integration_test: bool = False


@dataclass(frozen=True)
class ProjectUiConfig:
    """UI-related metadata loaded from project configuration."""

    workspace: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class ProjectDefinition:
    """One parsed and validated project definition."""

    name: str
    display_name: str
    config_path: Path
    config_version: str | None = None
    system_axes: int | None = None
    features: ProjectFeatures = field(default_factory=ProjectFeatures)
    ui: ProjectUiConfig = field(default_factory=ProjectUiConfig)


@dataclass(frozen=True)
class ValidationIssue:
    """One validation issue found while loading a project config."""

    path: Path
    severity: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class ProjectLoadResult:
    """Result of loading all project configs from the config directory."""

    valid_projects: list[ProjectDefinition]
    invalid_projects: list[ValidationIssue]
