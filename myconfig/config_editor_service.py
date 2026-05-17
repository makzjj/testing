"""Services for loading, validating, and rebuilding editable config documents."""

from __future__ import annotations

import copy
import logging
from pathlib import Path

import yaml

from myconfig.config_models import (
    ConfigDocument,
    ConfigEditorModel,
    ConfigFieldModel,
    ConfigValidationIssue,
    LiveHardwareFieldValue,
)
from myconfig.config_schema_adapter import ConfigSchemaAdapter
from myconfig.version_utils import is_valid_version_text
from myconfig.yaml_repair_service import YamlRepairService


logger = logging.getLogger("myconfig.config_editor_service")


class ConfigEditorService:
    """Loads YAML-backed config documents and prepares them for the workspace editor."""

    def __init__(
        self,
        adapter: ConfigSchemaAdapter | None = None,
        repair_service: YamlRepairService | None = None,
    ) -> None:
        self._adapter = adapter or ConfigSchemaAdapter()
        self._repair_service = repair_service or YamlRepairService()

    def load_current_config(self, path: Path) -> ConfigDocument:
        """Load one current YAML config document after the repair diagnostic step."""
        # 1. Run the explicit malformed-YAML diagnostic/repair step
        diagnostic = self._repair_service.repair_if_needed(path)
        if not diagnostic.is_valid:
            raise ValueError(diagnostic.message)
        # 2. Parse the YAML source into a top-level mapping
        raw_data, explicit_null_paths = self._read_yaml_mapping(path)
        # 3. Build the canonical in-memory config document
        return self._build_document(path, raw_data, explicit_null_paths)

    def build_editor_model(self, path: Path) -> ConfigEditorModel:
        """Build the editor-facing section model for the Project Config page."""
        # 1. Load the current YAML document
        document = self.load_current_config(path)
        return self.build_editor_model_from_raw_data(document.source_path, document.raw_data)

    def build_editor_model_from_raw_data(self, path: Path, raw_data: dict) -> ConfigEditorModel:
        """Build the editor model from the current in-memory config state."""
        document = self._build_document(path, copy.deepcopy(raw_data), set())
        # 2. Validate the loaded document
        validation_issues = self.validate_document(document)
        # 3. Convert the raw YAML into ordered editor sections
        sections = self._adapter.build_editor_sections(document.raw_data)
        # 4. Return the bridge-friendly editor model
        return ConfigEditorModel(
            sections=sections,
            source_path=document.source_path,
            project_name=document.project_name,
            version=document.version,
            validation_issues=validation_issues,
        )

    def apply_edit_payload(self, document: ConfigDocument, payload: dict) -> ConfigDocument:
        """Rebuild a config document from the current UI-edited payload."""
        # 1. Defend against malformed UI payloads
        if not isinstance(payload, dict):
            raise ValueError("Edited config payload must be a mapping")
        # 2. Copy the edited data so save logic cannot mutate UI-owned references
        raw_data = copy.deepcopy(payload)
        # 3. Return a rebuilt config document with updated identity metadata
        return self._build_document(document.source_path, raw_data, set(document.explicit_null_paths))

    def validate_document(self, document: ConfigDocument) -> list[ConfigValidationIssue]:
        """Validate one config document for safe editor and save behavior."""
        # 1. Validate required project metadata
        issues = self._validate_required_project_fields(document.raw_data)
        # 2. Surface non-fatal shape problems as warnings instead of blocking the page
        issues.extend(self._validate_noncritical_optional_sections(document.raw_data))
        # 3. Validate version-style axis firmware fields when present
        issues.extend(self._validate_axis_firmware_versions(document.raw_data))
        # 4. Validate that the YAML structure remains serializable
        issues.extend(self._validate_yaml_serialization(document.raw_data))
        # 5. Return the accumulated validation issues
        logger.debug("Validated config document, issues=%d path=%s", len(issues), document.source_path)
        return issues

    def apply_live_overlays(
        self,
        editor_model: ConfigEditorModel,
        overlays: list[LiveHardwareFieldValue],
    ) -> ConfigEditorModel:
        """Attach mismatch-only live hardware overlays onto the editor model."""
        # 1. Index overlays by their YAML field path
        overlay_map = {overlay.path: overlay for overlay in overlays}
        # 2. Walk the editor model recursively and attach matching overlays
        for section in editor_model.sections:
            for field in section.fields:
                self._attach_field_overlays(field, overlay_map)
        # 3. Return the updated model for convenience
        return editor_model

    def _read_yaml_mapping(self, path: Path) -> tuple[dict, set[tuple[str | int, ...]]]:
        logger.debug("Reading YAML mapping for editor model, path=%s", path)
        source_text = path.read_text(encoding="utf-8")
        raw_data = yaml.safe_load(source_text) or {}
        if not isinstance(raw_data, dict):
            raise ValueError("Top-level YAML content must be a mapping")
        return raw_data, self._collect_explicit_null_paths(source_text)

    def _build_document(
        self,
        path: Path,
        raw_data: dict,
        explicit_null_paths: set[tuple[str | int, ...]] | None = None,
    ) -> ConfigDocument:
        logger.debug("Building config document, path=%s", path)
        return ConfigDocument(
            raw_data=raw_data,
            source_path=path.resolve(),
            project_name=self._adapter.extract_project_name(raw_data),
            version=self._adapter.extract_version(raw_data),
            explicit_null_paths=explicit_null_paths or set(),
        )

    def _validate_required_project_fields(self, raw_data: dict) -> list[ConfigValidationIssue]:
        logger.debug("Validating required project fields")
        issues: list[ConfigValidationIssue] = []
        project_section = raw_data.get("project")
        if not isinstance(project_section, dict):
            issues.append(
                ConfigValidationIssue(
                    path=("project",),
                    severity="error",
                    message="Missing or invalid 'project' section",
                )
            )
            return issues

        project_name = project_section.get("name")
        if not isinstance(project_name, str) or not project_name.strip():
            issues.append(
                ConfigValidationIssue(
                    path=("project", "name"),
                    severity="error",
                    message="Missing required project.name",
                )
            )

        return issues

    def _validate_yaml_serialization(self, raw_data: dict) -> list[ConfigValidationIssue]:
        logger.debug("Validating YAML serialization safety")
        try:
            yaml.safe_dump(raw_data, sort_keys=False)
        except yaml.YAMLError as exc:
            return [
                ConfigValidationIssue(
                    path=(),
                    severity="error",
                    message=f"Config data cannot be serialized to YAML: {exc}",
                )
            ]
        return []

    def _validate_noncritical_optional_sections(self, raw_data: dict) -> list[ConfigValidationIssue]:
        logger.debug("Validating noncritical optional section shapes")
        issues: list[ConfigValidationIssue] = []
        for section_name in (
            "system",
            "features",
            "ui",
            "robot system configuration",
            "communication configuration",
            "serial_port",
            "mcu configuration",
            "robot arm configuration",
            "mcu",
            "robot",
        ):
            section_value = raw_data.get(section_name)
            if section_value is None or isinstance(section_value, dict):
                continue
            issues.append(
                ConfigValidationIssue(
                    path=(section_name,),
                    severity="warning",
                    message=f"Optional section '{section_name}' is malformed; rendering the raw YAML value.",
                )
            )
        return issues

    def _validate_axis_firmware_versions(self, raw_data: dict) -> list[ConfigValidationIssue]:
        """Validate per-axis firmware version values when users provide them."""
        issues: list[ConfigValidationIssue] = []
        for axes_root in (
            ("robot arm configuration", "axes"),
            ("robot", "axes"),
        ):
            axes = self._adapter.lookup_path(raw_data, axes_root, default=None)
            if not isinstance(axes, dict):
                continue

            for axis_name, axis_config in axes.items():
                if not isinstance(axis_config, dict):
                    continue
                version_value = axis_config.get("fw_version")
                if version_value in (None, ""):
                    continue
                if is_valid_version_text(str(version_value)):
                    continue
                issues.append(
                    ConfigValidationIssue(
                        path=axes_root + (axis_name, "fw_version"),
                        severity="error",
                        message=(
                            f"{axis_name}.fw_version must use digits separated by dots, "
                            "for example 0.0.1.6"
                        ),
                    )
                )

        return issues

    def _attach_field_overlays(
        self,
        field: ConfigFieldModel,
        overlay_map: dict[tuple[str | int, ...], LiveHardwareFieldValue],
    ) -> None:
        logger.debug("Attaching overlays for field path=%s", field.path)
        if field.path in overlay_map:
            field.live_overlay = overlay_map[field.path]
        for child in field.children:
            self._attach_field_overlays(child, overlay_map)

    def _collect_explicit_null_paths(self, source_text: str) -> set[tuple[str | int, ...]]:
        """Capture YAML paths that were written with an explicit `null` token."""
        root_node = yaml.compose(source_text)
        if root_node is None:
            return set()

        explicit_null_paths: set[tuple[str | int, ...]] = set()
        self._walk_yaml_node(root_node, (), explicit_null_paths)
        return explicit_null_paths

    def _walk_yaml_node(
        self,
        node,
        path: tuple[str | int, ...],
        explicit_null_paths: set[tuple[str | int, ...]],
    ) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                self._walk_yaml_node(value_node, path + (key_node.value,), explicit_null_paths)
            return

        if isinstance(node, yaml.SequenceNode):
            for index, child_node in enumerate(node.value):
                self._walk_yaml_node(child_node, path + (index,), explicit_null_paths)
            return

        if isinstance(node, yaml.ScalarNode) and node.tag == "tag:yaml.org,2002:null" and node.value == "null":
            explicit_null_paths.add(path)
