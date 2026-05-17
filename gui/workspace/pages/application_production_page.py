"""Application / Production page implementation."""

from __future__ import annotations

from ..bridges import WorkspaceRuntimeBridge
from ..sections.application import (
    ControllerProfileSection,
    IntegrationChecklistSection,
    TestRunSetupSection,
)
from .base_page import BaseWorkspacePage


class ApplicationProductionPage(BaseWorkspacePage):
    """Focused application / production workspace page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Application", "Integration flows, presets, and run setup.")
        self.integration_section = IntegrationChecklistSection(bridge)
        self.controller_profile_section = ControllerProfileSection(bridge)
        self.test_run_section = TestRunSetupSection(bridge)

        self.add_row(self.integration_section, self.controller_profile_section)
        self.add_full_width(self.test_run_section)

    def refresh(self) -> None:
        self.integration_section.refresh()
        self.controller_profile_section.refresh()
        self.test_run_section.refresh()
