"""Unit tests for workspace bridge snapshots."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gui.workspace.bridges import WorkspaceRuntimeBridge
from myconfig.constants import COMMANDS
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig


class WorkspaceRuntimeBridgeTests(unittest.TestCase):
    """Verifies bridge-side project summaries without launching the GUI."""

    def test_bridge_reads_bench_defaults_from_project_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
system:
  axes: 4
features:
  firmware_tools: true
  application_tools: true
ui:
  workspace: phase2_shell
mcu:
  serial_port:
    name: COM9
    baudrate: 230400
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                system_axes=4,
                features=ProjectFeatures(firmware_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            bridge = WorkspaceRuntimeBridge(project)
            bench_defaults = {item.label: item.value for item in bridge.get_bench_default_items()}

            self.assertEqual(bench_defaults["Serial port"], "COM9")
            self.assertEqual(bench_defaults["Baudrate"], "230400")
            self.assertEqual(bench_defaults["Axis count"], "4")

    def test_bridge_logs_project_context_without_launching_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)
            message = bridge.run_action("log_project_context")

            self.assertIn("Project context:", message)
            self.assertIn("Demo", message)

    def test_bridge_discovers_ports_without_creating_runtime_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
mcu:
  serial_port:
    name: COM5
    baudrate: 115200
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                features=ProjectFeatures(firmware_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            bridge = WorkspaceRuntimeBridge(project)
            with patch("gui.workspace.bridges.workspace_runtime_bridge.RobotBackendClient.get_available_ports", return_value=["COM11"]):
                communication_model = bridge.get_runtime_communication_model(create_if_missing=False)

            self.assertFalse(bridge.has_live_runtime)
            self.assertEqual(communication_model["selected_port"], "COM5")
            self.assertEqual(communication_model["ports"][0]["value"], "COM5")
            self.assertEqual(communication_model["ports"][1]["value"], "COM11")
            self.assertIn("Invalid", communication_model["ports"][0]["label"])
            self.assertIn("Valid", communication_model["ports"][1]["label"])

    def test_bridge_sends_legacy_robot_power_commands_through_existing_runtime_path(self) -> None:
        class _FakeBackendClient:
            def __init__(self) -> None:
                self.sent_commands: list[tuple[int, list[int]]] = []

            def is_connected(self) -> bool:
                return True

            def get_command_bytes(self, command_name: str, fallback: list[int] | None = None) -> list[int]:
                return list(COMMANDS.get(command_name, fallback or []))

            def send_command_bytes(self, node_id: int, command_bytes: list[int]) -> bytearray:
                self.sent_commands.append((node_id, list(command_bytes)))
                return bytearray(command_bytes)

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(backend_client=_FakeBackendClient(), sys_mode=None)

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                on_payload = bridge.send_runtime_robot_power(True)
                off_payload = bridge.send_runtime_robot_power(False)

            self.assertEqual(runtime_window.backend_client.sent_commands[0], (1, COMMANDS["ROBOT On"]))
            self.assertEqual(runtime_window.backend_client.sent_commands[1], (1, COMMANDS["ROBOT Off"]))
            self.assertEqual(list(on_payload), COMMANDS["ROBOT On"])
            self.assertEqual(list(off_payload), COMMANDS["ROBOT Off"])
            self.assertIsNone(runtime_window.sys_mode)

    def test_bridge_runtime_robot_nodes_exposes_detected_nodes_for_active_scan_ui(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(
                node_status={
                    5: {"connected": True, "firmware": "v1.0.0", "uuid": "", "type": "", "interrupt": ""},
                    8: {"connected": True, "firmware": "v1.0.0", "uuid": "", "type": "", "interrupt": ""},
                    9: {"connected": True, "firmware": "v1.0.0", "uuid": "", "type": "", "interrupt": ""},
                    12: {"connected": True, "firmware": "v1.0.0", "uuid": "", "type": "", "interrupt": ""},
                },
                detected_nodes={5, 8, 9, 12},
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                nodes = bridge.get_runtime_robot_nodes(create_if_missing=False)

            self.assertEqual(nodes["connected_nodes"], [5, 8, 9, 12])
            self.assertEqual(nodes["detected_nodes"], [5, 8, 9, 12])

    def test_bridge_requests_runtime_scan_through_burst_path_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            scan_requests: list[str] = []
            runtime_window = SimpleNamespace(
                dispatch_node_scan_batch=lambda: scan_requests.append("burst") or True,
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                self.assertTrue(bridge.request_runtime_node_scan())

            self.assertEqual(scan_requests, ["burst"])

    def test_bridge_does_not_fall_back_to_removed_sequential_scan_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            sequential_calls: list[str] = []
            runtime_window = SimpleNamespace(
                start_node_scan=lambda: sequential_calls.append("sequential"),
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                self.assertFalse(bridge.request_runtime_node_scan())

            self.assertEqual(sequential_calls, [])

    def test_bridge_exposes_runtime_emergency_stop_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(emergency_stop_active=True)

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                self.assertTrue(bridge.get_runtime_emergency_stop_state(create_if_missing=False))

    def test_bridge_exposes_per_node_interrupt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(
                node_status={
                    8: {
                        "interrupt_state": {
                            "int0": 0,
                            "int1": 1,
                            "left_cut": True,
                            "right_cut": False,
                            "last_source": "d8_query",
                        }
                    },
                    9: {
                        "interrupt_state": {
                            "int0": None,
                            "int1": None,
                            "left_cut": None,
                            "right_cut": True,
                            "last_source": "tpos_cut",
                        }
                    },
                }
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                node8 = bridge.get_runtime_node_interrupt_state(8, create_if_missing=False)
                node9 = bridge.get_runtime_node_interrupt_state(9, create_if_missing=False)
                unknown = bridge.get_runtime_node_interrupt_state(10, create_if_missing=False)

            self.assertEqual(node8["int0"], 0)
            self.assertEqual(node8["int1"], 1)
            self.assertTrue(node8["left_cut"])
            self.assertFalse(node8["right_cut"])
            self.assertEqual(node8["left_state"], "cut")
            self.assertEqual(node8["right_state"], "not_cut")
            self.assertEqual(node9["left_state"], "unknown")
            self.assertEqual(node9["right_state"], "cut")
            self.assertIsNone(unknown["left_cut"])
            self.assertEqual(unknown["left_state"], "unknown")

    def test_bridge_exposes_symmetric_cut_and_not_cut_states_after_left_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(
                node_status={
                    9: {
                        "interrupt_state": {
                            "left_cut": True,
                            "right_cut": False,
                            "last_source": "tpos_cut",
                        }
                    }
                }
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                state = bridge.get_runtime_node_interrupt_state(9, create_if_missing=False)

            self.assertEqual(state["left_state"], "cut")
            self.assertEqual(state["right_state"], "not_cut")

    def test_bridge_exposes_symmetric_cut_and_not_cut_states_after_right_cut(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(
                node_status={
                    9: {
                        "interrupt_state": {
                            "left_cut": False,
                            "right_cut": True,
                            "last_source": "tpos_cut",
                        }
                    }
                }
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                state = bridge.get_runtime_node_interrupt_state(9, create_if_missing=False)

            self.assertEqual(state["left_state"], "not_cut")
            self.assertEqual(state["right_state"], "cut")

    def test_bridge_exposes_runtime_node_motion_polarity_from_runtime_nodeconfig(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
robot:
  axes:
    x:
      node_id: 6
      node_config: "00"
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(
                node_status={
                    6: {"nodeconfig": 0x02},
                }
            )

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                polarity = bridge.get_runtime_node_motion_polarity(6, create_if_missing=False)

            self.assertTrue(polarity["known"])
            self.assertEqual(polarity["source"], "runtime")
            self.assertEqual(polarity["nodeconfig_raw"], 0x02)
            self.assertEqual(polarity["home_sensor"], "L")
            self.assertEqual(polarity["negative_run_sensor"], "R")
            self.assertEqual(polarity["positive_run_sensor"], "L")

    def test_bridge_exposes_runtime_node_motion_polarity_from_config_when_runtime_nodeconfig_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
robot:
  axes:
    x:
      node_id: 6
      node_config: "00"
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(node_status={6: {}})

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                polarity = bridge.get_runtime_node_motion_polarity(6, create_if_missing=False)

            self.assertTrue(polarity["known"])
            self.assertEqual(polarity["source"], "config")
            self.assertEqual(polarity["nodeconfig_raw"], 0x00)
            self.assertEqual(polarity["home_sensor"], "L")
            self.assertEqual(polarity["negative_run_sensor"], "L")
            self.assertEqual(polarity["positive_run_sensor"], "R")

    def test_bridge_parses_binary_style_nodeconfig_string_for_motion_polarity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
robot:
  axes:
    pz:
      node_id: 9
      node_config: "0010"
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            bridge = WorkspaceRuntimeBridge(project)
            runtime_window = SimpleNamespace(node_status={9: {}})

            with patch.object(bridge, "get_runtime_window", return_value=runtime_window):
                polarity = bridge.get_runtime_node_motion_polarity(9, create_if_missing=False)

            self.assertTrue(polarity["known"])
            self.assertEqual(polarity["source"], "config")
            self.assertEqual(polarity["nodeconfig_raw"], 0x02)
            self.assertEqual(polarity["negative_run_sensor"], "R")
            self.assertEqual(polarity["positive_run_sensor"], "L")

    def test_bridge_loads_editor_model_from_accuess_style_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ACCuESS.yaml"
            config_path.write_text(
                """
