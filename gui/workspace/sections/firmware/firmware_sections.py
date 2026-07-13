"""Section widgets used by the Firmware page."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton

from ...bridges import WorkspaceRuntimeBridge
from ...controllers.firmware_integration_controller import FirmwareIntegrationController
from ...models import SelectionField, SelectionOption
from ...widgets import ChipGroupWidget, DetailListWidget, LabeledControl, PanelFrame, SelectorFieldGrid, SimpleTableWidget
from ...widgets.layout_utils import clear_layout
from ..section_utils import build_grid_layout


class FirmwareIntegrationSection(PanelFrame):
    """Launcher section for Firmware Integration workflows."""

    def __init__(
        self,
        controller: FirmwareIntegrationController,
        *,
        open_manual_binary_dialog,
        open_manual_text_dialog,
        open_binary_fit_dialog,
        open_text_fit_dialog,
    ) -> None:
        super().__init__("Firmware Integration", "Manual Binary, Manual Text, and Binary FIT are available. Remaining FIT flows stay behind the controller scaffold.")
        self._controller = controller
        self._open_manual_binary_dialog = open_manual_binary_dialog
        self._open_manual_text_dialog = open_manual_text_dialog
        self._open_binary_fit_dialog = open_binary_fit_dialog
        self._open_text_fit_dialog = open_text_fit_dialog
        self._status_label: QLabel | None = None
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)

        helper = QLabel(
            "Manual Binary Command and Manual Text Command run through the Firmware Integration controller "
            "and transport adapter. Binary FIT and Text FIT now launch through configuration and report dialogs. Export behavior remains deferred."
        )
        helper.setWordWrap(True)
        helper.setObjectName("FirmwareIntegrationHelperText")
        self.body_layout.addWidget(helper)

        button_grid = QGridLayout()
        button_grid.setContentsMargins(0, 0, 0, 0)
        button_grid.setHorizontalSpacing(8)
        button_grid.setVerticalSpacing(8)

        buttons = [
            ("Manual Binary Command", "FirmwareFitManualBinaryButton", self._open_manual_binary_dialog, "primary"),
            ("Manual Text Command", "FirmwareFitManualTextButton", self._open_manual_text_dialog, "secondary"),
            ("Run Binary FIT", "FirmwareFitRunBinaryButton", self._open_binary_fit_dialog, "secondary"),
            ("Run Text FIT", "FirmwareFitRunTextButton", self._open_text_fit_dialog, "secondary"),
            ("Reports / Export", "FirmwareFitReportsButton", self._controller.open_reports, "secondary"),
        ]

        for index, (label, object_name, handler, tone) in enumerate(buttons):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setProperty("tone", tone)
            button.clicked.connect(lambda _checked=False, callback=handler: self._update_status(callback()))
            row = index // 3
            column = index % 3
            button_grid.addWidget(button, row, column)

        self.body_layout.addLayout(button_grid)

        self._status_label = QLabel(
            "Manual Binary Command, Manual Text Command, Binary FIT, and Text FIT are available. Export remains scaffold-only."
        )
        self._status_label.setWordWrap(True)
        self._status_label.setObjectName("FirmwareIntegrationStatusLabel")
        self.body_layout.addWidget(self._status_label)

    def _update_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)


class CommandDebugSection(PanelFrame):
    """Firmware command-debug module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Command debug", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        axis_nodes = _axis_node_options(self._bridge.raw_config)
        target_options = [SelectionOption("All", "Broadcast", "Send to every available node"), *axis_nodes[:3]]

        top = build_grid_layout()

        payload = QLineEdit("0x00 0x00")

        send_button = QPushButton("Send")
        send_button.setProperty("tone", "primary")

        selector_fields = [
            [
                SelectionField(
                    "Command",
                    [
                        SelectionOption("Node ID", "GET_NODE_ID", "Read the active node identifier"),
                        SelectionOption("UUID", "GET_UUID", "Fetch the MCU UUID"),
                        SelectionOption("Version", "READ_VERSION", "Read the installed firmware version"),
                    ],
                    style="list",
                ),
                SelectionField("Target", target_options, style="list"),
            ]
        ]

        top.addWidget(SelectorFieldGrid(selector_fields), 0, 0, 1, 2)
        top.addWidget(send_button, 0, 2)
        top.addWidget(LabeledControl("Payload", payload), 1, 0, 1, 3)
        self.body_layout.addLayout(top)

        self.body_layout.addWidget(ChipGroupWidget([("Binary mode", "info"), ("Text mode", "warning")], columns=2))

        log_list = QListWidget()
        log_list.setObjectName("CommandLogList")
        log_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log_list.setWordWrap(True)
        log_list.addItems(
            [
                "[TX] 0x7E 0x04 0x10",
                f"[RX] {axis_nodes[0].label if axis_nodes else 'Node 03'} version OK",
                f"[RX] {axis_nodes[1].label if len(axis_nodes) > 1 else 'Node 11'} UUID ready",
                "[RX] interrupt=0",
            ]
        )
        self.body_layout.addWidget(log_list)


