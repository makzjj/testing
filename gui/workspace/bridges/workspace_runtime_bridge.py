"""High-level bridge between the new shell and current project/runtime data."""

from __future__ import annotations

import copy
import os
import subprocess
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from myconfig.config_schema_adapter import ConfigSchemaAdapter
from myconfig.constants import NODE_ID_MAPPING
from myconfig.config_editor_service import ConfigEditorService
from myconfig.config_models import ConfigEditorModel, LiveHardwareFieldValue, SavePlan, SaveResult
from myconfig.config_save_service import ConfigSaveService
from myconfig.node_display import ML20_NODE_MAP, get_ml20_node_name
from myconfig.project_loader import build_project_definition
from myconfig.project_models import ProjectDefinition

from ..models import ActionItem, DetailItem, MetricItem, SessionState
from .legacy_runtime_launcher import LegacyRuntimeLauncher
from .live_hardware_overlay_provider import LiveHardwareOverlayProvider
from .raw_project_config_reader import RawProjectConfigReader
from .workspace_snapshot_factory import WorkspaceSnapshotFactory
from services.robot_backend_client import RobotBackendClient
from services.communication_log_store import CommunicationLogStore
from data.binary_cmd_parser import decode_nodeconfig_motion_polarity

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
        self._schema_adapter = ConfigSchemaAdapter()
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

    def get_runtime_communication_log_store(self, *, create_if_missing: bool = False) -> CommunicationLogStore | None:
        """Return the shared communication log buffer from the runtime window."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return None
        store = getattr(runtime_window, "communication_log_store", None)
        if store is None:
            store = getattr(runtime_window, "comm_log_store", None)
        return store

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
        raw_config = self._raw_config
        selected_port = self._schema_adapter.extract_serial_port_name(raw_config)
        selected_baud = self._schema_adapter.extract_serial_baudrate(raw_config) or "115200"
        baud_rates = ["115200", "230400", "345600"]
        connected = False

        if runtime_window is not None:
            if hasattr(runtime_window, "refresh_ports"):
                runtime_window.refresh_ports()

            port_combo = getattr(runtime_window, "port_combo", None)
            if port_combo is not None:
                current_port = port_combo.currentData()
                if current_port not in (None, ""):
                    selected_port = str(current_port)
                baud_combo = getattr(runtime_window, "baud_combo", None)
                if baud_combo is not None:
                    baud_rates = [str(baud_combo.itemText(index)) for index in range(baud_combo.count())] or baud_rates
                    selected_baud = str(baud_combo.currentText() or selected_baud)

            backend_client = getattr(runtime_window, "backend_client", None)
            connected = bool(backend_client and backend_client.is_connected())

        available_ports = self._discover_available_ports(runtime_window)
        ports = self._build_port_items(available_ports, selected_port)
        return {
            "ports": ports,
            "selected_port": selected_port,
            "baud_rates": baud_rates,
            "selected_baud": selected_baud,
            "connected": connected,
        }

    def get_runtime_robot_power_state(self, *, create_if_missing: bool = False) -> bool | None:
        """Return the current robot power state when the runtime has tracked it."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return None

        sys_mode = getattr(runtime_window, "sys_mode", None)
        if not isinstance(sys_mode, dict):
            return None

        text = str(sys_mode.get("text", "")).strip().lower()
        node_id = sys_mode.get("node_id")
        state_value = sys_mode.get("state_value")

        if not text or text == "unknown":
            return None
        if text in {"system off", "off"}:
            return False
        if node_id == 0x01 and state_value == 0:
            return False
        return True

    def get_runtime_emergency_stop_state(self, *, create_if_missing: bool = False) -> bool | None:
        """Return the current global emergency-stop state from the shared runtime."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return None
        state = getattr(runtime_window, "emergency_stop_active", None)
        if isinstance(state, bool):
            return state
        return None

    def send_runtime_robot_power(self, power_on: bool) -> bytearray:
        """Send the robot power command through the existing runtime backend path."""
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            raise RuntimeError("Runtime backend is unavailable for Production operations.")

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            raise RuntimeError("Serial port not connected.")

        command_name = "ROBOT On" if power_on else "ROBOT Off"
        fallback = [0x6F, 0x6E, 0x52, 0x42, 0x3D, 0x31 if power_on else 0x30, 0x0D, 0x0A, 0x0D, 0x0A]
        payload = backend_client.get_command_bytes(command_name, fallback)
        return backend_client.send_command_bytes(0x01, payload)

    def _discover_available_ports(self, runtime_window: object | None = None) -> list[str]:
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is not None and hasattr(backend_client, "get_available_ports"):
            try:
                return [str(port) for port in backend_client.get_available_ports()]
            except Exception:
                return []

        try:
            return [str(port) for port in RobotBackendClient().get_available_ports()]
        except Exception:
            return []

    @staticmethod
    def _format_port_label(port: str) -> str:
        if port == "COM11":
            return f"{port} ✅ (Valid)"
        return f"{port} ❌ (Invalid)"

    def _build_port_items(self, available_ports: list[str], selected_port: str | None) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        seen_ports: set[str] = set()
        for port in available_ports:
            if not port or port in seen_ports:
                continue
            seen_ports.add(port)
            items.append({"label": self._format_port_label(port), "value": port})

        if selected_port and selected_port not in seen_ports:
            items.insert(0, {"label": self._format_port_label(selected_port), "value": selected_port})

        if not items:
            items.append({"label": "No COM ports found ❌ (Invalid)", "value": ""})
        return items

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
        detected_nodes = sorted(
            int(node_id)
            for node_id in (getattr(runtime_window, "detected_nodes", set()) or set())
            if 2 <= int(node_id) <= 17
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
        return {"connected_nodes": connected_nodes, "detected_nodes": detected_nodes, "rows": rows}

    def get_plot_node_options(self, *, create_if_missing: bool = False) -> list[tuple[int, str]]:
        """Return plot-eligible node options from current config/runtime context."""
        if self._uses_ml20_plot_node_map():
            return [
                (3, "X"),
                (4, "Y"),
                (5, "V"),
                (6, "H"),
                (7, "NZ"),
                (8, "RZ"),
                (9, "PZ"),
                (10, "HMI"),
                (11, "NGActuator"),
                (12, "Z"),
            ]

        options_by_node: dict[int, str] = {}

        axes = self._schema_adapter.extract_axis_section(self._raw_config)
        for axis_key, axis_data in axes.items():
            if not isinstance(axis_data, dict):
                continue
            node_id = axis_data.get("node_id")
            if not isinstance(node_id, int):
                continue
            axis_name = str(axis_key).strip().upper()
            options_by_node[int(node_id)] = axis_name or self._fallback_plot_node_label(int(node_id))

        runtime_nodes = self.get_runtime_robot_nodes(create_if_missing=create_if_missing)
        for row in runtime_nodes.get("rows", []):
            if not isinstance(row, dict):
                continue
            node_id = row.get("node_id")
            if not isinstance(node_id, int):
                continue
            options_by_node.setdefault(int(node_id), self._fallback_plot_node_label(int(node_id)))

        return [(node_id, options_by_node[node_id]) for node_id in sorted(options_by_node)]

    def _uses_ml20_plot_node_map(self) -> bool:
        project_names = {
            str(self._project_definition.name or "").strip().lower(),
            str(self._project_definition.display_name or "").strip().lower(),
            str(((self._raw_config.get("project") or {}).get("name") or "")).strip().lower(),
            str(((self._raw_config.get("project") or {}).get("display_name") or "")).strip().lower(),
        }
        return any(name in {"ml2.0", "ml20"} for name in project_names if name)

    def _fallback_plot_node_label(self, node_id: int) -> str:
        if self._uses_ml20_plot_node_map():
            ml20_label = get_ml20_node_name(int(node_id))
            if ml20_label:
                return str(ml20_label)
        label = str(NODE_ID_MAPPING.get(int(node_id), "") or "").strip()
        if label and label.lower() != f"node {int(node_id)}".lower():
            return label
        return ""

    def get_runtime_node_interrupt_state(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        """Return one node's canonical runtime interrupt state."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {
                "node_id": int(node_id),
                "int0": None,
                "int1": None,
                "left_cut": None,
                "right_cut": None,
                "last_source": None,
                "left_state": "unknown",
                "right_state": "unknown",
            }

        node_status = getattr(runtime_window, "node_status", {}) or {}
        status = node_status.get(int(node_id), {}) if isinstance(node_status, dict) else {}
        interrupt_state = status.get("interrupt_state", {}) if isinstance(status, dict) else {}
        int0 = interrupt_state.get("int0") if isinstance(interrupt_state, dict) else None
        int1 = interrupt_state.get("int1") if isinstance(interrupt_state, dict) else None
        left_cut = interrupt_state.get("left_cut") if isinstance(interrupt_state, dict) else None
        right_cut = interrupt_state.get("right_cut") if isinstance(interrupt_state, dict) else None
        last_source = interrupt_state.get("last_source") if isinstance(interrupt_state, dict) else None
        return {
            "node_id": int(node_id),
            "int0": int0,
            "int1": int1,
            "left_cut": left_cut,
            "right_cut": right_cut,
            "last_source": last_source,
            "left_state": self._format_interrupt_display_state(left_cut),
            "right_state": self._format_interrupt_display_state(right_cut),
        }

    def get_runtime_node_motor_current(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        """Return one node's latest canonical runtime motor-current reading."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return {
                "node_id": int(node_id),
                "current_mA": None,
                "current_A": None,
                "sample_count": 0,
                "last_updated": None,
            }

        node_status = getattr(runtime_window, "node_status", {}) or {}
        status = node_status.get(int(node_id), {}) if isinstance(node_status, dict) else {}
        motor_current = status.get("motor_current", {}) if isinstance(status, dict) else {}
        latest_mA = motor_current.get("latest_mA") if isinstance(motor_current, dict) else None
        samples = motor_current.get("samples", []) if isinstance(motor_current, dict) else []
        last_updated = motor_current.get("last_updated") if isinstance(motor_current, dict) else None
        current_mA = int(latest_mA) if isinstance(latest_mA, int) else None
        return {
            "node_id": int(node_id),
            "current_mA": current_mA,
            "current_A": None if current_mA is None else current_mA / 1000.0,
            "sample_count": len(samples) if isinstance(samples, list) else 0,
            "last_updated": last_updated,
        }

    def get_runtime_node_motor_current_series(self, node_id: int, *, create_if_missing: bool = False) -> list[dict[str, object]]:
        """Return a safe copy of one node's bounded runtime motor-current series."""
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is None:
            return []

        node_status = getattr(runtime_window, "node_status", {}) or {}
        status = node_status.get(int(node_id), {}) if isinstance(node_status, dict) else {}
        motor_current = status.get("motor_current", {}) if isinstance(status, dict) else {}
        samples = motor_current.get("samples", []) if isinstance(motor_current, dict) else []
        if not isinstance(samples, list):
            return []
        return [
            {
                "index": int(sample.get("index", 0)),
                "current_mA": int(sample.get("current_mA", 0)),
                "current_A": int(sample.get("current_mA", 0)) / 1000.0,
            }
            for sample in copy.deepcopy(samples)
            if isinstance(sample, dict) and isinstance(sample.get("current_mA"), int)
        ]

    @staticmethod
    def _format_interrupt_display_state(is_cut: object) -> str:
        if is_cut is True:
            return "cut"
        if is_cut is False:
            return "not_cut"
        return "unknown"

    def get_runtime_node_motion_polarity(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        """Return canonical NODECONFIG-derived motion polarity for one node when known."""
        raw_value, source = self._resolve_runtime_nodeconfig_value(int(node_id), create_if_missing=create_if_missing)
        if raw_value is None:
            return {
                "node_id": int(node_id),
                "known": False,
                "source": source,
                "nodeconfig_raw": None,
                "home_sensor": None,
                "opposite_sensor": None,
                "hunting_sign": None,
                "outward_sign": None,
                "return_home_sign": None,
                "negative_run_sensor": None,
                "positive_run_sensor": None,
            }
        try:
            model = decode_nodeconfig_motion_polarity(int(raw_value))
        except Exception:
            return {
                "node_id": int(node_id),
                "known": False,
                "source": source,
                "nodeconfig_raw": int(raw_value) & 0xFF,
                "home_sensor": None,
                "opposite_sensor": None,
                "hunting_sign": None,
                "outward_sign": None,
                "return_home_sign": None,
                "negative_run_sensor": None,
                "positive_run_sensor": None,
            }
        return {
            "node_id": int(node_id),
            "known": True,
            "source": source,
            "nodeconfig_raw": model.nodeconfig_raw,
            "home_sensor": model.home_sensor,
            "opposite_sensor": model.opposite_sensor,
            "hunting_sign": model.hunting_sign,
            "outward_sign": model.outward_sign,
            "return_home_sign": model.return_home_sign,
            "negative_run_sensor": model.negative_run_sensor,
            "positive_run_sensor": model.positive_run_sensor,
        }

    def _resolve_runtime_nodeconfig_value(self, node_id: int, *, create_if_missing: bool) -> tuple[int | None, str | None]:
        runtime_window = self.get_runtime_window(create_if_missing=create_if_missing)
        if runtime_window is not None:
            node_status = getattr(runtime_window, "node_status", {}) or {}
            status = node_status.get(int(node_id), {}) if isinstance(node_status, dict) else {}
            runtime_value = status.get("nodeconfig") if isinstance(status, dict) else None
            normalized_runtime = self._normalize_nodeconfig_value(runtime_value)
            if normalized_runtime is not None:
                return normalized_runtime, "runtime"

        axis_data = self._axis_config_for_node(int(node_id))
        if axis_data is None:
            return None, None
        config_value = self._normalize_nodeconfig_value(axis_data.get("node_config"))
        if config_value is not None:
            return config_value, "config"
        return None, "config"

    def _axis_config_for_node(self, node_id: int) -> dict | None:
        axes = self._schema_adapter.extract_axis_section(self._raw_config)
        for axis_data in axes.values():
            if isinstance(axis_data, dict) and axis_data.get("node_id") == int(node_id):
                return axis_data
        return None

    @staticmethod
    def _normalize_nodeconfig_value(value: object) -> int | None:
        if isinstance(value, int):
            return int(value) & 0xFF
        text = str(value).strip()
        if not text or text.lower() == "n/a":
            return None
        if all(ch in "01" for ch in text) and len(text) in {4, 8}:
            try:
                return int(text, 2) & 0xFF
            except ValueError:
                return None
        try:
            return int(text, 16) & 0xFF
        except ValueError:
            return None

    def request_runtime_node_scan(self) -> bool:
        """Trigger runtime node scan/query flow when the legacy runtime exposes one."""
        runtime_window = self.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return False
        callback = getattr(runtime_window, "dispatch_node_scan_batch", None)
        if not callable(callback):
            return False
        return bool(callback())

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
