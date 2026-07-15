"""UI tests that protect the visible-selector interaction pattern."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QSizePolicy

from gui.program_selector_window import ProgramSelectorWindow
from gui.workspace.constants import ROUTE_APPLICATION, ROUTE_FIRMWARE, ROUTE_PRODUCTION, ROUTE_PROJECT_CONFIG, ROUTE_RUNTIME
from gui.workspace.models import SelectionField, SelectionOption
from gui.workspace.pages.application_production_page import PlotsPage
from gui.workspace.shell.project_workspace_window import ProjectWorkspaceWindow
from gui.workspace.widgets import NavigationButton, NavigationPanel, SelectorFieldGrid, VisibleSelector, WorkspaceTopBar
from myconfig import project_loader
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
LEGACY_ACCUESS_NODE_NAMES = ["Ya", "Yb", "Nd", "Rs", "Rp", "Rn"]


class _FakePlotsBackendClient:
    def __init__(self) -> None:
        self.sent_commands: list[tuple[int, list[int]]] = []
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def send_command_bytes(self, node_id: int, payload: list[int]) -> bytearray:
        self.sent_commands.append((int(node_id), list(payload)))
        return bytearray(payload)


class _FakePlotsRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.backend_client = _FakePlotsBackendClient()


class _FakePlotsBridge:
    def __init__(self) -> None:
        self._runtime_window = _FakePlotsRuntimeWindow()
        self._series_by_node: dict[int, list[dict[str, object]]] = {}

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self._runtime_window

    def get_plot_node_options(self, *, create_if_missing: bool = False):
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

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        connected = self._runtime_window.backend_client.is_connected()
        return connected, connected

    def get_runtime_node_motor_current(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        series = self._series_by_node.get(int(node_id), [])
        if not series:
            return {"node_id": int(node_id), "current_mA": None, "current_A": None, "sample_count": 0, "last_updated": None}
        latest = series[-1]
        current_mA = int(latest["current_mA"])
        return {
            "node_id": int(node_id),
            "current_mA": current_mA,
            "current_A": current_mA / 1000.0,
            "sample_count": len(series),
            "last_updated": latest["index"],
        }

    def get_runtime_node_motor_current_series(self, node_id: int, *, create_if_missing: bool = False) -> list[dict[str, object]]:
        return [dict(sample) for sample in self._series_by_node.get(int(node_id), [])]


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

            # Hidden combo boxes may exist inside composite visible selectors; assert only on rendered dropdowns.
            shell_dropdowns = [combo for combo in window.findChildren(QComboBox) if combo.isVisible()]
            self.assertGreaterEqual(len(shell_dropdowns), 1)
            allowed_names = {"AxisSelectorCombo", "ProductionCommPortCombo", "ProductionCommBaudCombo"}
            self.assertTrue(all(combo.objectName() in allowed_names for combo in shell_dropdowns))

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
            self.assertEqual(window.page_stack.count(), 6)

            toolbar = window.findChild(WorkspaceTopBar)
            self.assertIsNotNone(toolbar)

            nav_labels = [button.text() for button in toolbar.findChildren(NavigationButton)]
            self.assertEqual(nav_labels, ["Production", "Firmware", "Mechanical", "Plots", "Runtime", "Project Config"])
            self.assertNotIn("Application", nav_labels)

            menu_labels = [action.text() for action in toolbar.settings_menu.actions() if action.isEnabled()]
            self.assertEqual(toolbar.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Maximum)
            self.assertLessEqual(toolbar.height(), 44)
            self.assertEqual(toolbar.settings_button.text(), "")
            self.assertEqual(toolbar.settings_button.toolTip(), "Settings")
            self.assertIn("Open runtime", menu_labels)
            self.assertIn("Refresh shell", menu_labels)
            self.assertEqual(window.live_session_panel.parentWidget().objectName(), "RightColumn")
            self.assertEqual(len(window.live_session_panel.findChildren(QPushButton)), 1)
            self.assertEqual(window.live_session_panel.findChild(QPushButton).objectName(), "SessionEditButton")
            self.assertLess(window.console_panel.geometry().top(), window.live_session_panel.geometry().top())
            self.assertGreaterEqual(toolbar.findChildren(NavigationButton)[0].height(), 30)
            self.assertEqual(window._current_route_id, ROUTE_PRODUCTION)
            self.assertEqual(window.live_session_panel.page_value.text(), "Production")
            self.assertFalse(window._bridge.has_live_runtime)

    def test_plots_page_opens_motor_current_dialog_without_sending_commands(self) -> None:
        bridge = _FakePlotsBridge()
        runtime_window = bridge.get_runtime_window()
        receiver_count_before = runtime_window.receivers(runtime_window.packet_received)
        page = PlotsPage(bridge)
        page.show()
        self._app.processEvents()

        self.assertEqual(page.motor_current_button.text(), "Open Motor Current Plot")
        self.assertEqual(page.motor_torque_button.text(), "Motor Torque")
        self.assertEqual(page.motor_speed_button.text(), "Motor Speed")
        self.assertEqual(page.encoder_position_button.text(), "Encoder Position")
        self.assertFalse(page.motor_torque_button.isEnabled())
        self.assertFalse(page.motor_speed_button.isEnabled())
        self.assertFalse(page.encoder_position_button.isEnabled())
        self.assertFalse(hasattr(page, "node_combo"))
        self.assertFalse(hasattr(page, "placeholder_section"))
        self.assertIsNone(page.findChild(QComboBox, "PlotsNodeCombo"))
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)

        page.motor_current_button.click()
        self._app.processEvents()

        self.assertIsNotNone(page._motor_current_dialog)
        assert page._motor_current_dialog is not None
        self.assertTrue(page._motor_current_dialog.isVisible())
        self.assertFalse(page._motor_current_dialog._render_timer.isActive())
        self.assertEqual(page._motor_current_dialog.node_combo.count(), 10)
        dropdown_text = [page._motor_current_dialog.node_combo.itemText(index) for index in range(page._motor_current_dialog.node_combo.count())]
        self.assertEqual(dropdown_text[0], "Node 3 - X")
        self.assertIn("Node 4 - Y", dropdown_text)
        self.assertIn("Node 5 - V", dropdown_text)
        self.assertIn("Node 6 - H", dropdown_text)
        self.assertIn("Node 7 - NZ", dropdown_text)
        self.assertIn("Node 8 - RZ", dropdown_text)
        self.assertIn("Node 9 - PZ", dropdown_text)
        self.assertIn("Node 10 - HMI", dropdown_text)
        self.assertIn("Node 11 - NGActuator", dropdown_text)
        self.assertIn("Node 12 - Z", dropdown_text)
        self.assertNotIn("Node 7 - Node 7", dropdown_text)
        self.assertEqual(runtime_window.backend_client.sent_commands, [])
        self.assertEqual(runtime_window.receivers(runtime_window.packet_received), receiver_count_before)
        page._motor_current_dialog.close()

    def test_workspace_uses_plots_label_and_registers_plots_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
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
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()
            window.set_active_page(ROUTE_APPLICATION)
            self._app.processEvents()

            toolbar = window.findChild(WorkspaceTopBar)
            assert toolbar is not None
            nav_labels = [button.text() for button in toolbar.findChildren(NavigationButton)]
            self.assertIn("Plots", nav_labels)
            self.assertNotIn("Application", nav_labels)
            self.assertIsInstance(window._pages[ROUTE_APPLICATION], PlotsPage)

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

    def test_production_page_uses_ml20_node_map_for_table_and_dropdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
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
                features=ProjectFeatures(firmware_tools=True, mechanical_tools=True, application_tools=True),
                ui=ProjectUiConfig(workspace="phase2_shell"),
            )

            window = ProjectWorkspaceWindow(project)
            window.show()
            self._app.processEvents()
            window.set_active_page(ROUTE_PRODUCTION)
            self._app.processEvents()

            production_page = window._pages[ROUTE_PRODUCTION]
            dropdown = production_page.test_control_section._combo

            node_ids = sorted(production_page.node_status_section._led_by_node_id.keys())
            dropdown_text = [dropdown.itemText(index) for index in range(dropdown.count())]

            self.assertEqual(node_ids, list(range(2, 17)))
            self.assertIn("Node 7 - NZ", dropdown_text)
            self.assertIn("Node 11 - NGActuator", dropdown_text)
            self.assertNotIn("Node 1 - MCU Master", dropdown_text)
            node_labels = [label.text() for label in production_page.node_status_section.findChildren(QLabel)]
            self.assertFalse(any(name in node_labels for name in LEGACY_ACCUESS_NODE_NAMES))

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

            mechanical_button = next(
                (button for button in window.top_bar.findChildren(NavigationButton) if button.text() == "Mechanical"),
                None,
            )
            self.assertIsNotNone(mechanical_button)
            self.assertFalse(mechanical_button.isEnabled())

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
