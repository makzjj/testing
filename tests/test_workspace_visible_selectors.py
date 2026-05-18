"""UI tests that protect the visible-selector interaction pattern."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton, QSizePolicy

from gui.program_selector_window import ProgramSelectorWindow
from gui.workspace.constants import ROUTE_FIRMWARE, ROUTE_PROJECT_CONFIG, ROUTE_RUNTIME
from gui.workspace.models import SelectionField, SelectionOption
from gui.workspace.shell.project_workspace_window import ProjectWorkspaceWindow
from gui.workspace.widgets import NavigationButton, NavigationPanel, SelectorFieldGrid, VisibleSelector, WorkspaceTopBar
from myconfig import project_loader
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class WorkspaceVisibleSelectorTests(unittest.TestCase):
    """Verifies that workspace selections stay visible instead of hiding behind dropdowns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_workspace_uses_visible_selectors_instead_of_dropdowns(self) -> None:
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
  mechanical_tools: true
  application_tools: true
ui:
  workspace: phase2_shell
robot:
  axes:
    x:
      node_id: 3
    y:
      node_id: 11
    z:
      node_id: 14
mcu:
  serial_port:
    name: COM11
    baudrate: 115200
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                system_axes=4,
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()

            shell_dropdowns = [combo for combo in window.findChildren(QComboBox) if combo.isVisible()]
            self.assertTrue(all(combo.objectName() == "AxisSelectorCombo" for combo in shell_dropdowns))
            self.assertGreater(len(window.findChildren(VisibleSelector)), 0)

    def test_workspace_shell_uses_top_toolbar_and_settings_menu(self) -> None:
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
  mechanical_tools: true
  application_tools: true
ui:
  workspace: phase2_shell
robot:
  axes:
    x:
      node_id: 3
    y:
      node_id: 11
    z:
      node_id: 14
mcu:
  serial_port:
    name: COM11
    baudrate: 115200
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                system_axes=4,
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()

            self.assertIsNone(window.findChild(NavigationPanel))
            self.assertEqual(window.page_stack.count(), 5)

            toolbar = window.findChild(WorkspaceTopBar)
            self.assertIsNotNone(toolbar)

            nav_labels = [button.text() for button in toolbar.findChildren(NavigationButton)]
            self.assertEqual(nav_labels, ["Firmware", "Mechanical", "Application", "Runtime", "Project Config"])

            menu_labels = [action.text() for action in toolbar.settings_menu.actions() if action.isEnabled()]
            self.assertEqual(toolbar.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Maximum)
            self.assertLessEqual(toolbar.height(), 44)
            self.assertEqual(toolbar.settings_button.text(), "")
            self.assertEqual(toolbar.settings_button.toolTip(), "Settings")
            self.assertIn("Open runtime", menu_labels)
            self.assertIn("Refresh shell", menu_labels)
            self.assertEqual(window.live_session_panel.parentWidget().objectName(), "RightColumn")
            self.assertEqual(len(window.live_session_panel.findChildren(QPushButton)), 0)
            self.assertLess(window.console_panel.geometry().top(), window.live_session_panel.geometry().top())
            self.assertGreaterEqual(toolbar.findChildren(NavigationButton)[0].height(), 30)
            self.assertEqual(window._current_route_id, ROUTE_FIRMWARE)
            self.assertEqual(window.live_session_panel.page_value.text(), "Firmware")
            self.assertFalse(window._bridge.has_live_runtime)

    def test_workspace_open_does_not_create_runtime_until_runtime_page_is_requested(self) -> None:
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
  mechanical_tools: true
  application_tools: true
ui:
  workspace: phase2_shell
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                system_axes=4,
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()

            self.assertFalse(window._bridge.has_live_runtime)

            window.set_active_page(ROUTE_RUNTIME)
            self._app.processEvents()

            self.assertTrue(window._bridge.has_live_runtime)

    def test_project_config_reload_enables_feature_gated_navigation_from_current_editor_state(self) -> None:
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
  application_tools: true
ui:
  workspace: phase2_shell
""".strip(),
                encoding="utf-8",
            )

            project = ProjectDefinition(
                name="demo",
                display_name="Demo",
                config_path=config_path,
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=False, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()
            window.set_active_page(ROUTE_PROJECT_CONFIG)
            self._app.processEvents()

            project_page = window._pages[ROUTE_PROJECT_CONFIG]
            features_panel = next(panel for panel in project_page._section_panels if panel.section_key == "features")
            mechanical_widget = next(
                widget
                for widget in features_panel._field_widgets
                if getattr(widget, "_field", None) is not None and widget._field.path[-1] == "mechanical_tools"
            )

            self.assertFalse(window.top_bar.findChildren(NavigationButton)[1].isEnabled())

            mechanical_widget._checkbox.setChecked(True)
            project_page.header_panel._reload_button.click()
            self._app.processEvents()

            mechanical_button = next(
                button for button in window.top_bar.findChildren(NavigationButton) if button.text() == "Mechanical"
            )
            self.assertTrue(mechanical_button.isEnabled())
            self.assertTrue(window._bridge.project_definition.features.mechanical_tools)

    def test_selector_field_grid_balances_list_heights_within_one_row(self) -> None:
        selector_grid = SelectorFieldGrid(
            [
                [
                    SelectionField(
                        "Command",
                        [
                            SelectionOption("Node ID", "GET_NODE_ID"),
                            SelectionOption("UUID", "GET_UUID"),
                            SelectionOption("Version", "READ_VERSION"),
                        ],
                        style="list",
                    ),
                    SelectionField(
                        "Target",
                        [
                            SelectionOption("All", "broadcast"),
                            SelectionOption("YA N3", "ya"),
                        ],
                        style="list",
                    ),
                ]
            ]
        )

        selector_grid.show()
        self._app.processEvents()

        selectors = selector_grid.findChildren(VisibleSelector)
        self.assertEqual(len(selectors), 2)
        self.assertEqual(selectors[0].height(), selectors[1].height())

    def test_program_selector_window_loads_real_project_configs_without_crashing(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            shutil.copy2(repo_root / "project_configs" / "ACCuESS.yaml", config_dir / "ACCuESS.yaml")
            shutil.copy2(repo_root / "project_configs" / "ML2.0.yaml", config_dir / "ML2.0.yaml")

            with patch.object(project_loader, "PROJECT_CONFIG_DIR", config_dir):
                window = ProgramSelectorWindow()
                window.show()
                self._app.processEvents()

            displayed_projects = [
                window.project_list.item(index).text()
                for index in range(window.project_list.count())
                if window.project_list.item(index).data(Qt.ItemDataRole.UserRole) is not None
            ]

            self.assertIn("ACCuESS", displayed_projects)
            self.assertIn("ML2.0", displayed_projects)
            self.assertTrue(window.open_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
