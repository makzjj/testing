"""Application / Production page implementation."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal

from ..bridges import WorkspaceRuntimeBridge
from ..sections.application import (
    ControllerProfileSection,
    IntegrationChecklistSection,
    TestRunSetupSection,
)
from .base_page import BaseWorkspacePage


class ApplicationProductionPage(BaseWorkspacePage):
    """Focused application / production workspace page."""

    action_requested = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Application", "Integration flows, presets, and run setup.")
        self.integration_section = IntegrationChecklistSection(bridge)
        self.controller_profile_section = ControllerProfileSection(bridge)
        self.test_run_section = TestRunSetupSection(bridge)
        self.test_run_section.action_requested.connect(self.action_requested.emit)

        self.add_row(self.integration_section, self.controller_profile_section)
        self.add_full_width(self.test_run_section)

    def refresh(self) -> None:
        self.integration_section.refresh()
        self.controller_profile_section.refresh()
        self.test_run_section.refresh()