class UartProtocolSection(PanelFrame):
    """UART protocol monitor module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("UART protocol monitor", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        axis_nodes = _axis_node_options(self._bridge.raw_config)
        rows = [
            ["13:28:01", "TX", "broadcast", "GET_NODE_ID"],
            ["13:28:02", "RX", axis_nodes[0].label if axis_nodes else "3", "MCU version OK"],
            ["13:28:04", "RX", axis_nodes[1].label if len(axis_nodes) > 1 else "11", "Interrupt=0"],
            ["13:28:06", "RX", axis_nodes[2].label if len(axis_nodes) > 2 else "14", "Range ready"],
        ]
        self.body_layout.addWidget(SimpleTableWidget(["Time", "Dir", "Node", "Summary"], rows))


class FrameLossSection(PanelFrame):
    """Frame-loss summary module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Frame loss summary", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        self.body_layout.addWidget(DetailListWidget(self._bridge.get_frame_loss_items()))


class MotionCommandSection(PanelFrame):
    """Firmware-side motion command module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Motion command panel", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        axis_nodes = _axis_node_options(self._bridge.raw_config)

        grid = build_grid_layout()

        value_edit = QLineEdit("40")

        node_options = axis_nodes[:4] or [SelectionOption("Node 03", "Node 03")]
        top_selector_fields = [
            [
                SelectionField("Node", node_options, style="list"),
                SelectionField(
                    "Control mode",
                    [
                        SelectionOption("Vel PID", "Velocity PID", "Closed-loop speed control"),
                        SelectionOption("Pos PID", "Position PID", "Closed-loop position control"),
                    ],
                    style="list",
                ),
            ]
        ]
        preset_selector_fields = [
            [
                SelectionField(
                    "Command preset",
                    [
                        SelectionOption("Set V20", "Set Velocity 20", "Low-speed validation"),
                        SelectionOption("Set V40", "Set Velocity 40", "High-speed validation"),
                    ],
                    style="list",
                ),
            ]
        ]
        grid.addWidget(SelectorFieldGrid(top_selector_fields), 0, 0, 1, 2)
        grid.addWidget(SelectorFieldGrid(preset_selector_fields), 1, 0)
        grid.addWidget(LabeledControl("Value", value_edit), 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body_layout.addLayout(grid)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        query_button = QPushButton("Query")
        query_button.setProperty("tone", "secondary")
        actions.addWidget(query_button)

        run_button = QPushButton("Run")
        run_button.setProperty("tone", "primary")
        actions.addWidget(run_button)

        stop_button = QPushButton("Stop")
        stop_button.setProperty("tone", "danger")
        actions.addWidget(stop_button)

        self.body_layout.addLayout(actions)


class SensorSnapshotSection(PanelFrame):
    """Firmware sensor snapshot module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Sensor snapshot", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        rows = []
        encoders = self._bridge.raw_config.get("robot", {}).get("encoders", {})
        for sensor_name, sensor_data in encoders.items():
            rows.append([sensor_name.upper(), str(sensor_data.get("node_id", "?")), "Ready"])
        if not rows:
            rows = [["ENCODER", "n/a", "Idle"]]
        self.body_layout.addWidget(SimpleTableWidget(["Sensor", "Node", "State"], rows))


def _axis_node_options(raw_config: dict) -> list[SelectionOption]:
    axis_options: list[SelectionOption] = []
    axes = raw_config.get("robot", {}).get("axes", {})
    if isinstance(axes, dict):
        for axis_name, axis_data in axes.items():
            node_id = axis_data.get("node_id", "?") if isinstance(axis_data, dict) else "?"
            axis_options.append(
                SelectionOption(
                    label=f"{axis_name.upper()} N{node_id}",
                    value=f"{axis_name.upper()} / Node {node_id}",
                    description=f"Direct selection for axis {axis_name.upper()} on node {node_id}",
                )
            )
    return axis_options
