"""Builds presentation-friendly workspace snapshots from project config."""

from __future__ import annotations

from pathlib import Path

from myconfig.config_schema_adapter import ConfigSchemaAdapter
from myconfig.project_models import ProjectDefinition

from ..models import ActionItem, DetailItem, MetricItem, SessionState
from ..constants import PROJECT_ROOT


class WorkspaceSnapshotFactory:
    """Creates page-ready summary data for the Phase 2 shell."""

    def __init__(self) -> None:
        self._adapter = ConfigSchemaAdapter()

    def build_session_state(
        self,
        project_definition: ProjectDefinition,
        active_page: str,
        has_live_runtime: bool,
    ) -> SessionState:
        """Create lightweight shell status for the selected route."""
        if has_live_runtime:
            connection_text = "Runtime ready"
            session_text = "Bridge live"
            alerts_text = "Shell active"
        else:
            connection_text = "Offline"
            session_text = "Preview mode"
            alerts_text = "Runtime offline"

        return SessionState(
            project_name=project_definition.display_name,
            connection_text=connection_text,
            session_text=session_text,
            active_page=active_page,
            alerts_text=alerts_text,
            has_live_runtime=has_live_runtime,
            operator_name="Missing",
            assembler_name="Missing",
            metadata_edit_enabled=False,
        )

    def build_boot_messages(self, project_definition: ProjectDefinition) -> list[str]:
        """Create initial console messages for workspace startup."""
        return [
            f"Workspace shell ready for project {project_definition.display_name}",
            f"Config path: {project_definition.config_path}",
            "Phase 2 shell uses layered modules across shell, pages, sections, widgets, and bridges",
        ]

    def build_overview_metrics(self, project_definition: ProjectDefinition, raw_config: dict, has_live_runtime: bool) -> list[MetricItem]:
        """Build top-level KPI cards."""
        configured_nodes = len(self._collect_axis_nodes(raw_config)) + len(self._collect_sensor_nodes(raw_config))
        nodes_value = f"0 / {configured_nodes}" if configured_nodes else "0 / n/a"
        motor_value = "Stable" if has_live_runtime else "Standby"
        frame_loss_value = "n/a" if not has_live_runtime else "Pending"
        alerts_value = "0" if has_live_runtime else "1"

        return [
            MetricItem("Nodes online", nodes_value, "YAML config", "neutral"),
            MetricItem("Motor health", motor_value, "Live feed later", "neutral"),
            MetricItem("Frame loss", frame_loss_value, "Pending", "warning"),
            MetricItem("Active alerts", alerts_value, "Alerts", "warning"),
        ]

    def build_transport_items(self, raw_config: dict, has_live_runtime: bool) -> list[DetailItem]:
        """Build overview transport summary rows."""
        serial_port = self._adapter.extract_serial_port_name(raw_config) or "Not configured"
        baudrate = self._adapter.extract_serial_baudrate(raw_config) or "115200"
        workspace_mode = self._lookup(raw_config, ("ui", "workspace"), "phase2_shell")
        runtime_state = "Connected" if has_live_runtime else "Waiting"

        return [
            DetailItem("Link state", runtime_state),
            DetailItem("Serial endpoint", str(serial_port)),
            DetailItem("Baud rate", str(baudrate)),
            DetailItem("Workspace", str(workspace_mode)),
        ]

    def build_node_summary_items(self, project_definition: ProjectDefinition, raw_config: dict) -> list[DetailItem]:
        """Build overview node-summary rows from YAML data."""
        axis_nodes = self._collect_axis_nodes(raw_config)
        sensor_nodes = self._collect_sensor_nodes(raw_config)
        hmi_type = self._lookup(raw_config, ("robot", "hmi_type"), self._lookup(raw_config, ("system", "nghmi"), "n/a"))

        return [
            DetailItem("Configured axes", str(project_definition.system_axes or len(axis_nodes) or "n/a")),
            DetailItem("Axis nodes", ", ".join(axis_nodes) or "n/a"),
            DetailItem("Sensor nodes", ", ".join(sensor_nodes) or "n/a"),
            DetailItem("HMI endpoint", str(hmi_type)),
        ]

    def build_runtime_alerts(self, has_live_runtime: bool) -> list[str]:
        """Build overview runtime alerts."""
        if has_live_runtime:
            return [
                "Runtime panel is active in this workspace window.",
                "Serial and hardware state are shared across shell panels.",
            ]

        return [
            "Runtime disconnected.",
            "Open from Quick actions to activate the runtime panel.",
        ]

    def build_quick_actions(self) -> list[ActionItem]:
        """Build shared quick actions used by overview and settings."""
        return [
            ActionItem("open_legacy_runtime", "Open Runtime", "Open the in-workspace runtime panel"),
            ActionItem("focus_legacy_runtime", "Focus Runtime", "Switch to the in-workspace runtime panel"),
            ActionItem("refresh_workspace", "Refresh", "Reload session and summary data"),
            ActionItem("log_project_context", "Log Context", "Write project context to console"),
        ]

    def build_project_capability_items(self, project_definition: ProjectDefinition) -> list[DetailItem]:
        """Build capability rows from the typed feature flags."""
        return [
            DetailItem("Firmware", self._format_bool(project_definition.features.firmware_tools)),
            DetailItem("Mechanical", self._format_bool(project_definition.features.mechanical_tools)),
            DetailItem("Plots", self._format_bool(project_definition.features.application_tools)),
            DetailItem("Integration test", self._format_bool(project_definition.features.integration_test)),
            DetailItem("Stress module", self._format_bool(project_definition.features.stress_test)),
        ]

    def build_firmware_command_items(self, raw_config: dict) -> list[DetailItem]:
        """Build firmware command-debug section rows."""
        return [
            DetailItem("Target mode", "Current runtime command bridge"),
            DetailItem("Configured axis count", str(self._axis_count(raw_config))),
            DetailItem("Primary command flow", "Use current runtime for live commands"),
        ]

    def build_protocol_monitor_items(self, raw_config: dict) -> list[DetailItem]:
        """Build UART/protocol section rows."""
        return [
            DetailItem("Serial endpoint", str(self._adapter.extract_serial_port_name(raw_config) or "Not configured")),
            DetailItem("Baudrate", str(self._adapter.extract_serial_baudrate(raw_config) or "115200")),
            DetailItem("Monitor strategy", "Monitor via the current runtime bridge"),
        ]

    def build_frame_loss_items(self) -> list[DetailItem]:
        """Build frame-loss placeholder rows."""
        return [
            DetailItem("Current source", "Feed pending"),
            DetailItem("Expected view", "Summary only"),
            DetailItem("Migration note", "Traces omitted"),
        ]

    def build_motion_command_items(self, raw_config: dict) -> list[DetailItem]:
        """Build firmware motion command section rows."""
        return [
            DetailItem("Configured axes", str(self._axis_count(raw_config))),
            DetailItem("Axis nodes", ", ".join(self._collect_axis_nodes(raw_config)) or "n/a"),
            DetailItem("Execution path", "Start current runtime for live motion"),
        ]

    def build_sensor_snapshot_items(self, raw_config: dict) -> list[DetailItem]:
        """Build firmware sensor snapshot rows."""
        return [
            DetailItem("Sensor count", str(len(self._collect_sensor_nodes(raw_config)))),
            DetailItem("Sensor nodes", ", ".join(self._collect_sensor_nodes(raw_config)) or "n/a"),
            DetailItem("Snapshot mode", "Config and bridge summary"),
        ]

    def build_motor_behaviour_items(self, raw_config: dict) -> list[DetailItem]:
        """Build mechanical behaviour rows."""
        return [
            DetailItem("Observed axes", ", ".join(self._collect_axis_names(raw_config)) or "n/a"),
            DetailItem("Observation mode", "Shell summary only"),
            DetailItem("Workspace note", "Use page-local tools for mechanical work"),
        ]

    def build_axis_control_items(self, raw_config: dict) -> list[DetailItem]:
        """Build axis-control rows."""
        return [
            DetailItem("Axis count", str(self._axis_count(raw_config))),
            DetailItem("Configured standby positions", self._format_axis_positions(raw_config)),
            DetailItem("Control path", "Runtime bridge for live movement"),
        ]

    def build_repeatability_items(self) -> list[DetailItem]:
        """Build repeatability section rows."""
        return [
            DetailItem("Current support", "Reserved page section"),
            DetailItem("Phase 2 focus", "Information architecture and module ownership"),
            DetailItem("Future path", "Repeatability workflows can attach here later"),
        ]

    def build_sensor_limit_items(self, raw_config: dict) -> list[DetailItem]:
        """Build sensor-limit rows from geometry/calibration hints."""
        geometry = raw_config.get("geometry", {})
        calibration = raw_config.get("calibration", {})
        return [
            DetailItem("Geometry values", str(len(geometry)) if isinstance(geometry, dict) else "0"),
            DetailItem("Calibration values", str(len(calibration)) if isinstance(calibration, dict) else "0"),
            DetailItem("Current mode", "Config-side limits and offsets"),
        ]

    def build_axis_snapshot_items(self, raw_config: dict) -> list[DetailItem]:
        """Build selected-axis snapshot rows."""
        axis_names = self._collect_axis_names(raw_config)
        first_axis = axis_names[0] if axis_names else "n/a"
        return [
            DetailItem("Selected axis seed", first_axis),
            DetailItem("Counts-per-unit source", "Project YAML"),
            DetailItem("Live telemetry", "Not migrated in Phase 2"),
        ]

    def build_integration_checklist_items(self) -> list[str]:
        """Build application-side checklist notes."""
        return [
            "Confirm project context before bench work.",
            "Keep integration tools inside focused modules.",
            "Use the workspace shell as the stable entry.",
        ]

    def build_controller_profile_items(self, raw_config: dict) -> list[DetailItem]:
        """Build controller profile rows."""
        return [
            DetailItem("Config version", str(self._lookup(raw_config, ("project", "config_version"), "1"))),
            DetailItem("Workspace tag", str(self._lookup(raw_config, ("ui", "workspace"), "phase2_shell"))),
            DetailItem("Serial path", str(self._adapter.extract_serial_port_name(raw_config) or "Not configured")),
        ]

    def build_test_run_setup_items(self, project_definition: ProjectDefinition, raw_config: dict) -> list[DetailItem]:
        """Build application test-setup rows."""
        return [
            DetailItem("Project", project_definition.display_name),
            DetailItem("Axis count", str(self._axis_count(raw_config))),
            DetailItem("Runtime handoff", "Bridge actions handle live handoff"),
        ]

    def build_project_metadata_items(self, project_definition: ProjectDefinition, raw_config: dict) -> list[DetailItem]:
        """Build settings metadata rows."""
        return [
            DetailItem("Project", project_definition.name),
            DetailItem("Display name", project_definition.display_name),
            DetailItem("Config file", self._format_config_path(project_definition.config_path)),
            DetailItem("Workspace note", self._truncate_text(str(self._lookup(raw_config, ("ui", "notes"), "n/a")), 26)),
        ]

    def build_enabled_tool_items(self, project_definition: ProjectDefinition) -> list[DetailItem]:
        """Build settings feature-flag rows."""
        return self.build_project_capability_items(project_definition)

    def build_bench_default_items(self, raw_config: dict) -> list[DetailItem]:
        """Build settings bench-default rows."""
        return [
            DetailItem("Serial port", str(self._adapter.extract_serial_port_name(raw_config) or "Not configured")),
            DetailItem("Baudrate", str(self._adapter.extract_serial_baudrate(raw_config) or "115200")),
            DetailItem("Axis count", str(self._axis_count(raw_config))),
            DetailItem("UI seed", str(self._lookup(raw_config, ("ui", "workspace"), "phase2_shell"))),
        ]

    def build_configuration_actions(self) -> list[ActionItem]:
        """Build settings action rows."""
        return [
            ActionItem("open_legacy_runtime", "Open runtime", "Open the in-workspace runtime panel"),
            ActionItem("refresh_workspace", "Refresh shell", "Refresh shell summaries from project config"),
            ActionItem("log_project_context", "Log context", "Write the selected project metadata into the console"),
        ]

    def _format_config_path(self, config_path: Path) -> str:
        try:
            return str(config_path.resolve().relative_to(PROJECT_ROOT))
        except ValueError:
            return config_path.name

    def _truncate_text(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[: max_length - 3].rstrip() + "..."

    def _collect_axis_names(self, raw_config: dict) -> list[str]:
        return [str(name) for name in self._adapter.extract_axis_section(raw_config).keys()]

    def _collect_axis_nodes(self, raw_config: dict) -> list[str]:
        axes = self._adapter.extract_axis_section(raw_config)
        return [str(axis_data.get("node_id", "?")) for axis_data in axes.values() if isinstance(axis_data, dict)]

    def _collect_sensor_nodes(self, raw_config: dict) -> list[str]:
        sensors = self._adapter.extract_sensor_section(raw_config)
        return [str(sensor_data.get("node_id", "?")) for sensor_data in sensors.values() if isinstance(sensor_data, dict)]

    def _format_axis_positions(self, raw_config: dict) -> str:
        axes = self._adapter.extract_axis_section(raw_config)
        if not axes:
            return "n/a"

        parts: list[str] = []
        for name, axis_data in axes.items():
            if not isinstance(axis_data, dict):
                continue
            standby = axis_data.get("standby_position", axis_data.get("sw_standby_position"))
            if standby is not None:
                parts.append(f"{name}={standby}")
        return ", ".join(parts) if parts else "n/a"

    def _axis_count(self, raw_config: dict):
        value = self._adapter.extract_axes_count(raw_config)
        return value if value is not None else "n/a"

    def _format_bool(self, value: bool) -> str:
        return "Enabled" if value else "Disabled"

    def _lookup(self, raw_config: dict, keys: tuple[str, ...], default):
        current = raw_config
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current
