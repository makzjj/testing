"""Firmware page implementation."""

from __future__ import annotations

from ..bridges import WorkspaceRuntimeBridge
from ..sections.firmware import (
    CommandDebugSection,
    FrameLossSection,
    MotionCommandSection,
    SensorSnapshotSection,
    UartProtocolSection,
)
from .base_page import BaseWorkspacePage


class FirmwarePage(BaseWorkspacePage):
    """Focused firmware workspace page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Firmware", "Command, protocol, and sensor tools.")
        self.command_section = CommandDebugSection(bridge)
        self.protocol_section = UartProtocolSection(bridge)
        self.frame_loss_section = FrameLossSection(bridge)
        self.motion_section = MotionCommandSection(bridge)
        self.sensor_section = SensorSnapshotSection(bridge)

        self.add_row(self.command_section, self.protocol_section)
        self.add_row(self.frame_loss_section, self.motion_section)
        self.add_full_width(self.sensor_section)

    def refresh(self) -> None:
        self.command_section.refresh()
        self.protocol_section.refresh()
        self.frame_loss_section.refresh()
        self.motion_section.refresh()
        self.sensor_section.refresh()
