"""Focused tests for the global workspace Session panel and Production metadata flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication, QDialog, QLabel

from gui.workspace.models import SessionState
from gui.workspace.pages.production_page import ProductionPage
from gui.workspace.shell.project_workspace_window import ProjectWorkspaceWindow
from gui.workspace.constants import ROUTE_PRODUCTION, ROUTE_PROJECT_CONFIG
from gui.workspace.widgets import LiveSessionPanel
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig

try:
    from openpyxl import Workbook

    _HAS_OPENPYXL = True
except ImportError:  # pragma: no cover - environment dependent.
    _HAS_OPENPYXL = False

class _FakeBridge:
    def __init__(self) -> None:
        self._project_definition = ProjectDefinition(
            name="demo",
            display_name="Demo",
            config_path=Path("demo.yaml"),
        )

    @property
    def project_definition(self) -> ProjectDefinition:
        return self._project_definition

    @property
    def project_config_path(self) -> Path:
        return self._project_definition.config_path

    def get_runtime_communication_model(self, *, create_if_missing: bool = False) -> dict:
        return {"connected": False, "ports": [], "selected_port": "", "baud_rates": ["115200"], "selected_baud": "115200"}

    def get_runtime_robot_nodes(self, *, create_if_missing: bool = False) -> dict:
        return {"connected_nodes": [], "rows": []}

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return None

    def get_session_state(self, active_page: str) -> SessionState:
        return SessionState(
            project_name="Demo",
            connection_text="Offline",
            session_text="Preview mode",
            active_page=active_page,
            metadata_edit_enabled=False,
        )

    def get_boot_messages(self) -> list[str]:
        return []


class WorkspaceSessionPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_live_session_panel_shows_operator_assembler_page_and_edit_button(self) -> None:
        panel = LiveSessionPanel()
        state = SessionState(
            project_name="Demo",
            connection_text="Workbook loaded",
            session_text="Metadata ready",
            active_page="Production",
            operator_name="Alice",
            assembler_name="Bob",
            metadata_edit_enabled=True,
        )

        panel.update_state(state)

        self.assertEqual(panel.operator_value.text(), "Alice")
        self.assertEqual(panel.assembler_value.text(), "Bob")
        self.assertEqual(panel.page_value.text(), "Production")
        self.assertTrue(panel.edit_button.isEnabled())
        self.assertEqual(panel.findChild(QLabel, "LiveSessionTitle").text(), "Session")

    def test_workspace_session_edit_button_routes_to_active_production_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
features:
  firmware_tools: true
ui:
  workspace: phase2_shell
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

            production_state = SessionState(
                project_name="Demo",
                connection_text="Workbook loaded",
                session_text="Metadata ready",
                active_page="Production",
                operator_name="Alice",
                assembler_name="Bob",
                metadata_edit_enabled=True,
            )
            edit_calls: list[ProductionPage] = []

            def _build_session_state(self: ProductionPage) -> SessionState:
                return production_state

            def _handle_session_metadata_edit_requested(self: ProductionPage) -> bool:
                edit_calls.append(self)
                return True

            with patch.object(ProductionPage, "build_session_state", _build_session_state), patch.object(
                ProductionPage,
                "handle_session_metadata_edit_requested",
                _handle_session_metadata_edit_requested,
            ):
                window = ProjectWorkspaceWindow(project)
                window.set_active_page(ROUTE_PRODUCTION, log_route_change=False)
                self.assertTrue(window.live_session_panel.edit_button.isEnabled())
                window.live_session_panel.edit_button.click()
                self._app.processEvents()

                self.assertEqual(len(edit_calls), 1)
                self.assertIsInstance(edit_calls[0], ProductionPage)

                window.set_active_page(ROUTE_PROJECT_CONFIG, log_route_change=False)
                self._app.processEvents()
                self.assertFalse(window.live_session_panel.edit_button.isEnabled())

                window.set_active_page(ROUTE_PRODUCTION, log_route_change=False)
                self._app.processEvents()
                self.assertTrue(window.live_session_panel.edit_button.isEnabled())

    @unittest.skipUnless(_HAS_OPENPYXL, "openpyxl is required for workbook metadata tests.")
    def test_production_page_load_prompts_and_saves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "demo.yaml"
            config_path.write_text(
                """
project:
  name: demo
  display_name: Demo
features:
  firmware_tools: true
ui:
  workspace: phase2_shell
""".strip(),
                encoding="utf-8",
            )
            workbook_path = Path(tmpdir) / "ipqc.xlsx"
            workbook = Workbook()
            summary = workbook.active
            summary.title = "3X"
            summary["A1"] = "Programming"
            summary["A3"] = "Operator"
            summary["A4"] = "UUID"
            summary["A5"] = "PWM"
            summary["B4"] = "1223303010"
            summary["B5"] = "100"
            workbook.create_sheet("3X_D")
            workbook.create_sheet("3X_A")
            workbook.save(workbook_path)

            page = ProductionPage(_FakeBridge())

            with patch("gui.workspace.pages.production_page.QFileDialog.getOpenFileName", return_value=(str(workbook_path), "Excel Files (*.xlsx)")), patch(
                "gui.workspace.pages.production_page.ProductionMetadataDialog.exec",
                return_value=QDialog.DialogCode.Accepted,
            ), patch(
                "gui.workspace.pages.production_page.ProductionMetadataDialog.metadata_values",
                return_value=("Operator A", "Assembler A"),
            ):
                page._handle_load_ipqc_workbook()
                self._app.processEvents()

            metadata = page._ipqc_excel_adapter.read_production_metadata()
            self.assertEqual(metadata.operator_name, "Operator A")
            self.assertEqual(metadata.assembler_name, "Assembler A")


if __name__ == "__main__":
    unittest.main()
