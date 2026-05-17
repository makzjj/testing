"""Unit tests for workspace page registry behavior."""

from __future__ import annotations

import unittest
from pathlib import Path

from gui.workspace.constants import ROUTE_APPLICATION, ROUTE_FIRMWARE, ROUTE_MECHANICAL, ROUTE_PROJECT_CONFIG
from gui.workspace.shell.workspace_page_registry import build_navigation_items, get_route_label
from myconfig.project_models import ProjectDefinition, ProjectFeatures, ProjectUiConfig


class WorkspacePageRegistryTests(unittest.TestCase):
    """Verifies first-level navigation metadata for the Phase 2 shell."""

    def test_build_navigation_items_respects_project_feature_flags(self) -> None:
        project = ProjectDefinition(
            name="demo",
            display_name="Demo",
            config_path=Path("demo.yaml"),
            features=ProjectFeatures(
                firmware_tools=True,
                mechanical_tools=False,
                application_tools=True,
            ),
            ui=ProjectUiConfig(workspace="phase2_shell"),
        )

        items = build_navigation_items(project)
        item_map = {item.route_id: item for item in items}

        self.assertTrue(item_map[ROUTE_FIRMWARE].enabled)
        self.assertFalse(item_map[ROUTE_MECHANICAL].enabled)
        self.assertTrue(item_map[ROUTE_APPLICATION].enabled)
        self.assertEqual(get_route_label(items, ROUTE_PROJECT_CONFIG), "Project Config")


if __name__ == "__main__":
    unittest.main()
