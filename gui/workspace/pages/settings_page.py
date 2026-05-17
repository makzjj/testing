"""Settings page implementation."""

from __future__ import annotations

from collections.abc import Callable

from ..bridges import WorkspaceRuntimeBridge
from ..sections.settings import (
    BenchDefaultsSection,
    ConfigurationActionsSection,
    EnabledToolsSection,
    ProjectMetadataSection,
)
from .base_page import BaseWorkspacePage


class SettingsPage(BaseWorkspacePage):
    """Settings and project-context page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge, action_handler: Callable[[str], None]) -> None:
        super().__init__("Settings", "Project defaults, enabled areas, and bench actions.")
        self.metadata_section = ProjectMetadataSection(bridge)
        self.enabled_tools_section = EnabledToolsSection(bridge)
        self.bench_defaults_section = BenchDefaultsSection(bridge)
        self.configuration_actions_section = ConfigurationActionsSection(bridge)

        self.configuration_actions_section.action_requested.connect(action_handler)

        self.add_row(self.metadata_section, self.enabled_tools_section)
        self.add_row(self.bench_defaults_section, self.configuration_actions_section)

    def refresh(self) -> None:
        self.metadata_section.refresh()
        self.enabled_tools_section.refresh()
        self.bench_defaults_section.refresh()
        self.configuration_actions_section.refresh()