project:
  name: ACCuESS
  display_name: ACCuESS
  config_version: 0.0.0.1
features:
  firmware_tools: true
ui:
  workspace: main_window
robot system configuration:
  axes number: 5
serial_port:
  name: COM11
  baudrate: 115200
mcu configuration:
  firmware version: 0.0.1.6
robot arm configuration:
  axes:
    ya:
      node_id: 3
      node_config: 02
      sw_standby_position: 21.01
command list:
geometry:
  ya_min_y: 15.3
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="ACCuESS",
                display_name="ACCuESS",
                config_path=config_path,
                config_version="0.0.0.1",
                system_axes=5,
                features=ProjectFeatures(firmware_tools=True),
                ui=ProjectUiConfig(workspace="main_window"),
            )

            bridge = WorkspaceRuntimeBridge(project)
            editor_model = bridge.get_config_editor_model()

            self.assertEqual(editor_model.project_name, "ACCuESS")
            self.assertEqual(editor_model.version, "0.0.0.1")
            section_map = {section.section_key: section for section in editor_model.sections}
            self.assertIn("robot system configuration", section_map)
            self.assertIn("robot arm configuration", section_map)
            self.assertEqual(section_map["command list"].raw_value_type, "list")
            self.assertEqual(section_map["command list"].fields, [])
            axes_field = next(
                field for field in section_map["robot arm configuration"].fields if field.path[-1] == "axes"
            )
            ya_axis = next(child for child in axes_field.children if child.path[-1] == "ya")
            node_config_field = next(child for child in ya_axis.children if child.path[-1] == "node_config")
            fw_version_field = next(child for child in ya_axis.children if child.path[-1] == "fw_version")
            self.assertEqual(node_config_field.value_type, "code")
            self.assertEqual(node_config_field.value, "02")
            self.assertEqual(fw_version_field.value_type, "version")
            self.assertIsNone(fw_version_field.value)

    def test_bridge_requires_new_version_before_saving_and_updates_active_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
