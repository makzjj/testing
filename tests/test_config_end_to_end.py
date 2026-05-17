"""Comprehensive end-to-end verification for the YAML-backed Project Config flow."""

from __future__ import annotations

import copy
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from PyQt6.QtWidgets import QApplication, QDialog

from gui.workspace.bridges import WorkspaceRuntimeBridge
from gui.workspace.pages.project_config_page import ProjectConfigPage
from gui.workspace.sections.project_config.project_config_sections import (
    ConfigFieldWidget,
    ConfigListItemCard,
    ConfigSectionPanel,
)
from myconfig.project_loader import build_project_definition, load_project_yaml


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ConfigEndToEndTests(unittest.TestCase):
    """Exercises the real ACCuESS config through UI binding, save, and reload flows."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])
        cls._accuess_path = Path(__file__).resolve().parents[1] / "project_configs" / "ACCuESS.yaml"

    def test_real_accuess_field_by_field_round_trip_through_ui_save_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            bridge = self._build_bridge(config_path)
            editor_model = bridge.get_config_editor_model()
            expected_scalar_count = self._count_section_scalar_fields(editor_model.sections) + 1

            panels = [ConfigSectionPanel(section) for section in editor_model.sections]
            for panel in panels:
                panel.show()
            self._app.processEvents()

            mutated_scalar_count = 0
            for panel in panels:
                mutated_scalar_count += self._mutate_panel_fields(panel)

            payload = {panel.section_key: panel.collect_value() for panel in panels}

            self.assertEqual(len(editor_model.sections), 10)
            self.assertEqual(mutated_scalar_count, expected_scalar_count)
            self.assertEqual(payload["project"]["name"], "ACCuESS_E2E_VERIFY")
            self.assertEqual(payload["project"]["display_name"], "ACCuESS E2E Verify")
            self.assertEqual(payload["project"]["config_version"], "9.9.9.91")
            self.assertEqual(payload["command list"], ["CMD_E2E_001"])

            save_result = bridge.save_config_changes(payload)
            self.assertEqual(save_result.saved_path.name, "ACCuESS_E2E_VERIFY_9.9.9.91.yaml")

            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_data, payload)
            self.assertEqual(bridge.project_config_path, save_result.saved_path.resolve())

            reloaded_model = bridge.get_config_editor_model()
            reloaded_panels = [ConfigSectionPanel(section) for section in reloaded_model.sections]
            for panel in reloaded_panels:
                panel.show()
            self._app.processEvents()
            reloaded_payload = {panel.section_key: panel.collect_value() for panel in reloaded_panels}

            self.assertEqual(reloaded_payload, payload)

    def test_partial_edit_preserves_unrelated_yaml_sections_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            original_data = load_project_yaml(config_path)
            bridge = self._build_bridge(config_path)
            payload = copy.deepcopy(bridge.raw_config)

            payload["project"]["config_version"] = "0.0.0.77"
            payload["mcu configuration"]["hardware info"] = "S32K148_SUBSET_TEST"

            save_result = bridge.save_config_changes(payload)
            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))

            expected_data = copy.deepcopy(original_data)
            expected_data["project"]["config_version"] = "0.0.0.77"
            expected_data["mcu configuration"]["hardware info"] = "S32K148_SUBSET_TEST"

            self.assertEqual(saved_data, expected_data)

    def test_canceling_version_update_flow_leaves_files_and_active_path_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            bridge = self._build_bridge(config_path)
            initial_files = sorted(path.name for path in config_path.parent.glob("*.yaml"))

            page = ProjectConfigPage(bridge, lambda _action_id: None, bridge.get_session_state("Project Config"))
            page.show()
            self._app.processEvents()

            with patch(
                "gui.workspace.pages.project_config_page.VersionChangeDialog.exec",
                return_value=QDialog.DialogCode.Rejected,
            ):
                page._handle_save_requested()
                self._app.processEvents()

            current_files = sorted(path.name for path in config_path.parent.glob("*.yaml"))
            self.assertEqual(initial_files, current_files)
            self.assertEqual(bridge.project_config_path, config_path.resolve())
            self.assertEqual(page.header_panel._message_label.text(), "Save cancelled.")

    def test_unknown_fields_round_trip_without_being_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            raw_data = load_project_yaml(config_path)
            raw_data["custom future section"] = {
                "unknown scalar": "keep me",
                "unknown list": [1, {"nested": "value"}],
            }
            raw_data["robot arm configuration"]["axes"]["ya"]["future flag"] = "enabled"
            config_path.write_text(yaml.safe_dump(raw_data, sort_keys=False), encoding="utf-8")

            bridge = self._build_bridge(config_path)
            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "0.0.0.78"
            payload["mcu configuration"]["hardware info"] = "S32K148_UNKNOWN_FIELD_TEST"

            save_result = bridge.save_config_changes(
                payload,
                requested_version="0.0.0.78",
                confirmed_new_version=True,
            )
            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))

            self.assertEqual(saved_data["custom future section"]["unknown scalar"], "keep me")
            self.assertEqual(saved_data["custom future section"]["unknown list"], [1, {"nested": "value"}])
            self.assertEqual(saved_data["robot arm configuration"]["axes"]["ya"]["future flag"], "enabled")

    def test_axis_selector_loads_missing_fw_version_and_saves_per_axis_values_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            raw_data = load_project_yaml(config_path)
            for axis_config in raw_data["robot arm configuration"]["axes"].values():
                if isinstance(axis_config, dict):
                    axis_config.pop("fw_version", None)
            config_path.write_text(yaml.safe_dump(raw_data, sort_keys=False), encoding="utf-8")

            bridge = self._build_bridge(config_path)
            editor_model = bridge.get_config_editor_model()
            robot_arm_section = next(
                section for section in editor_model.sections if section.section_key == "robot arm configuration"
            )
            panel = ConfigSectionPanel(robot_arm_section)
            panel.show()
            self._app.processEvents()

            axis_editor = next(widget for widget in panel._field_widgets if hasattr(widget, "set_current_axis"))
            axis_editor.set_current_axis("ya")
            self._app.processEvents()
            ya_fw_widget = next(
                widget for widget in axis_editor.iter_scalar_widgets() if widget._field.path[-2:] == ("ya", "fw_version")
            )
            self.assertEqual(ya_fw_widget._line_edit.text(), "")
            ya_fw_widget._line_edit.setText("0.0.1.61")

            axis_editor.set_current_axis("rp")
            self._app.processEvents()
            rp_fw_widget = next(
                widget for widget in axis_editor.iter_scalar_widgets() if widget._field.path[-2:] == ("rp", "fw_version")
            )
            rp_fw_widget._line_edit.setText("0.0.1.62")

            payload = copy.deepcopy(bridge.raw_config)
            payload["robot arm configuration"] = panel.collect_value()
            payload["project"]["config_version"] = "0.0.0.79"

            save_result = bridge.save_config_changes(
                payload,
                requested_version="0.0.0.79",
                confirmed_new_version=True,
            )
            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))

            self.assertEqual(saved_data["robot arm configuration"]["axes"]["ya"]["fw_version"], "0.0.1.61")
            self.assertEqual(saved_data["robot arm configuration"]["axes"]["rp"]["fw_version"], "0.0.1.62")
            self.assertIsNone(saved_data["robot arm configuration"]["axes"]["yb"]["fw_version"])

    def test_axis_fw_version_invalid_value_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            bridge = self._build_bridge(config_path)
            payload = copy.deepcopy(bridge.raw_config)
            payload["robot arm configuration"]["axes"]["ya"]["fw_version"] = "bad version"
            payload["project"]["config_version"] = "0.0.0.80"

            with self.assertRaisesRegex(ValueError, "ya.fw_version must use digits separated by dots"):
                bridge.save_config_changes(
                    payload,
                    requested_version="0.0.0.80",
                    confirmed_new_version=True,
                )

    def test_legacy_project_config_shape_loads_saves_and_reloads_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "project_configs"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "legacy_demo.yaml"
            config_path.write_text(
                """
