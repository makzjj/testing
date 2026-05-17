"""Schema helpers that bridge ACCuESS YAML and legacy project config shapes."""

from __future__ import annotations

import logging
from pathlib import Path

from myconfig.config_models import ConfigFieldModel, ConfigSectionModel
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig


logger = logging.getLogger("myconfig.config_schema_adapter")

_KNOWN_LIST_SECTIONS = {
    "command list",
}

_AXIS_FIRMWARE_VERSION_FIELD = "fw_version"
_CODE_STYLE_FIELDS = {
    "node_config",
}

_PREFERRED_SECTION_ORDER = [
    "project",
    "features",
    "ui",
    "robot system configuration",
    "communication configuration",
    "serial_port",
    "mcu configuration",
    "robot arm configuration",
    "command list",
    "geometry",
    "calibration",
    "system",
    "mcu",
    "robot",
]


class ConfigSchemaAdapter:
    """Centralizes project-schema knowledge for loader, bridge, and UI flows."""

    def build_project_identity(self, raw: dict, path: Path) -> ProjectDefinition:
        """Build selector/workspace metadata from the richest known schema."""
        # 1. Extract core project identity
        project_name = self.extract_project_name(raw)
        display_name = self.extract_display_name(raw)
        config_version = self.extract_version(raw)
        # 2. Extract shared metadata used across the selector and shell
        system_axes = self.extract_axes_count(raw)
        features = self.extract_features(raw)
        ui_config = self.extract_ui_config(raw)
        # 3. Return the typed project definition
        logger.debug("Built project identity, name=%s path=%s", project_name, path)
        return ProjectDefinition(
            name=project_name,
            display_name=display_name,
            config_path=path.resolve(),
            config_version=config_version,
            system_axes=system_axes,
            features=features,
            ui=ui_config,
        )

    def build_editor_sections(self, raw: dict) -> list[ConfigSectionModel]:
        """Build ordered top-level section models for the Project Config page."""
        # 1. Compute a stable top-level section order
        ordered_keys = self._build_ordered_section_keys(raw)
        # 2. Convert every top-level YAML property into a recursive section model
        sections = [self._build_section_model(section_key, raw.get(section_key)) for section_key in ordered_keys]
        # 3. Return the prepared editor sections
        logger.debug("Built %d editor section(s)", len(sections))
        return sections

    def extract_project_name(self, raw: dict) -> str:
        """Resolve the canonical project name with safe fallbacks."""
        project_section = raw.get("project")
        if isinstance(project_section, dict):
            name_value = project_section.get("name")
            if isinstance(name_value, str) and name_value.strip():
                return name_value.strip()
        return "unnamed_project"

    def extract_display_name(self, raw: dict) -> str:
        """Resolve the user-facing project display name."""
        project_section = raw.get("project")
        if isinstance(project_section, dict):
            display_name = project_section.get("display_name")
            if isinstance(display_name, str) and display_name.strip():
                return display_name.strip()
        return self.extract_project_name(raw)

    def extract_version(self, raw: dict) -> str | None:
        """Resolve the current project config version from the supported schemas."""
        version_value = self.lookup_first(
            raw,
            [
                ("project", "config_version"),
                ("project", "version"),
            ],
        )
        if version_value is None:
            return None
        cleaned_value = str(version_value).strip()
        return cleaned_value or None

    def set_version(self, raw: dict, version: str) -> None:
        """Update the YAML-backed project version field in place."""
        project_section = raw.setdefault("project", {})
        if not isinstance(project_section, dict):
            project_section = {}
            raw["project"] = project_section
        project_section["config_version"] = version

    def extract_features(self, raw: dict) -> ProjectFeatures:
        """Resolve the current feature flags from the YAML source of truth."""
        features_section = raw.get("features")
        if not isinstance(features_section, dict):
            features_section = {}
        return ProjectFeatures(
            firmware_tools=bool(features_section.get("firmware_tools")),
            mechanical_tools=bool(features_section.get("mechanical_tools")),
            application_tools=bool(features_section.get("application_tools")),
            stress_test=bool(features_section.get("stress_test")),
            integration_test=bool(features_section.get("integration_test")),
        )

    def extract_ui_config(self, raw: dict) -> ProjectUiConfig:
        """Resolve current UI metadata from the YAML file."""
        ui_section = raw.get("ui")
        if not isinstance(ui_section, dict):
            ui_section = {}
        workspace = self._clean_optional_string(ui_section.get("workspace"))
        notes = self._clean_optional_string(ui_section.get("notes"))
        return ProjectUiConfig(workspace=workspace, notes=notes)

    def extract_axes_count(self, raw: dict) -> int | None:
        """Resolve the configured axis count from new or legacy schema paths."""
        axis_count = self.lookup_first(
            raw,
            [
                ("robot system configuration", "axes number"),
                ("system", "axes"),
                ("robot", "axis_count"),
            ],
        )
        if isinstance(axis_count, int):
            return axis_count
        if axis_count is not None:
            try:
                return int(axis_count)
            except (TypeError, ValueError):
                logger.warning("Failed to coerce axis count, value=%s", axis_count)
        axes_section = self.extract_axis_section(raw)
        return len(axes_section) if axes_section else None

    def extract_axis_section(self, raw: dict) -> dict[str, dict]:
        """Resolve the configured axis mapping from new or legacy schema paths."""
        axes = self.lookup_first(
            raw,
            [
                ("robot arm configuration", "axes"),
                ("robot", "axes"),
            ],
            default={},
        )
        return axes if isinstance(axes, dict) else {}

    def extract_sensor_section(self, raw: dict) -> dict[str, dict]:
        """Resolve configured sensor/encoder nodes from new or legacy schema paths."""
        sensors = self.lookup_first(
            raw,
            [
                ("robot arm configuration", "sensors"),
                ("robot", "encoders"),
            ],
            default={},
        )
        return sensors if isinstance(sensors, dict) else {}

    def extract_serial_port_name(self, raw: dict) -> str | None:
        """Resolve the configured serial port name from supported schema variants."""
        value = self.lookup_first(
            raw,
            [
                ("communication configuration", "serial_port", "name"),
                ("serial_port", "name"),
                ("mcu", "serial_port", "name"),
            ],
        )
        return self._clean_optional_string(value)

    def extract_serial_baudrate(self, raw: dict) -> str | None:
        """Resolve the configured baudrate from supported schema variants."""
        value = self.lookup_first(
            raw,
            [
                ("communication configuration", "serial_port", "baudrate"),
                ("serial_port", "baudrate"),
                ("mcu", "serial_port", "baudrate"),
            ],
        )
        return self._clean_optional_string(value)

    def lookup_first(self, raw: dict, key_paths: list[tuple[str, ...]], default=None):
        """Try multiple schema paths and return the first value that exists."""
        for key_path in key_paths:
            value = self.lookup_path(raw, key_path, default=None)
            if value is not None:
                return value
        return default

    def lookup_path(self, raw: object, key_path: tuple[str | int, ...], default=None):
        """Resolve one nested value by tuple path."""
        current = raw
        for key in key_path:
            if isinstance(key, int):
                if not isinstance(current, list) or key >= len(current):
                    return default
                current = current[key]
                continue
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def _build_ordered_section_keys(self, raw: dict) -> list[str]:
        ordered_keys: list[str] = []
        for section_key in _PREFERRED_SECTION_ORDER:
            if section_key in raw:
                ordered_keys.append(section_key)
        for section_key in raw.keys():
            if section_key not in ordered_keys:
                ordered_keys.append(section_key)
        return ordered_keys

    def _build_section_model(self, section_key: str, section_value: object) -> ConfigSectionModel:
        if section_value is None and section_key in _KNOWN_LIST_SECTIONS:
            return ConfigSectionModel(
                section_key=section_key,
                title=section_key,
                raw_value_type="list",
                preserve_empty_as_null=True,
                fields=[],
            )
        root_field = self._build_field_model((section_key,), section_key, section_value)
        fields = root_field.children if root_field.value_type in {"mapping", "list"} else [root_field]
        return ConfigSectionModel(
            section_key=section_key,
            title=section_key,
            raw_value_type=root_field.value_type,
            preserve_empty_as_null=False,
            fields=fields,
        )

    def _build_field_model(
        self,
        path: tuple[str | int, ...],
        label: str,
        value: object,
    ) -> ConfigFieldModel:
        value = self._with_editor_defaults(path, value)
        if isinstance(value, dict):
            children = [self._build_field_model(path + (key,), str(key), child_value) for key, child_value in value.items()]
            return ConfigFieldModel(
                path=path,
                label=label,
                value=None,
                value_type="mapping",
                editable=False,
                children=children,
            )

        if isinstance(value, list):
            children = [
                self._build_field_model(path + (index,), f"[{index}]", child_value)
                for index, child_value in enumerate(value)
            ]
            return ConfigFieldModel(
                path=path,
                label=label,
                value=None,
                value_type="list",
                editable=False,
                children=children,
            )

        value = self._normalize_scalar_value(path, value)
        return ConfigFieldModel(
            path=path,
            label=label,
            value=value,
            value_type=self._resolve_scalar_type(path, value),
            editable=True,
        )

    def _resolve_scalar_type(self, path: tuple[str | int, ...], value: object) -> str:
        if path and path[-1] == _AXIS_FIRMWARE_VERSION_FIELD:
            return "version"
        if path and str(path[-1]) in _CODE_STYLE_FIELDS:
            return "code"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        return "string"

    def _with_editor_defaults(self, path: tuple[str | int, ...], value: object) -> object:
        """Inject editor-only defaults for schema fields that older YAML files may omit."""
        if not isinstance(value, dict):
            return value
        if len(path) < 3 or path[-2] != "axes":
            return value
        if path[0] not in {"robot arm configuration", "robot"}:
            return value
        if _AXIS_FIRMWARE_VERSION_FIELD in value:
            return value

        normalized_value = dict(value)
        normalized_value[_AXIS_FIRMWARE_VERSION_FIELD] = None
        return normalized_value

    def _normalize_scalar_value(self, path: tuple[str | int, ...], value: object) -> object:
        if not path:
            return value

        if str(path[-1]) not in _CODE_STYLE_FIELDS:
            return value

        if value is None:
            return ""
        if isinstance(value, int):
            return f"{value:02d}"

        cleaned_value = str(value).strip()
        if cleaned_value.isdigit():
            return cleaned_value.zfill(2)
        return cleaned_value

    def _clean_optional_string(self, value: object) -> str | None:
        if value is None:
            return None
        cleaned_value = str(value).strip()
        return cleaned_value or None
