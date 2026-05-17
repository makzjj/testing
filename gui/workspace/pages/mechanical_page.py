"""Mechanical page implementation."""

from __future__ import annotations

from ..bridges import WorkspaceRuntimeBridge
from ..sections.mechanical import (
    AxisMotionControlSection,
    MotorBehaviourSection,
    RepeatabilitySection,
    SelectedAxisSnapshotSection,
    SensorLimitsSection,
)
from .base_page import BaseWorkspacePage


class MechanicalPage(BaseWorkspacePage):
    """Focused mechanical workspace page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Mechanical", "Motion control, repeatability, and axis context.")
        self.behaviour_section = MotorBehaviourSection(bridge)
        self.axis_control_section = AxisMotionControlSection(bridge)
        self.repeatability_section = RepeatabilitySection(bridge)
        self.sensor_limits_section = SensorLimitsSection(bridge)
        self.axis_snapshot_section = SelectedAxisSnapshotSection(bridge)

        self.add_row(self.behaviour_section, self.axis_control_section)
        self.add_row(self.repeatability_section, self.sensor_limits_section)
        self.add_full_width(self.axis_snapshot_section)

    def refresh(self) -> None:
        self.behaviour_section.refresh()
        self.axis_control_section.refresh()
        self.repeatability_section.refresh()
        self.sensor_limits_section.refresh()
        self.axis_snapshot_section.refresh()