project:
  name: legacy_demo
  display_name: Legacy Demo
  config_version: 1.0
system:
  axes: 2
features:
  firmware_tools: true
ui:
  workspace: phase2_shell
mcu:
  serial_port:
    name: COM9
    baudrate: 230400
  firmware_version: 1.2.3
robot:
  axes:
    x:
      node_id: 3
      node_type: 1
    y:
      node_id: 4
      node_type: 1
""".strip(),
                encoding="utf-8",
            )

            bridge = self._build_bridge(config_path)
            editor_model = bridge.get_config_editor_model()
            section_keys = [section.section_key for section in editor_model.sections]
            self.assertIn("system", section_keys)
            self.assertIn("mcu", section_keys)
            self.assertIn("robot", section_keys)

            payload = copy.deepcopy(bridge.raw_config)
            payload["project"]["config_version"] = "1.0.1"
            payload["mcu"]["serial_port"]["name"] = "COM10"

            save_result = bridge.save_config_changes(
                payload,
                requested_version="1.0.1",
                confirmed_new_version=True,
            )
            reloaded_data = bridge.raw_config

            self.assertEqual(save_result.saved_path.name, "legacy_demo_1.0.1.yaml")
            self.assertEqual(reloaded_data["mcu"]["serial_port"]["name"], "COM10")
            self.assertEqual(reloaded_data["project"]["config_version"], "1.0.1")

    def test_project_config_page_loads_with_missing_optional_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "project_configs"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "minimal.yaml"
            config_path.write_text(
                """
