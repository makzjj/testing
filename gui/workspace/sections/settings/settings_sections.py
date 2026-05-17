"""Section widgets used by the Settings page."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout

from ...bridges import WorkspaceRuntimeBridge
from ...models import SelectionField, SelectionOption
from ...widgets import ActionButtonStrip, PanelFrame, SelectorFieldGrid, SimpleTableWidget, StatusChip, SwitchListWidget
from ...widgets.layout_utils import clear_layout
from ..section_utils import build_grid_layout, detail_map


class ProjectMetadataSection(PanelFrame):
    """Project metadata section."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Project metadata", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        rows = [[item.label, item.value] for item in self._bridge.get_project_metadata_items()]
        self.body_layout.addWidget(SimpleTableWidget(["Field", "Value"], rows))


class EnabledToolsSection(PanelFrame):
    """Enabled tool-areas section."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Enabled areas", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        switch_rows = [(item.label, item.value == "Enabled") for item in self._bridge.get_enabled_tool_items()]
        switch_rows.insert(0, ("Overview workspace", True))
        switch_rows.append(("Settings page", True))
        self.body_layout.addWidget(SwitchListWidget(switch_rows))


class BenchDefaultsSection(PanelFrame):
    """Bench-default summary section."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Bench defaults", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        defaults = detail_map(self._bridge.get_bench_default_items())

        top_grid = build_grid_layout()

        selector_fields = [
            [
                SelectionField(
                    "Preferred COM port",
                    [
                        SelectionOption(defaults.get("Serial port", "COM11"), defaults.get("Serial port", "COM11"), "Current bench default"),
                        SelectionOption("COM9", "COM9", "Alternative bench port"),
                        SelectionOption("COM10", "COM10", "Alternative bench port"),
                    ],
                    style="list",
                ),
                SelectionField(
                    "Baud rate",
                    [
                        SelectionOption(defaults.get("Baudrate", "115200"), defaults.get("Baudrate", "115200"), "Current bench default"),
                        SelectionOption("230400", "230400", "High-throughput profile"),
                    ],
                    style="list",
                ),
            ],
            [
                SelectionField(
                    "Report export",
                    [
                        SelectionOption("JSON + CSV", "JSON + CSV", "Dual export bundle"),
                        SelectionOption("JSON only", "JSON only", "Lean structured report"),
                    ],
                    style="segmented",
                    columns=2,
                ),
            ],
        ]
        top_grid.addWidget(SelectorFieldGrid(selector_fields), 0, 0, 2, 2)
        self.body_layout.addLayout(top_grid)

        toggles = SwitchListWidget(
            [
                ("Auto node scan", True),
                ("Restore last project", True),
                ("Write trace log", False),
            ]
        )
        self.body_layout.addWidget(toggles)


class ConfigurationActionsSection(PanelFrame):
    """Settings action section."""

    action_requested = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Configuration actions", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        badges = QHBoxLayout()
        badges.setContentsMargins(0, 0, 0, 0)
        badges.setSpacing(8)
        badges.addWidget(StatusChip("YAML", "info"))
        badges.addWidget(StatusChip("Readonly shell", "muted"))
        badges.addStretch(1)
        self.body_layout.addLayout(badges)

        action_items = self._bridge.get_configuration_actions()
        actions = ActionButtonStrip(action_items, columns=1, primary_index=0)
        actions.action_requested.connect(self.action_requested.emit)
        self.body_layout.addWidget(actions)
