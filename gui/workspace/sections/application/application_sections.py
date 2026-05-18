"""Section widgets used by the Application page."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QProgressBar

from ...bridges import WorkspaceRuntimeBridge
from ...models import DetailItem, SelectionField, SelectionOption
from ...widgets import ChipGroupWidget, DetailListWidget, LabeledControl, PanelFrame, SelectorFieldGrid, StatusListWidget, VisibleSelector
from ...widgets.layout_utils import clear_layout
from ..section_utils import build_grid_layout


class IntegrationChecklistSection(PanelFrame):
    """Integration checklist module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Integration checklist", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        self.body_layout.addWidget(
            StatusListWidget(
                [
                    ("Serial connection", "success"),
                    ("MCU version query", "success"),
                    ("Node identity validation", "success"),
                    ("Robot HMI handshake", "warning"),
                    ("Motion profile validation", "warning"),
                    ("Final report export", "muted"),
                ]
            )
        )


class ControllerProfileSection(PanelFrame):
    """Controller profile module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Controller profile", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        detail_map = {item.label: item.value for item in self._bridge.get_controller_profile_items()}

        grid = build_grid_layout()

        selector_fields = [
            [
                SelectionField(
                    "Profile",
                    [
                        SelectionOption(
                            f"{self._bridge.project_definition.display_name}_Default_v2",
                            f"{self._bridge.project_definition.display_name}_Default_v2",
                            "Balanced default controller profile",
                        ),
                        SelectionOption(
                            f"{self._bridge.project_definition.display_name}_Quick",
                            f"{self._bridge.project_definition.display_name}_Quick",
                            "Fast setup for quick validation",
                        ),
                    ],
                    style="list",
                ),
            ],
            [
                SelectionField(
                    "Motion preset",
                    [
                        SelectionOption("Velocity 20", "Velocity 20", "Lower-speed calibration preset"),
                        SelectionOption("Velocity 40", "Velocity 40", "Higher-speed validation preset"),
                    ],
                    style="segmented",
                    columns=2,
                ),
            ],
            [
                SelectionField(
                    "Retry policy",
                    [
                        SelectionOption("1 retry", "1 retry", "Quick recovery"),
                        SelectionOption("2 retries", "2 retries", "Safer re-run window"),
                    ],
                    style="segmented",
                    columns=2,
                ),
            ],
        ]
        grid.addWidget(SelectorFieldGrid(selector_fields), 0, 0, 3, 2)
        self.body_layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        load_button = QPushButton("Load")
        load_button.setProperty("tone", "secondary")
        actions.addWidget(load_button)

        save_button = QPushButton("Save")
        save_button.setProperty("tone", "primary")
        actions.addWidget(save_button)
        self.body_layout.addLayout(actions)

        self.body_layout.addWidget(
            ChipGroupWidget(
                [
                    (detail_map.get("Project config version", "v1"), "info"),
                    (detail_map.get("Bench workspace tag", "main_window"), "muted"),
                    (detail_map.get("Configured serial path", "COM11"), "warning"),
                ],
                columns=3,
            )
        )


class TestRunSetupSection(PanelFrame):
    """Test run setup module."""

    action_requested = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Test run setup", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        items = {item.label: item.value for item in self._bridge.get_test_run_setup_items()}

        header_chips = ChipGroupWidget([("Integration", "info"), ("Bench ready", "success"), ("Phase 2", "muted")], columns=3)
        self.body_layout.addWidget(header_chips)

        form = build_grid_layout()

        operator = QLineEdit("Y. Wang")
        form.addWidget(
            LabeledControl(
                "Run type",
                VisibleSelector(
                    [
                        SelectionOption("Integration", "Integration", "End-to-end bench validation"),
                        SelectionOption("Regression", "Regression", "Repeat baseline verification"),
                    ],
                    style="segmented",
                    columns=2,
                ),
            ),
            0,
            0,
        )
        form.addWidget(LabeledControl("Operator", operator), 0, 1)
        form.addWidget(
            LabeledControl(
                "Report",
                VisibleSelector(
                    [
                        SelectionOption("JSON + CSV", "JSON + CSV", "Structured and spreadsheet output"),
                        SelectionOption("JSON only", "JSON only", "Structured export only"),
                    ],
                    style="segmented",
                    columns=2,
                ),
            ),
            0,
            2,
        )
        self.body_layout.addLayout(form)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        for label in ("Open runtime", "Export report", "Stop all"):
            button = QPushButton(label)
            button.setProperty("tone", "secondary")
            if label == "Open runtime":
                button.clicked.connect(lambda: self.action_requested.emit("open_legacy_runtime"))
            actions.addWidget(button)

        actions.addStretch(1)

        start_button = QPushButton("Start")
        start_button.setProperty("tone", "primary")
        actions.addWidget(start_button)
        self.body_layout.addLayout(actions)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(64)
        self.body_layout.addWidget(progress)

        self.body_layout.addWidget(
            DetailListWidget(
                [
                    DetailItem("Project", items.get("Project display name", "n/a")),
                    DetailItem("Axis count", items.get("Axis count", "n/a")),
                    DetailItem("Runtime handoff", items.get("Runtime handoff", "n/a")),
                ]
            )
        )
