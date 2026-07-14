"""Section widgets used by the Firmware page."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QWidget,
)

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
        open_reports_dialog,
    ) -> None:
        super().__init__("Firmware Integration", "Manual Binary, Manual Text, Binary FIT, Text FIT, and report export are available.")
        self._controller = controller
        self._open_manual_binary_dialog = open_manual_binary_dialog
        self._open_manual_text_dialog = open_manual_text_dialog
        self._open_binary_fit_dialog = open_binary_fit_dialog
        self._open_text_fit_dialog = open_text_fit_dialog
        self._open_reports_dialog = open_reports_dialog
        self._status_label: QLabel | None = None
        self._history_output: QTextEdit | None = None
        self._manual_stack: QStackedWidget | None = None
        self._mode_combo: QComboBox | None = None
        self._text_cmd_combo: QComboBox | None = None
        self._text_param_label: QLabel | None = None
        self._text_param_input: QLineEdit | None = None
        self._send_text_button: QPushButton | None = None
        self._node_id_combo: QComboBox | None = None
        self._bin_cmd_combo: QComboBox | None = None
        self._param_stack: QStackedWidget | None = None
        self._pos_spin: QSpinBox | None = None
        self._vel_spin: QSpinBox | None = None
        self._bin_hex_input: QLineEdit | None = None
        self._raw_hex_check: QCheckBox | None = None
        self._send_binary_button: QPushButton | None = None
        self._text_definitions = tuple(controller.manual_text_command_definitions())
        self._binary_definitions = tuple(controller.manual_binary_command_definitions())
        self._controller.status_changed.connect(self._handle_status_changed)
        self._controller.pending_state_changed.connect(self._handle_pending_state_changed)
        self._controller.manual_binary_sent.connect(self._handle_manual_binary_sent)
        self._controller.manual_binary_result.connect(self._handle_manual_binary_result)
        self._controller.manual_text_sent.connect(self._handle_manual_text_sent)
        self._controller.manual_text_result.connect(self._handle_manual_text_result)
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)

        auto_layout = QHBoxLayout()
        auto_layout.setSpacing(6)

        run_binary = QPushButton("Run Binary Tests")
        run_binary.setObjectName("FirmwareFitRunBinaryButton")
        run_binary.setProperty("tone", "primary")
        run_binary.clicked.connect(lambda _checked=False: self._update_status(self._open_binary_fit_dialog()))
        auto_layout.addWidget(run_binary, alignment=Qt.AlignmentFlag.AlignVCenter)

        run_text = QPushButton("Run Text-based Tests")
        run_text.setObjectName("FirmwareFitRunTextButton")
        run_text.setProperty("tone", "primary")
        run_text.clicked.connect(lambda _checked=False: self._update_status(self._open_text_fit_dialog()))
        auto_layout.addWidget(run_text, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._diag_mode_check = QCheckBox("Diagnostic Mode")
        self._diag_mode_check.setObjectName("FirmwareFitDiagnosticModeCheck")
        self._diag_mode_check.setToolTip("Quietens background terminal printing to prioritize test logs.")
        auto_layout.addWidget(self._diag_mode_check, alignment=Qt.AlignmentFlag.AlignVCenter)

        save_location = QPushButton("Save Location")
        save_location.setObjectName("FirmwareFitReportsButton")
        save_location.setToolTip("View or change the save location for test reports and diagnostic logs.")
        save_location.clicked.connect(lambda _checked=False: self._update_status(self._open_reports_dialog()))
        auto_layout.addWidget(save_location, alignment=Qt.AlignmentFlag.AlignVCenter)
        auto_layout.addStretch()
        self.body_layout.addLayout(auto_layout)

        # Compatibility aliases for older callers; the visible legacy control is the mode combo below.
        self._manual_binary_alias_button = QPushButton("Manual Binary Command")
        self._manual_binary_alias_button.setObjectName("FirmwareFitManualBinaryButton")
        self._manual_binary_alias_button.clicked.connect(lambda _checked=False: self._update_status(self._open_manual_binary_dialog()))
        self._manual_binary_alias_button.hide()
        self.body_layout.addWidget(self._manual_binary_alias_button)
        self._manual_text_alias_button = QPushButton("Manual Text Command")
        self._manual_text_alias_button.setObjectName("FirmwareFitManualTextButton")
        self._manual_text_alias_button.clicked.connect(lambda _checked=False: self._update_status(self._open_manual_text_dialog()))
        self._manual_text_alias_button.hide()
        self.body_layout.addWidget(self._manual_text_alias_button)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Manual Testing Mode:"))
        self._mode_combo = QComboBox()
        self._mode_combo.setObjectName("FirmwareFitManualModeCombo")
        self._mode_combo.addItems(["Text Command Mode", "Binary Command Mode"])
        self._mode_combo.setMinimumWidth(180)
        mode_layout.addWidget(self._mode_combo)
        mode_layout.addStretch()
        self.body_layout.addLayout(mode_layout)

        self._manual_stack = QStackedWidget()
        self._manual_stack.addWidget(self._build_text_manual_row())
        self._manual_stack.addWidget(self._build_binary_manual_row())
        self._mode_combo.currentIndexChanged.connect(self._manual_stack.setCurrentIndex)
        self.body_layout.addWidget(self._manual_stack)

        self._status_label = QLabel("Firmware Integration Test is ready.")
        self._status_label.setWordWrap(True)
        self._status_label.setObjectName("FirmwareIntegrationStatusLabel")
        self.body_layout.addWidget(self._status_label)

        self._history_output = QTextEdit()
        self._history_output.setObjectName("FirmwareIntegrationManualHistoryOutput")
        self._history_output.setReadOnly(True)
        self._history_output.setMaximumHeight(120)
        self.body_layout.addWidget(self._history_output)

        self._sync_text_value_visibility()
        self._sync_binary_parameter_visibility()
        self._handle_pending_state_changed(self._controller.has_pending_firmware_request())

    def _update_status(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(message)

    def _build_text_manual_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Text Command:"))
        self._text_cmd_combo = QComboBox()
        self._text_cmd_combo.setObjectName("FirmwareFitTextCommandCombo")
        self._text_cmd_combo.setEditable(True)
        commands = sorted({str(definition.text_command or definition.name) for definition in self._text_definitions})
        self._text_cmd_combo.addItems(commands)
        self._text_cmd_combo.setMinimumWidth(140)
        completer = QCompleter(commands, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._text_cmd_combo.setCompleter(completer)
        self._text_cmd_combo.currentTextChanged.connect(self._sync_text_value_visibility)
        layout.addWidget(self._text_cmd_combo)

        self._text_param_label = QLabel("Value:")
        layout.addWidget(self._text_param_label)

        self._text_param_input = QLineEdit()
        self._text_param_input.setObjectName("FirmwareFitTextValueInput")
        self._text_param_input.setPlaceholderText("Enter parameter...")
        self._text_param_input.setMaximumWidth(120)
        layout.addWidget(self._text_param_input)

        self._send_text_button = QPushButton("Send Text")
        self._send_text_button.setObjectName("FirmwareFitSendTextButton")
        self._send_text_button.setProperty("tone", "primary")
        self._send_text_button.clicked.connect(self._send_manual_text)
        layout.addWidget(self._send_text_button)
        layout.addStretch()
        return widget

    def _build_binary_manual_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Node ID:"))
        self._node_id_combo = QComboBox()
        self._node_id_combo.setObjectName("FirmwareFitBinaryNodeCombo")
        self._node_id_combo.addItems([str(i) for i in range(2, 18)])
        self._node_id_combo.setCurrentText("3")
        self._node_id_combo.setMaximumWidth(55)
        layout.addWidget(self._node_id_combo)

        layout.addWidget(QLabel("Cmd:"))
        self._bin_cmd_combo = QComboBox()
        self._bin_cmd_combo.setObjectName("FirmwareFitBinaryCommandCombo")
        for definition in self._binary_definitions:
            self._bin_cmd_combo.addItem(str(definition.display_name or definition.name), definition.name)
        self._bin_cmd_combo.setMinimumWidth(180)
        self._bin_cmd_combo.currentIndexChanged.connect(self._sync_binary_parameter_visibility)
        layout.addWidget(self._bin_cmd_combo)

        self._param_stack = QStackedWidget()
        self._pos_spin = QSpinBox()
        self._pos_spin.setRange(-2147483648, 2147483647)
        self._pos_spin.setValue(0)
        self._pos_spin.setMinimumWidth(110)
        self._pos_spin.setMaximumWidth(130)
        self._param_stack.addWidget(self._pos_spin)

        self._vel_spin = QSpinBox()
        self._vel_spin.setRange(-32768, 32767)
        self._vel_spin.setValue(30)
        self._vel_spin.setMinimumWidth(110)
        self._vel_spin.setMaximumWidth(130)
        self._param_stack.addWidget(self._vel_spin)

        self._bin_hex_input = QLineEdit()
        self._bin_hex_input.setObjectName("FirmwareFitBinaryHexInput")
        self._bin_hex_input.setPlaceholderText("Hex bytes (e.g. 00 AA 55)")
        self._bin_hex_input.setMinimumWidth(130)
        self._bin_hex_input.setMaximumWidth(130)
        self._param_stack.addWidget(self._bin_hex_input)
        self._param_stack.setMaximumWidth(130)
        layout.addWidget(self._param_stack)

        self._raw_hex_check = QCheckBox("Raw Hex")
        self._raw_hex_check.setObjectName("FirmwareFitRawHexCheck")
        self._raw_hex_check.toggled.connect(self._sync_binary_parameter_visibility)
        layout.addWidget(self._raw_hex_check)

        self._send_binary_button = QPushButton("Send Binary")
        self._send_binary_button.setObjectName("FirmwareFitSendBinaryButton")
        self._send_binary_button.setProperty("tone", "primary")
        self._send_binary_button.clicked.connect(self._send_manual_binary)
        layout.addWidget(self._send_binary_button)
        layout.addStretch()
        return widget

    def _sync_text_value_visibility(self) -> None:
        if self._text_cmd_combo is None or self._text_param_label is None or self._text_param_input is None:
            return
        is_setter = "=" in self._text_cmd_combo.currentText()
        self._text_param_label.setVisible(is_setter)
        self._text_param_input.setVisible(is_setter)
        if is_setter:
            self._text_param_input.setFocus()

    def _sync_binary_parameter_visibility(self) -> None:
        if self._bin_cmd_combo is None or self._param_stack is None or self._raw_hex_check is None or self._bin_hex_input is None:
            return
        if self._raw_hex_check.isChecked():
            self._param_stack.setCurrentWidget(self._bin_hex_input)
            self._bin_hex_input.setPlaceholderText("Raw Hex (e.g. 25 A5 01 03 31 ...)")
            self._bin_cmd_combo.setEnabled(False)
            return
        self._bin_cmd_combo.setEnabled(True)
        definition = self._current_binary_definition()
        kind = str((definition.parameter_schema or {}).get("kind", "none"))
        if kind == "int32" and self._pos_spin is not None:
            self._param_stack.setCurrentWidget(self._pos_spin)
        elif kind == "int16" and self._vel_spin is not None:
            self._param_stack.setCurrentWidget(self._vel_spin)
        else:
            self._param_stack.setCurrentWidget(self._bin_hex_input)
            self._bin_hex_input.setPlaceholderText("Hex bytes (e.g. 00 AA 55)")
            self._bin_hex_input.setText(str((definition.parameter_schema or {}).get("default", "") or ""))

    def _send_manual_text(self) -> None:
        definition = self._current_text_definition()
        value = None
        if self._text_param_input is not None and "=" in str(definition.text_command or ""):
            value = self._text_param_input.text().strip()
        self._controller.send_manual_text_command(definition.name, value)

    def _send_manual_binary(self) -> None:
        if self._node_id_combo is None:
            return
        node_id = int(self._node_id_combo.currentText())
        if self._raw_hex_check is not None and self._raw_hex_check.isChecked():
            self._controller.send_manual_binary_command(
                node_id=node_id,
                use_raw_hex=True,
                raw_hex_text="" if self._bin_hex_input is None else self._bin_hex_input.text(),
            )
            return
        definition = self._current_binary_definition()
        kind = str((definition.parameter_schema or {}).get("kind", "none"))
        value: object | None = None
        if kind == "int32" and self._pos_spin is not None:
            value = int(self._pos_spin.value())
        elif kind == "int16" and self._vel_spin is not None:
            value = int(self._vel_spin.value())
        elif kind not in {"none", "query_3f"} and self._bin_hex_input is not None:
            value = self._bin_hex_input.text().strip()
        self._controller.send_manual_binary_command(
            node_id=node_id,
            command_name=definition.name,
            parameter_value=value,
            use_raw_hex=False,
        )

    def _current_text_definition(self):
        text = "" if self._text_cmd_combo is None else self._text_cmd_combo.currentText().strip()
        for definition in self._text_definitions:
            if definition.text_command == text or definition.name == text:
                return definition
        return self._text_definitions[0]

    def _current_binary_definition(self):
        name = "" if self._bin_cmd_combo is None else str(self._bin_cmd_combo.currentData() or self._bin_cmd_combo.currentText())
        for definition in self._binary_definitions:
            if definition.name == name:
                return definition
        return self._binary_definitions[0]

    def _handle_status_changed(self, message: str) -> None:
        self._update_status(str(message))

    def _handle_pending_state_changed(self, pending: bool) -> None:
        for widget in (
            self._send_text_button,
            self._send_binary_button,
            self._text_cmd_combo,
            self._text_param_input,
            self._node_id_combo,
            self._bin_cmd_combo,
            self._raw_hex_check,
            self._bin_hex_input,
            self._pos_spin,
            self._vel_spin,
        ):
            if widget is not None:
                widget.setEnabled(not pending)

    def _handle_manual_binary_sent(self, event: object) -> None:
        if isinstance(event, dict):
            self._append_history(
                f"[TX] BINARY CMD to Node {int(event.get('node_id', 0)):02X}: "
                f"{event.get('command_name', 'UNKNOWN')} (Raw: {event.get('frame_hex', event.get('payload_hex', '--'))})"
            )

    def _handle_manual_binary_result(self, event: object) -> None:
        if isinstance(event, dict):
            latency = event.get("latency_ms")
            latency_text = f" [{float(latency):.1f} ms]" if isinstance(latency, (int, float)) else ""
            self._append_history(f"[RX] BINARY RESP{latency_text}: {event.get('decoded_text', '--')} (Raw: {event.get('response_hex', '--')})")

    def _handle_manual_text_sent(self, event: object) -> None:
        if isinstance(event, dict):
            self._append_history(f"[TX] TEXT CMD: {event.get('command_text', '--')} (Raw: {event.get('frame_hex', '--')})")

    def _handle_manual_text_result(self, event: object) -> None:
        if isinstance(event, dict):
            latency = event.get("latency_ms")
            latency_text = f" [{float(latency):.1f} ms]" if isinstance(latency, (int, float)) else ""
            self._append_history(f"[RX] TEXT RESP: {event.get('decoded_text', '--')}{latency_text} (Raw: {event.get('response_hex', '--')})")

    def _append_history(self, message: str) -> None:
        if self._history_output is None:
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._history_output.append(f"[{timestamp}] {message}")


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