project:
  name: minimal
  display_name: Minimal
  config_version: 1.0.0
""".strip(),
                encoding="utf-8",
            )

            bridge = self._build_bridge(config_path)
            page = ProjectConfigPage(bridge, lambda _action_id: None, bridge.get_session_state("Project Config"))
            page.show()
            self._app.processEvents()

            self.assertIsNotNone(page._editor_model)
            self.assertEqual(len(page._section_panels), 1)
            self.assertFalse(page._error_label.isVisible())

    def test_project_config_page_loads_with_malformed_optional_sections_and_shows_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "project_configs"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "weird.yaml"
            config_path.write_text(
                """
project:
  name: weird
  display_name: Weird
  config_version: 1.0.0
features: bad
ui: 123
serial_port: COM11
robot arm configuration: unexpected
""".strip(),
                encoding="utf-8",
            )

            bridge = self._build_bridge(config_path)
            page = ProjectConfigPage(bridge, lambda _action_id: None, bridge.get_session_state("Project Config"))
            page.show()
            self._app.processEvents()

            self.assertIsNotNone(page._editor_model)
            self.assertFalse(page._error_label.isVisible())
            self.assertGreaterEqual(len(page._section_panels), 4)
            self.assertTrue(page.header_panel._issue_label.isVisible())
            self.assertIn("Optional section 'features' is malformed", page.header_panel._issue_label.text())

    def test_reveal_failure_updates_page_message_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = self._copy_real_config(temp_dir, "ACCuESS.yaml")
            bridge = self._build_bridge(config_path)
            missing_path = config_path.parent / "missing.yaml"
            bridge._config_reader._active_path = missing_path
            page = ProjectConfigPage(bridge, lambda _action_id: None, bridge.get_session_state("Project Config"))

            with patch("gui.workspace.pages.project_config_page.QMessageBox.warning") as warning:
                page._handle_reveal_requested()

            warning.assert_called_once()
            self.assertIn("does not exist", page.header_panel._message_label.text())

    def _build_bridge(self, config_path: Path) -> WorkspaceRuntimeBridge:
        raw_config = load_project_yaml(config_path)
        project = build_project_definition(raw_config, config_path)
        return WorkspaceRuntimeBridge(project)

    def _copy_real_config(self, temp_dir: str, target_name: str) -> Path:
        config_dir = Path(temp_dir) / "project_configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        target_path = config_dir / target_name
        shutil.copy2(self._accuess_path, target_path)
        return target_path

    def _mutate_panel_fields(self, panel: ConfigSectionPanel) -> int:
        if panel.section_key == "command list":
            return self._mutate_command_list(panel)

        count = 0
        for widget in self._iter_scalar_widgets_in_panel(panel):
            self._set_scalar_widget_value(widget)
            count += 1
        return count

    def _mutate_command_list(self, panel: ConfigSectionPanel) -> int:
        list_editor = panel._list_editor
        assert list_editor is not None

        add_button = next(button for button in list_editor.findChildren(type(list_editor._add_button)) if button.text() == "Add Command")
        add_button.click()
        self._app.processEvents()

        item_cards = list_editor.findChildren(ConfigListItemCard)
        self.assertEqual(len(item_cards), 1)

        scalar_widgets = list(self._iter_scalar_widgets_from_item_card(item_cards[0]))
        self.assertEqual(len(scalar_widgets), 1)
        self._set_scalar_widget_value(scalar_widgets[0], override_value="CMD_E2E_001")
        return 1

    def _iter_scalar_widgets_in_panel(self, panel: ConfigSectionPanel):
        if panel._list_editor is not None:
            for item_card in panel._list_editor._item_cards:
                yield from self._iter_scalar_widgets_from_item_card(item_card)
            return
        for widget in panel._field_widgets:
            if hasattr(widget, "iter_scalar_widgets"):
                yield from widget.iter_scalar_widgets()
                continue
            yield from self._iter_scalar_widgets(widget)

    def _iter_scalar_widgets_from_item_card(self, item_card: ConfigListItemCard):
        if item_card._single_widget is not None:
            yield from self._iter_scalar_widgets(item_card._single_widget)
        for widget in item_card._content_widgets:
            yield from self._iter_scalar_widgets(widget)

    def _iter_scalar_widgets(self, widget: ConfigFieldWidget):
        if widget._field.value_type in {"mapping", "list"}:
            for child in widget._children:
                yield from self._iter_scalar_widgets(child)
            return
        yield widget

    def _set_scalar_widget_value(self, widget: ConfigFieldWidget, override_value: object | None = None) -> None:
        path = widget._field.path
        value_type = widget._field.value_type
        current_value = widget._field.value
        target_value = override_value
        if target_value is None:
            target_value = self._build_test_value(path, value_type, current_value)

        if widget._checkbox is not None:
            widget._checkbox.setChecked(bool(target_value))
        else:
            widget._line_edit.setText("" if target_value is None else str(target_value))
        self._app.processEvents()

    def _build_test_value(self, path: tuple[str | int, ...], value_type: str, current_value: object):
        key = "_".join(str(part) for part in path)
        numeric_index = sum(ord(character) for character in key) % 900

        special_values = {
            ("project", "name"): "ACCuESS_E2E_VERIFY",
            ("project", "display_name"): "ACCuESS E2E Verify",
            ("project", "config_version"): "9.9.9.91",
            ("ui", "workspace"): "main_window_e2e",
            ("ui", "notes"): "End-to-end verification notes",
        }
        if path in special_values:
            return special_values[path]

        if value_type == "bool":
            return not bool(current_value)
        if value_type == "int":
            return 1000 + numeric_index
        if value_type == "float":
            return round(1000.5 + numeric_index, 4)
        if value_type == "version":
            return f"1.0.{numeric_index // 100}.{numeric_index % 100}"
        if value_type == "null":
            return f"null_set_{key}"
        return f"value_set_{key}"

    def _count_section_scalar_fields(self, sections) -> int:
        total = 0
        for section in sections:
            for field in section.fields:
                total += self._count_field_scalars(field)
        return total

    def _count_field_scalars(self, field) -> int:
        if field.value_type in {"mapping", "list"}:
            return sum(self._count_field_scalars(child) for child in field.children)
        return 1


if __name__ == "__main__":
    unittest.main()
