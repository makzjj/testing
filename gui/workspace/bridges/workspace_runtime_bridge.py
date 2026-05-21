"""High-level bridge between the new shell and current project/runtime data."""

from __future__ import annotations

import copy
import os
import subprocess
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from myconfig.constants import NODE_ID_MAPPING
from myconfig.config_editor_service import ConfigEditorService
from myconfig.config_models import ConfigEditorModel, LiveHardwareFieldValue, SavePlan, SaveResult
from myconfig.config_save_service import ConfigSaveService
from myconfig.project_loader import build_project_definition
from myconfig.project_models import ProjectDefinition

from ..models import ActionItem, DetailItem, MetricItem, SessionState
from .legacy_runtime_launcher import LegacyRuntimeLauncher
from .live_hardware_overlay_provider import LiveHardwareOverlayProvider
from .raw_project_config_reader import RawProjectConfigReader
from .workspace_snapshot_factory import WorkspaceSnapshotFactory

_ALLOWED_CONFIG_SUFFIXES = {".yaml", ".yml"}

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class WorkspaceRuntimeBridge:
    """Provides page-friendly data and focused actions for the workspace shell."""

    def __init__(self, project_definition: ProjectDefinition) -> None:
        self._project_definition = project_definition
        self._config_reader = RawProjectConfigReader(project_definition)
        self._runtime_launcher = LegacyRuntimeLauncher(project_definition)
        self._snapshot_factory = WorkspaceSnapshotFactory()
        self._config_editor_service = ConfigEditorService()
        self._config_save_service = ConfigSaveService()
        self._live_overlay_provider = LiveHardwareOverlayProvider(self._runtime_launcher)

    def get_boot_messages(self) -> list[str]:
        return self._snapshot_factory.build_boot_messages(self._project_definition)

    def get_session_state(self, active_page: str) -> SessionState:
        return self._snapshot_factory.build_session_state(
            self._project_definition,
            active_page,
            self._runtime_launcher.has_window(),
        )

    def get_overview_metrics(self) -> list[MetricItem]:
        return self._snapshot_factory.build_overview_metrics(
            self._project_definition,
            self._raw_config,
            self._runtime_launcher.has_window(),
        )

    def get_transport_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_transport_items(self._raw_config, self._runtime_launcher.has_window())

    def get_node_summary_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_node_summary_items(self._project_definition, self._raw_config)

    def get_runtime_alerts(self) -> list[str]:
        return self._snapshot_factory.build_runtime_alerts(self._runtime_launcher.has_window())

    def get_quick_actions(self) -> list[ActionItem]:
        return self._snapshot_factory.build_quick_actions()

    def get_project_capability_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_project_capability_items(self._project_definition)

    def get_firmware_command_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_firmware_command_items(self._raw_config)

    def get_protocol_monitor_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_protocol_monitor_items(self._raw_config)

    def get_frame_loss_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_frame_loss_items()

    def get_motion_command_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_motion_command_items(self._raw_config)

    def get_sensor_snapshot_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_sensor_snapshot_items(self._raw_config)

    def get_motor_behaviour_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_motor_behaviour_items(self._raw_config)

    def get_axis_control_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_axis_control_items(self._raw_config)

    def get_repeatability_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_repeatability_items()

    def get_sensor_limit_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_sensor_limit_items(self._raw_config)

    def get_axis_snapshot_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_axis_snapshot_items(self._raw_config)

    def get_integration_checklist_items(self) -> list[str]:
        return self._snapshot_factory.build_integration_checklist_items()

    def get_controller_profile_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_controller_profile_items(self._raw_config)

    def get_test_run_setup_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_test_run_setup_items(self._project_definition, self._raw_config)

    def get_project_metadata_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_project_metadata_items(self._project_definition, self._raw_config)

    def get_enabled_tool_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_enabled_tool_items(self._project_definition)

    def get_bench_default_items(self) -> list[DetailItem]:
        return self._snapshot_factory.build_bench_default_items(self._raw_config)

    def get_configuration_actions(self) -> list[ActionItem]:
        return self._snapshot_factory.build_configuration_actions()

    def get_config_editor_model(self) -> ConfigEditorModel:
        """Load the current Project Config editor model with mismatch-only overlays."""
        # 1. Build the editor model from the current active config state
        editor_model = self._config_editor_service.build_editor_model_from_raw_data(
            self.project_config_path,
            copy.deepcopy(self._raw_config),
        )
        # 2. Collect mismatch-only live hardware overlays from current runtime state
        overlays = self.get_live_hardware_overlays()
        # 3. Attach overlays and return the page-ready model
        return self._config_editor_service.apply_live_overlays(editor_model, overlays)

    def get_live_hardware_overlays(self) -> list[LiveHardwareFieldValue]:
        """Return mismatch-only live hardware comparison data for the editor page."""
        return self._live_overlay_provider.collect_live_values(self._raw_config)

    def save_config_changes(
        self,
        edit_payload: dict,
        requested_version: str | None = None,
        confirmed_new_version: bool = False,
    ) -> SavePlan | SaveResult:
        """Save the current Project Config edits through the version-aware flow."""
        # 1. Load the active config document from disk
        current_document = self._config_editor_service.load_current_config(self.project_config_path)
        # 2. Apply the edited UI payload onto the current document
        edited_document = self._config_editor_service.apply_edit_payload(current_document, edit_payload)
        # 3. Validate the edited document before planning a write
        validation_issues = [
            issue
            for issue in self._config_editor_service.validate_document(edited_document)
            if issue.severity == "error"
        ]
        if validation_issues:
            raise ValueError(validation_issues[0].message)
        # 4. Prepare the version-aware save plan
        save_plan = self._config_save_service.prepare_save(
            edited_document,
            current_version=current_document.version,
            requested_version=requested_version,
            confirmed_new_version=confirmed_new_version,
        )
        if save_plan.requires_confirmation:
            return save_plan
        # 5. Persist the versioned YAML document
        save_result = self._config_save_service.save_document(edited_document, save_plan)
        # 6. Promote the saved file as the new active config path
        self._config_reader.set_active_path(save_result.saved_path)
        self._runtime_launcher.update_config_path(save_result.saved_path)
        self._refresh_project_definition()
        return save_result

    def reload_project_config(self, edit_payload: dict | None = None) -> str:
        """Reload the workspace from disk or from the current edited Project Config state."""
        if edit_payload is None:
            self._config_reader.invalidate()
            self._refresh_project_definition()
            return f"Reloaded project config from {self.project_config_path.name}"

        if not isinstance(edit_payload, dict):
            raise ValueError("Edited project config state must be a mapping")

        self._config_reader.set_cached_raw_config(copy.deepcopy(edit_payload))
        self._refresh_project_definition(self._raw_config)
        return "Reloaded workspace from the current Project Config state"

    def open_project_config_file(self) -> str:
        """Open the current YAML file with the platform-default file handler."""
        path = self._resolve_accessible_config_path(self.project_config_path)
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
        except Exception as exc:
            raise RuntimeError(f"Unable to open project config file {path.name}: {exc}") from exc
        return f"Opened project config file {path.name}"

    def reveal_project_config_file(self) -> str:
        """Reveal the current YAML file in the host file manager."""
        path = self._resolve_accessible_config_path(self.project_config_path)
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", "/select,", str(path.resolve())])
            else:
                webbrowser.open(path.parent.as_uri())
        except Exception as exc:
            raise RuntimeError(f"Unable to reveal project config file {path.name}: {exc}") from exc
        return f"Revealed project config file in the file explorer: {path.name}"

    def run_action(self, action_id: str) -> str:
        """Execute one focused shell action and return a console message."""
        if action_id == "open_legacy_runtime":
            self._runtime_launcher.open_window()
            return f"Opened runtime panel for {self._project_definition.display_name}"

        if action_id == "focus_legacy_runtime":
            self._runtime_launcher.open_window()
            return "Focused runtime panel"

        if action_id == "refresh_workspace":
            self._config_reader.invalidate()
            self._refresh_project_definition()
            return "Workspace summaries refreshed from project config and bridge state"

        if action_id == "log_project_context":
            return f"Project context: {self._project_definition.display_name} ({self.project_config_path})"

        return f"Unknown action requested: {action_id}"

    def get_runtime_widget(self, parent: "QWidget | None" = None) -> "QWidget":
        """Return the shared runtime widget attached to the provided parent."""
        return self._runtime_launcher.ensure_runtime_widget(parent)

    def get_runtime_window(self, *, create_if_missing: bool = False):
        """Return the shared legacy runtime window, creating it lazily when requested."""
        if create_if_missing:
            self._runtime_launcher.ensure_runtime_widget()
        return self._runtime_launcher.current_window()

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        """Return lightweight serial/MCU connection flags from the shared runtime backend."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return False, False

        backend_client = getattr(runtime_window, "backend_client", None)
        serial_connected = bool(backend_client and backend_client.is_connected())
        mcu_connected = serial_connected
        return serial_connected, mcu_connected

    def get_runtime_communication_model(self, *, create_if_missing: bool = False) -> dict:
        """Return Runtime communication UI model from the shared runtime window."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {
                "ports": [],
                "selected_port": None,
                "baud_rates": ["115200", "230400", "345600"],
                "selected_baud": "115200",
                "connected": False,
            }

        if hasattr(runtime_window, "refresh_ports"):
            runtime_window.refresh_ports()

        ports: list[dict[str, str]] = []
        selected_port = None
        port_combo = getattr(runtime_window, "port_combo", None)
        if port_combo is not None:
            for index in range(port_combo.count()):
                port_text = str(port_combo.itemText(index))
                port_value = port_combo.itemData(index)
                ports.append({"label": port_text, "value": str(port_value or "")})
            selected_data = port_combo.currentData()
            selected_port = str(selected_data) if selected_data else None

        baud_rates: list[str] = []
        selected_baud = "115200"
        baud_combo = getattr(runtime_window, "baud_combo", None)
        if baud_combo is not None:
            baud_rates = [str(baud_combo.itemText(index)) for index in range(baud_combo.count())]
            selected_baud = str(baud_combo.currentText() or selected_baud)

        backend_client = getattr(runtime_window, "backend_client", None)
        connected = bool(backend_client and backend_client.is_connected())
        return {
            "ports": ports,
            "selected_port": selected_port,
            "baud_rates": baud_rates or ["115200", "230400", "345600"],
            "selected_baud": selected_baud,
            "connected": connected,
        }

    def connect_runtime_serial(self, *, port: str, baud_rate: int) -> bool:
        """Connect Runtime serial transport using existing Runtime logic."""
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return False

        if hasattr(runtime_window, "refresh_ports"):
            runtime_window.refresh_ports()

        port_combo = getattr(runtime_window, "port_combo", None)
        if port_combo is not None:
            for index in range(port_combo.count()):
                if str(port_combo.itemData(index) or "") == str(port):
                    port_combo.setCurrentIndex(index)
                    break

        baud_combo = getattr(runtime_window, "baud_combo", None)
        if baud_combo is not None:
            baud_combo.setCurrentText(str(baud_rate))
        if hasattr(runtime_window, "on_baud_rate_changed"):
            runtime_window.on_baud_rate_changed(str(baud_rate))
        if hasattr(runtime_window, "connect_serial"):
            runtime_window.connect_serial()

        backend_client = getattr(runtime_window, "backend_client", None)
        connected = bool(backend_client and backend_client.is_connected())
        connect_btn = getattr(runtime_window, "connect_btn", None)
        if connect_btn is not None:
            connect_btn.setChecked(connected)
        return connected

    def disconnect_runtime_serial(self) -> None:
        """Disconnect Runtime serial transport using existing Runtime logic."""
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return
        if hasattr(runtime_window, "disconnect_serial"):
            runtime_window.disconnect_serial()
        connect_btn = getattr(runtime_window, "connect_btn", None)
        if connect_btn is not None:
            connect_btn.setChecked(False)

    def get_runtime_robot_nodes(self, *, create_if_missing: bool = False) -> dict:
        """Return Runtime detected robot-node summary and table rows."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {"connected_nodes": [], "rows": []}

        node_status = getattr(runtime_window, "node_status", {}) or {}
        connected_nodes = sorted(
            node_id for node_id, status in node_status.items() if 2 <= int(node_id) <= 17 and status.get("connected", False)
        )
        rows: list[dict[str, str | int]] = []
        for node_id in connected_nodes:
            status = node_status.get(node_id, {})
            node_name = NODE_ID_MAPPING.get(node_id, "")
            node_display = f"{node_name}({node_id:02d}) ✅ Connected" if node_name else f"{node_id:02d} ✅ Connected"
            if node_id in [5, 9, 10, 16, 17]:
                interrupt_status = "N/A"
            else:
                interrupt_status = str(status.get("interrupt", "") or "")
            rows.append(
                {
                    "node_id": node_id,
                    "node": node_display,
                    "firmware": str(status.get("firmware", "") or ""),
                    "uuid": str(status.get("uuid", "") or ""),
                    "node_type": str(status.get("type", "") or ""),
                    "status": interrupt_status,
                }
            )
        return {"connected_nodes": connected_nodes, "rows": rows}

    @property
    def project_definition(self) -> ProjectDefinition:
        return self._project_definition

    @property
    def project_config_path(self) -> Path:
        return self._config_reader.current_path()

    @property
    def raw_config(self) -> dict:
        return self._raw_config

    @property
    def has_live_runtime(self) -> bool:
        return self._runtime_launcher.has_window()

    @property
    def _raw_config(self) -> dict:
        return self._config_reader.load()

    def _resolve_accessible_config_path(self, path: Path) -> Path:
        """Return the current config path after validating that it is an in-scope YAML file."""
        resolved_path = path.resolve()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Project config file does not exist: {resolved_path}")
        if resolved_path.suffix.lower() not in _ALLOWED_CONFIG_SUFFIXES:
            raise ValueError(f"Project config file must be YAML: {resolved_path.name}")

        config_root = self._project_definition.config_path.resolve().parent
        try:
            resolved_path.relative_to(config_root)
        except ValueError as exc:
            raise PermissionError(
                f"Project config file must stay inside the project config directory: {config_root}"
            ) from exc
        return resolved_path

    def _refresh_project_definition(self, raw_config: dict | None = None) -> None:
        """Rebuild the active project definition from the current config state."""
        current_raw_config = raw_config if raw_config is not None else self._raw_config
        self._project_definition = build_project_definition(current_raw_config, self.project_config_path)
        self._runtime_launcher.update_project_definition(self._project_definition)