ui:
  workspace: phase2_shell
features:
  firmware_tools: true
serial_port:
  name: COM9
  baudrate: 230400
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
                features=ProjectFeatures(firmware_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            bridge = WorkspaceRuntimeBridge(project)
            payload = copy.deepcopy(bridge.raw_config)

            save_plan = bridge.save_config_changes(payload)

            self.assertTrue(save_plan.requires_confirmation)

            payload["ui"]["workspace"] = "updated_shell"
            save_result = bridge.save_config_changes(
                payload,
                requested_version="1.0.1",
                confirmed_new_version=True,
            )

            self.assertEqual(save_result.saved_path.name, "demo_1.0.1.yaml")
            self.assertEqual(bridge.project_config_path.name, "demo_1.0.1.yaml")

    def test_bridge_reload_from_current_project_config_state_updates_feature_flags_without_save(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
features:
  firmware_tools: true
  mechanical_tools: false
ui:
  workspace: phase2_shell
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=False),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            bridge = WorkspaceRuntimeBridge(project)
            payload = copy.deepcopy(bridge.raw_config)
            payload["features"]["mechanical_tools"] = True

            message = bridge.reload_project_config(payload)

            self.assertIn("current Project Config state", message)
            self.assertTrue(bridge.project_definition.features.mechanical_tools)
            self.assertTrue(bridge.raw_config["features"]["mechanical_tools"])

    def test_bridge_only_reports_live_overlays_for_mismatches(self) -> None:
        class _RuntimeWindow:
            def __init__(self, version: str) -> None:
                self.runtime_system_state = {"mcu_version": version}

            @property
            def mcu_version(self) -> str | None:
                return self.runtime_system_state.get("mcu_version")

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
mcu configuration:
  firmware version: 1.0.0
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._runtime_launcher._window = _RuntimeWindow("2.0.0")

            overlays = bridge.get_live_hardware_overlays()
            self.assertEqual(len(overlays), 1)
            self.assertEqual(overlays[0].display_text, "Actual: MCU Version = 2.0.0")

            bridge._runtime_launcher._window = _RuntimeWindow("1.0.0")
            self.assertEqual(bridge.get_live_hardware_overlays(), [])

    def test_bridge_reports_node_type_live_overlay_only_for_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
robot arm configuration:
  axes:
    ya:
      node_id: 3
      node_type: 1
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._runtime_launcher._window = SimpleNamespace(node_status={3: {"type": 1}})
            self.assertEqual(bridge.get_live_hardware_overlays(), [])

            bridge._runtime_launcher._window = SimpleNamespace(node_status={3: {"type": 7}})
            overlays = bridge.get_live_hardware_overlays()
            self.assertEqual(len(overlays), 1)
            self.assertEqual(overlays[0].display_text, "Actual: YA Node Type = 7")

    def test_bridge_rejects_non_yaml_file_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
            invalid_path = Path(temp_dir) / "notes.txt"
            invalid_path.write_text("not a yaml config", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._config_reader._active_path = invalid_path

            with self.assertRaisesRegex(ValueError, "must be YAML"):
                bridge.open_project_config_file()
            with self.assertRaisesRegex(ValueError, "must be YAML"):
                bridge.reveal_project_config_file()

    def test_bridge_rejects_yaml_file_actions_outside_project_config_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as external_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
            external_path = Path(external_dir) / "external.yaml"
            external_path.write_text("project:\n  name: external\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._config_reader._active_path = external_path

            with self.assertRaisesRegex(PermissionError, "must stay inside"):
                bridge.open_project_config_file()
            with self.assertRaisesRegex(PermissionError, "must stay inside"):
                bridge.reveal_project_config_file()

    def test_bridge_reveal_action_uses_explorer_selection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)

            with patch("gui.workspace.bridges.workspace_runtime_bridge.subprocess.Popen") as popen:
                message = bridge.reveal_project_config_file()

            popen.assert_called_once_with(["explorer.exe", "/select,", str(config_path.resolve())])
            self.assertIn("file explorer", message)

    def test_bridge_open_action_uses_platform_file_open_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)

            with patch("gui.workspace.bridges.workspace_runtime_bridge.os.startfile", create=True) as startfile:
                message = bridge.open_project_config_file()

            startfile.assert_called_once_with(config_path.resolve())
            self.assertIn("Opened project config file", message)

    def test_bridge_open_and_reveal_actions_target_newly_saved_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "1.0.1"
            save_result = bridge.save_config_changes(
                payload,
                requested_version="1.0.1",
                confirmed_new_version=True,
            )

            with patch("gui.workspace.bridges.workspace_runtime_bridge.os.startfile", create=True) as startfile:
                bridge.open_project_config_file()
            with patch("gui.workspace.bridges.workspace_runtime_bridge.subprocess.Popen") as popen:
                bridge.reveal_project_config_file()

            startfile.assert_called_once_with(save_result.saved_path.resolve())
            popen.assert_called_once_with(["explorer.exe", "/select,", str(save_result.saved_path.resolve())])

    def test_bridge_file_actions_report_missing_file_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
            missing_path = Path(temp_dir) / "missing.yaml"

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._config_reader._active_path = missing_path

            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                bridge.open_project_config_file()
            with self.assertRaisesRegex(FileNotFoundError, "does not exist"):
                bridge.reveal_project_config_file()

    def test_bridge_open_action_wraps_os_shell_failures_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)

            with patch(
                "gui.workspace.bridges.workspace_runtime_bridge.os.startfile",
                side_effect=OSError("shell failed"),
                create=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "Unable to open project config file demo.yaml: shell failed"):
                    bridge.open_project_config_file()

    def test_bridge_reveal_action_wraps_os_shell_failures_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
            )

            bridge = WorkspaceRuntimeBridge(project)

            with patch(
                "gui.workspace.bridges.workspace_runtime_bridge.subprocess.Popen",
                side_effect=OSError("explorer failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Unable to reveal project config file demo.yaml: explorer failed"):
                    bridge.reveal_project_config_file()

    def test_bridge_rejects_existing_config_version_before_saving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
""".strip(),
                encoding="utf-8",
            )
            existing_dir = Path(temp_dir) / "history"
            existing_dir.mkdir()
            existing_target = existing_dir / "demo_1.0.1.yaml"
            existing_target.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.1
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "1.0.1"

            with self.assertRaisesRegex(FileExistsError, "Config version 1.0.1 already exists"):
                bridge.save_config_changes(
                    payload,
                    requested_version="1.0.1",
                    confirmed_new_version=True,
                )

    def test_bridge_rejects_invalid_config_version_format_before_saving(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "release candidate 1"

            with self.assertRaisesRegex(ValueError, "Config version must use digits separated by dots"):
                bridge.save_config_changes(
                    payload,
                    requested_version="release candidate 1",
                    confirmed_new_version=True,
                )

    def test_bridge_save_keeps_yaml_value_while_live_hardware_mismatch_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
  config_version: 1.0.0
mcu configuration:
  firmware version: 1.0.0
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                config_version="1.0.0",
            )

            bridge = WorkspaceRuntimeBridge(project)
            bridge._runtime_launcher._window = SimpleNamespace(mcu_version="2.0.0")

            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "1.0.1"

            save_result = bridge.save_config_changes(
                payload,
                requested_version="1.0.1",
                confirmed_new_version=True,
            )
            saved_data = bridge.raw_config

            self.assertEqual(save_result.saved_path.name, "demo_1.0.1.yaml")
            self.assertEqual(saved_data["mcu configuration"]["firmware version"], "1.0.0")

            overlays = bridge.get_live_hardware_overlays()
            self.assertEqual(len(overlays), 1)
            self.assertEqual(overlays[0].display_text, "Actual: MCU Version = 2.0.0")


if __name__ == "__main__":
    unittest.main()
