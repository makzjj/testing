"""Mechanical page implementation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from myconfig.config_schema_adapter import ConfigSchemaAdapter

from data.binary_cmd_builders import (
    build_getpos,
    build_lflag_query_payload,
    build_nodeconfig_query_payload,
    build_run,
    build_rflag_query_payload,
    build_stopmotor,
)
from data.binary_cmd_parser import decode_command
from services.functional_transport_adapter import FunctionalTransportAdapter
from services.release_watch_helper import ReleaseWatchHelper

from ..bridges import WorkspaceRuntimeBridge
from ..widgets import LabeledControl, PanelFrame, ResponsiveRow
from .base_page import BaseWorkspacePage
from .production_parameter_controller import (
    MAX_TESTABLE_NODE_ID,
    MIN_TESTABLE_NODE_ID,
    ParameterRequest,
    ParameterVerificationResult,
    ProductionParameterController,
    UUID_VERIFY_TIMEOUT_MS,
    default_workbook_parameter_definitions,
    parse_pwm_value,
)

PRESET_COUNTS = (
    172,
    344,
    688,
    1376,
    2752,
    5504,
    11008,
    22016,
    44032,
    88064,
    176128,
    264192,
    352256,
    440320,
    528384,
    616448,
    704512,
    792576,
    880640,
    968704,
)
COUNTS_PER_REV = 88064


@dataclass
class _PendingMechanicalRequest:
    family: str
    action: str
    node_id: int
    timeout_owner: str
    button: QPushButton | None = None
    idle_button_text: str | None = None
    pending_button_text: str | None = None
    expected_cmd: int | None = None
    definitions: list[Any] | None = None
    requests: list[ParameterRequest] | None = None
    index: int = 0
    results: list[Any] | None = None
    enable_eeprom: bool = False


class _MechanicalParameterController(ProductionParameterController):
    """Mechanical-specific wrapper that ignores wrong-node traffic."""

    def _handle_runtime_packet_parameter(self, packet: dict) -> None:
        request = self._pending_parameter_request
        if request is not None:
            sender = int(packet.get("sender", -1))
            if sender != request.node_id:
                raw_cmd = int(packet.get("cmd", -1))
                raw_params = packet.get("params") or []
                raw_hex = " ".join(f"{int(v) & 0xFF:02X}" for v in [raw_cmd, *raw_params])
                self.log_message.emit(
                    f"[Mechanical] Ignored parameter packet from Node {sender:02d} "
                    f"(expected {request.node_id:02d}), cmd {raw_cmd:02X}, raw: {raw_hex}"
                )
                return
        super()._handle_runtime_packet_parameter(packet)

    def _handle_runtime_packet_eeprom_save(self, packet: dict) -> None:
        if self._pending_eeprom_save is not None:
            expected_node_id, _node_name = self._pending_eeprom_save
            sender = packet.get("sender")
            if sender is not None and int(sender) != expected_node_id:
                raw_cmd = int(packet.get("cmd", -1))
                raw_params = packet.get("params") or []
                raw_hex = " ".join(f"{int(v) & 0xFF:02X}" for v in [raw_cmd, *raw_params])
                self.log_message.emit(
                    f"[Mechanical] Ignored EEPROM packet from Node {int(sender):02d} "
                    f"(expected {expected_node_id:02d}), cmd {raw_cmd:02X}, raw: {raw_hex}"
                )
                return
        super()._handle_runtime_packet_eeprom_save(packet)


class MotorMovementControlPopup(QDialog):
    """UI-only popup for mechanical motor movement controls."""

    def __init__(self, parent: QWidget | None = None, node_options: list[dict[str, Any]] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Motor Movement Control")
        self.setModal(False)
        self.resize(640, 520)
        self.setMinimumSize(560, 460)
        self.setSizeGripEnabled(True)

        self._node_options = list(node_options or [])

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(6)

        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(8)
        top_grid.setVerticalSpacing(6)

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("MechanicalPopupNodeCombo")
        self.node_combo.setMinimumWidth(180)
        MechanicalPage._style_combo_box(self.node_combo)

        self.axis_type_value = self._readonly_line("n/a", "MechanicalPopupAxisTypeValue", width=110)
        self.pwm_input = QSpinBox()
        self.pwm_input.setObjectName("MechanicalPopupPwmInput")
        self.pwm_input.setRange(0, 1000)
        self.pwm_input.setValue(100)

        self.set_pwm_button = QPushButton("Set PWM")
        self.set_pwm_button.setObjectName("MechanicalPopupSetPwmButton")
        self.run_positive_button = QPushButton("Run +")
        self.run_positive_button.setObjectName("MechanicalPopupRunPositiveButton")
        self.run_negative_button = QPushButton("Run -")
        self.run_negative_button.setObjectName("MechanicalPopupRunNegativeButton")
        self.home_button = QPushButton("Home")
        self.home_button.setObjectName("MechanicalPopupHomeButton")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("MechanicalPopupStopButton")

        self.move_absolute_checkbox = QCheckBox("Move Absolute")
        self.move_absolute_checkbox.setObjectName("MechanicalPopupMoveAbsoluteCheckbox")
        self.absolute_target_input = QLineEdit("0")
        self.absolute_target_input.setObjectName("MechanicalPopupAbsoluteTargetInput")
        self.absolute_target_input.setMaximumWidth(160)

        self.relative_preset_combo = QComboBox()
        self.relative_preset_combo.setObjectName("MechanicalPopupRelativePresetCombo")
        MechanicalPage._style_combo_box(self.relative_preset_combo)
        self.relative_direction_combo = QComboBox()
        self.relative_direction_combo.setObjectName("MechanicalPopupRelativeDirectionCombo")
        self.relative_direction_combo.addItems(["Positive", "Negative"])
        MechanicalPage._style_combo_box(self.relative_direction_combo)
        self.relative_count_value = self._readonly_line("0", "MechanicalPopupRelativeCountValue", width=140)
        self.move_relative_button = QPushButton("Move Relative")
        self.move_relative_button.setObjectName("MechanicalPopupMoveRelativeButton")
        self.current_position_value = self._readonly_line("n/a", "MechanicalPopupCurrentPositionValue", width=140)
        self.get_position_button = QPushButton("Get Position")
        self.get_position_button.setObjectName("MechanicalPopupGetPositionButton")
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("MechanicalPopupCloseButton")
        self.helper_text = QLabel("Legacy relative-movement presets use 88,064 counts per revolution.")
        self.helper_text.setObjectName("MechanicalPopupHelperText")
        self.helper_text.setWordWrap(True)

        for button in (
            self.set_pwm_button,
            self.run_positive_button,
            self.run_negative_button,
            self.home_button,
            self.stop_button,
            self.move_relative_button,
            self.get_position_button,
        ):
            button.setEnabled(False)

        self.close_button.clicked.connect(self.close)

        top_grid.addWidget(LabeledControl("Node", self.node_combo), 0, 0)
        top_grid.addWidget(LabeledControl("Axis type", self.axis_type_value), 0, 1)
        top_grid.addWidget(LabeledControl("PWM", self.pwm_input), 0, 2)
        top_grid.addWidget(self.set_pwm_button, 0, 3)
        top_grid.addWidget(self.run_positive_button, 1, 0)
        top_grid.addWidget(self.run_negative_button, 1, 1)
        top_grid.addWidget(self.home_button, 1, 2)
        top_grid.addWidget(self.stop_button, 1, 3)
        top_grid.addWidget(self.move_absolute_checkbox, 2, 0)
        top_grid.addWidget(LabeledControl("Absolute target", self.absolute_target_input), 2, 1, 1, 2)
        top_grid.addWidget(self.get_position_button, 2, 3)
        root.addLayout(top_grid)

        lower_grid = QGridLayout()
        lower_grid.setContentsMargins(0, 0, 0, 0)
        lower_grid.setHorizontalSpacing(8)
        lower_grid.setVerticalSpacing(6)
        lower_grid.addWidget(LabeledControl("Preset", self.relative_preset_combo), 0, 0)
        lower_grid.addWidget(LabeledControl("Direction", self.relative_direction_combo), 0, 1)
        lower_grid.addWidget(LabeledControl("Relative counts", self.relative_count_value), 0, 2)
        lower_grid.addWidget(self.move_relative_button, 0, 3)
        lower_grid.addWidget(LabeledControl("Current position", self.current_position_value), 1, 0, 1, 2)
        lower_grid.addWidget(self.helper_text, 1, 2, 1, 2)
        root.addLayout(lower_grid)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(6)
        footer.addStretch(1)
        footer.addWidget(self.close_button)
        root.addLayout(footer)

        self.node_combo.currentIndexChanged.connect(self._update_axis_display)
        self.relative_preset_combo.currentIndexChanged.connect(self._update_relative_count)
        self.relative_direction_combo.currentIndexChanged.connect(self._update_relative_count)
        self.move_absolute_checkbox.stateChanged.connect(self._sync_absolute_mode_state)

        self._populate_nodes()
        self._populate_presets()
        self._sync_absolute_mode_state()
        self._update_relative_count()

    def set_node_options(self, node_options: list[dict[str, Any]]) -> None:
        self._node_options = list(node_options)
        self._populate_nodes()

    def _populate_nodes(self) -> None:
        current_node_id = self._current_node_id()
        self.node_combo.blockSignals(True)
        self.node_combo.clear()
        if not self._node_options:
            self.node_combo.addItem("No nodes available", None)
        else:
            for node in self._node_options:
                self.node_combo.addItem(str(node.get("label", "Node")), node)
            if current_node_id is not None:
                for index in range(self.node_combo.count()):
                    data = self.node_combo.itemData(index)
                    if isinstance(data, dict) and data.get("node_id") == current_node_id:
                        self.node_combo.setCurrentIndex(index)
                        break
        self.node_combo.blockSignals(False)
        self._update_axis_display()

    def _populate_presets(self) -> None:
        self.relative_preset_combo.clear()
        for counts in PRESET_COUNTS:
            label = f"{counts} - {counts // COUNTS_PER_REV} rev"
            self.relative_preset_combo.addItem(label, counts)

    def _current_node_id(self) -> int | None:
        data = self.node_combo.currentData()
        if isinstance(data, dict):
            node_id = data.get("node_id")
            return int(node_id) if isinstance(node_id, int) else None
        return None

    def _update_axis_display(self) -> None:
        data = self.node_combo.currentData()
        axis = str(data.get("axis", "n/a")) if isinstance(data, dict) else "n/a"
        self.axis_type_value.setText(axis)

    def _update_relative_count(self) -> None:
        counts = int(self.relative_preset_combo.currentData() or 0)
        if self.relative_direction_combo.currentText() == "Negative":
            counts = -abs(counts)
        else:
            counts = abs(counts)
        self.relative_count_value.setText(str(counts))

    def _sync_absolute_mode_state(self) -> None:
        self.absolute_target_input.setEnabled(self.move_absolute_checkbox.isChecked())

    @staticmethod
    def _readonly_line(text: str, object_name: str, *, width: int) -> QLineEdit:
        line = QLineEdit(text)
        line.setObjectName(object_name)
        line.setReadOnly(True)
        line.setMaximumWidth(width)
        return line


class MechanicalPage(BaseWorkspacePage):
    """Focused mechanical workspace page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Mechanical", "")
        self._bridge = bridge
        self._schema_adapter = ConfigSchemaAdapter()
        self._node_entries: list[dict[str, Any]] = []
        self._movement_popup: MotorMovementControlPopup | None = None
        self._transport_adapter: FunctionalTransportAdapter | None = None
        self._transport_runtime_window: object | None = None
        self._transport_node_id: int | None = None
        self._pending_request: _PendingMechanicalRequest | None = None
        self._persistent_write_pending = False
        self._parameter_actual_texts: dict[str, str] = {}
        self._sensor_state_cache: dict[str, int | None] = {"left": None, "right": None}
        self._sensor_state_node_id: int | None = None
        self._actual_nodeconfig_value: int | None = None
        self._pending_nodeconfig_value: int | None = None
        self._updating_nodeconfig_editor = False
        self._runtime_packet_window: QObject | None = None
        self._release_watch_helper = ReleaseWatchHelper(self._bridge)
        self._parameter_definitions = {
            definition.name: definition
            for definition in default_workbook_parameter_definitions()
        }
        self._parameter_controller = _MechanicalParameterController(bridge, timeout_ms=UUID_VERIFY_TIMEOUT_MS)
        self._parameter_controller.log_message.connect(self._append_log)
        self._parameter_controller.parameter_write_finished.connect(self._on_parameter_write_finished)
        self._parameter_controller.parameter_verification_finished.connect(self._on_parameter_verification_finished)
        self._parameter_controller.eeprom_save_finished.connect(self._on_eeprom_save_finished)
        self._simple_request_timer = QTimer(self)
        self._simple_request_timer.setSingleShot(True)
        self._simple_request_timer.timeout.connect(self._handle_simple_request_timeout)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        self.open_popup_button = QPushButton("Motor Movement Control")
        self.open_popup_button.setObjectName("MechanicalOpenMotorMovementControlButton")
        self.open_popup_button.clicked.connect(self._open_motor_movement_popup)
        popup_min_width = self.open_popup_button.fontMetrics().horizontalAdvance(self.open_popup_button.text()) + 30
        self.open_popup_button.setMinimumWidth(max(184, popup_min_width))
        self.open_popup_button.setMaximumWidth(232)
        self.open_popup_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._style_enabled_button(self.open_popup_button)

        self.row_one = ResponsiveRow(stack_below_width=760)
        self.row_one.setObjectName("MechanicalRowOne")
        self.node_header_panel = self._build_node_header_group()
        self.sensor_panel = self._build_sensor_group()
        self.row_one.add_panel(self.node_header_panel, stretch=49)
        self.row_one.add_panel(self.sensor_panel, stretch=51)
        self._align_top_card_heights()

        self.row_two = ResponsiveRow(stack_below_width=820)
        self.row_two.setObjectName("MechanicalRowTwo")
        self.velocity_panel = self._build_velocity_group()
        self.ramp_panel = self._build_ramp_group()
        self.pid_panel = self._build_pid_group()
        self.row_two.add_panel(self.velocity_panel, stretch=1)
        self.row_two.add_panel(self.ramp_panel, stretch=1)
        self.row_two.add_panel(self.pid_panel, stretch=1)

        self.row_three = ResponsiveRow(stack_below_width=1120)
        self.row_three.setObjectName("MechanicalRowThree")
        self.log_panel = self._build_log_panel()
        self.row_three.add_panel(self.log_panel, stretch=1)

        self.add_full_width(self.row_one)
        self.add_full_width(self.row_two)
        self.add_full_width(self.row_three)

    def _build_log_panel(self) -> PanelFrame:
        panel = PanelFrame("Mechanical Log")
        panel.setObjectName("MechanicalLogPanel")
        self._configure_module_panel(panel, min_width=420)

        log_controls = QHBoxLayout()
        log_controls.setContentsMargins(0, 0, 0, 0)
        log_controls.setSpacing(8)
        self.clear_log_button = QPushButton("Clear")
        self.clear_log_button.setObjectName("MechanicalClearLogButton")
        self.clear_log_button.clicked.connect(self._clear_log)
        self._style_enabled_button(self.clear_log_button)
        log_controls.addWidget(self.clear_log_button)
        self.save_to_eeprom_button = self._disabled_button("Save to EEPROM", "MechanicalSaveToEepromButton")
        self.save_to_eeprom_button.clicked.connect(self._handle_save_to_eeprom_clicked)
        log_controls.addWidget(self.save_to_eeprom_button)
        log_controls.addStretch(1)

        self.log_output = QPlainTextEdit()
        self.log_output.setObjectName("MechanicalLogOutput")
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumHeight(280)
        self.log_output.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_output.setStyleSheet(
            "background: #F5F7FB; color: #5B524C; border: 1px solid #E8ECF1; "
            "border-radius: 16px; padding: 10px; font-family: Consolas; font-size: 15px;"
        )

        panel.body_layout.addLayout(log_controls)
        panel.body_layout.addWidget(self.log_output)
        return panel

    def _build_node_header_group(self) -> PanelFrame:
        group = PanelFrame("Node Header")
        group.setObjectName("MechanicalNodeHeaderPanel")
        self._configure_module_panel(group, min_width=340)
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(8)

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("MechanicalNodeCombo")
        self.node_combo.setMinimumWidth(144)
        self._style_combo_box(self.node_combo)
        self.node_combo.currentIndexChanged.connect(self._handle_selected_node_changed)

        self.axis_type_value = self._readonly_line("n/a", "MechanicalAxisTypeValue", width=92)
        layout.addWidget(LabeledControl("Node", self.node_combo), 0, 0)
        layout.addWidget(LabeledControl("Axis Type", self.axis_type_value), 0, 1)

        nodeconfig_section = QWidget()
        nodeconfig_section.setObjectName("MechanicalNodeConfigPanel")
        nodeconfig_layout = QGridLayout(nodeconfig_section)
        nodeconfig_layout.setContentsMargins(0, 2, 0, 0)
        nodeconfig_layout.setHorizontalSpacing(10)
        nodeconfig_layout.setVerticalSpacing(8)

        self.nodeconfig_row = QWidget()
        self.nodeconfig_row.setObjectName("MechanicalNodeHeaderNodeConfigRow")
        self.flag_selector_row = QWidget()
        self.flag_selector_row.setObjectName("MechanicalNodeHeaderFlagSelectorRow")
        self.polarity_row = QWidget()
        self.polarity_row.setObjectName("MechanicalNodeHeaderPolarityRow")
        self.nodeconfig_button_row = QWidget()
        self.nodeconfig_button_row.setObjectName("MechanicalNodeHeaderButtonRow")

        self.current_nodeconfig_value = self._readonly_line("n/a", "MechanicalCurrentNodeconfigValue", width=96)
        self.pending_nodeconfig_value = self._readonly_line("n/a", "MechanicalPendingNodeconfigValue", width=96)
        self.pending_nodeconfig_value.setEnabled(False)
        self.nodeconfig_unsaved_indicator = QLabel("Unsaved")
        self.nodeconfig_unsaved_indicator.setObjectName("MechanicalNodeconfigUnsavedIndicator")
        self.nodeconfig_unsaved_indicator.setStyleSheet(
            "background: #FFF1E3;"
            "color: #C46A12;"
            "border: 1px solid #F3C79E;"
            "border-radius: 10px;"
            "padding: 4px 8px;"
            "font-weight: 600;"
        )
        self.nodeconfig_unsaved_indicator.hide()
        self.polarity_selector = QComboBox()
        self.polarity_selector.setObjectName("MechanicalPolaritySelector")
        self.polarity_selector.addItems(["Negative", "Positive"])
        self.polarity_selector.setEnabled(True)
        self.polarity_selector.setMinimumWidth(92)
        self.polarity_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.polarity_selector)
        self.flag_selector_selector = QComboBox()
        self.flag_selector_selector.setObjectName("MechanicalFlagSelector")
        self.flag_selector_selector.addItems(["Left / INT0", "Right / INT1"])
        self.flag_selector_selector.setEnabled(True)
        self.flag_selector_selector.setMinimumWidth(92)
        self.flag_selector_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.flag_selector_selector)
        self.read_nodeconfig_button = self._disabled_button("Read", "MechanicalReadNodeConfigButton")
        self.write_nodeconfig_button = self._disabled_button("Write", "MechanicalWriteNodeConfigButton")
        self.read_nodeconfig_button.clicked.connect(self._handle_read_nodeconfig_clicked)
        self.flag_selector_selector.currentIndexChanged.connect(self._handle_nodeconfig_editor_changed)
        self.polarity_selector.currentIndexChanged.connect(self._handle_nodeconfig_editor_changed)

        nodeconfig_layout.addWidget(LabeledControl("Actual NODECONFIG", self.current_nodeconfig_value), 0, 0)
        pending_row = QWidget()
        pending_row.setObjectName("MechanicalPendingNodeconfigRow")
        pending_layout = QHBoxLayout(pending_row)
        pending_layout.setContentsMargins(0, 0, 0, 0)
        pending_layout.setSpacing(8)
        pending_layout.addWidget(self.pending_nodeconfig_value, 0, Qt.AlignmentFlag.AlignVCenter)
        pending_layout.addWidget(self.nodeconfig_unsaved_indicator, 0, Qt.AlignmentFlag.AlignVCenter)
        pending_layout.addStretch(1)
        nodeconfig_layout.addWidget(LabeledControl("Pending NODECONFIG", pending_row), 1, 0)
        nodeconfig_layout.addWidget(LabeledControl("Flag Selector", self.flag_selector_selector), 2, 0)
        nodeconfig_layout.addWidget(LabeledControl("Polarity", self.polarity_selector), 3, 0)
        button_row = QHBoxLayout(self.nodeconfig_button_row)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self._equalize_button_widths(self.read_nodeconfig_button, self.write_nodeconfig_button)
        button_row.addWidget(self.read_nodeconfig_button)
        button_row.addWidget(self.write_nodeconfig_button)
        button_row.addStretch(1)
        nodeconfig_layout.addWidget(self.nodeconfig_button_row, 4, 0)

        layout.addWidget(nodeconfig_section, 1, 0, 1, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        group.body_layout.addLayout(layout)
        return group

    def _build_sensor_group(self) -> PanelFrame:
        group = PanelFrame("Sensor Status")
        group.setObjectName("MechanicalSensorPanel")
        self._configure_module_panel(group, min_width=360)
        header_layout = group.layout()
        title_item = header_layout.takeAt(0)
        title_label = title_item.widget() if title_item is not None else None
        sensor_header_row = QWidget()
        sensor_header_row.setObjectName("MechanicalSensorHeaderRow")
        sensor_header_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sensor_header_layout = QHBoxLayout(sensor_header_row)
        sensor_header_layout.setContentsMargins(0, 0, 0, 0)
        sensor_header_layout.setSpacing(8)
        sensor_header_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        if isinstance(title_label, QLabel):
            sensor_header_layout.addWidget(title_label, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        sensor_header_layout.addStretch(1)
        sensor_header_layout.addWidget(self.open_popup_button, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header_layout.insertWidget(0, sensor_header_row)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.left_flag_led = self._build_led("MechanicalLeftFlagLed")
        self.left_flag_state_value = self._readonly_display_label("unknown", "MechanicalLeftFlagStateValue", width=92)
        self.left_flag_setting_selector = QComboBox()
        self.left_flag_setting_selector.setObjectName("MechanicalLeftFlagSettingSelector")
        self.left_flag_setting_selector.addItems(["1", "9", "11"])
        self.left_flag_setting_selector.setEnabled(False)
        self.left_flag_setting_selector.setMinimumWidth(76)
        self.left_flag_setting_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.left_flag_setting_selector)
        self.left_flag_write_button = self._disabled_button("Write", "MechanicalLeftFlagWriteButton")
        self.right_flag_led = self._build_led("MechanicalRightFlagLed")
        self.right_flag_state_value = self._readonly_display_label("unknown", "MechanicalRightFlagStateValue", width=92)
        self.right_flag_setting_selector = QComboBox()
        self.right_flag_setting_selector.setObjectName("MechanicalRightFlagSettingSelector")
        self.right_flag_setting_selector.addItems(["1", "9", "11"])
        self.right_flag_setting_selector.setEnabled(False)
        self.right_flag_setting_selector.setMinimumWidth(76)
        self.right_flag_setting_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.right_flag_setting_selector)
        self.right_flag_write_button = self._disabled_button("Write", "MechanicalRightFlagWriteButton")
        self.read_lflag_button = self._disabled_button("Read LFLAG", "MechanicalReadLFlagButton")
        self.read_rflag_button = self._disabled_button("Read RFLAG", "MechanicalReadRFlagButton")
        self.read_lflag_button.clicked.connect(self._handle_read_lflag_clicked)
        self.read_rflag_button.clicked.connect(self._handle_read_rflag_clicked)

        layout.addWidget(
            self._build_sensor_row(
                "Left Flag (INT0)",
                self.left_flag_led,
                self.left_flag_state_value,
                self.left_flag_setting_selector,
                self.left_flag_write_button,
                row_object_name="MechanicalLeftFlagRow",
            )
        )
        layout.addWidget(
            self._build_sensor_row(
                "Right Flag (INT1)",
                self.right_flag_led,
                self.right_flag_state_value,
                self.right_flag_setting_selector,
                self.right_flag_write_button,
                row_object_name="MechanicalRightFlagRow",
            )
        )

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self._equalize_button_widths(self.read_lflag_button, self.read_rflag_button)
        button_row.addWidget(self.read_lflag_button)
        button_row.addWidget(self.read_rflag_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        group.body_layout.addLayout(layout)
        return group

    def _build_velocity_group(self) -> PanelFrame:
        group = PanelFrame("Velocity / Motion Control")
        group.setObjectName("MechanicalVelocityPanel")
        self._configure_module_panel(group, min_width=220)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.drive_mode_group = QButtonGroup(group)
        self.pwm_mode_radio = QRadioButton("PWM")
        self.pwm_mode_radio.setObjectName("MechanicalPwmModeRadio")
        self.rpm_mode_radio = QRadioButton("RPM")
        self.rpm_mode_radio.setObjectName("MechanicalRpmModeRadio")
        self.pwm_mode_radio.setChecked(True)
        self.drive_mode_group.addButton(self.pwm_mode_radio)
        self.drive_mode_group.addButton(self.rpm_mode_radio)

        self.current_pwm_value = self._readonly_line("0", "MechanicalCurrentPwmValue", width=64)
        self.current_rpm_value = self._readonly_line("n/a", "MechanicalCurrentRpmValue", width=76)
        self.read_pwm_button = self._disabled_button("Read PWM", "MechanicalReadPwmButton")
        self.read_rpm_button = self._disabled_button("Read RPM", "MechanicalReadRpmButton")
        self.selected_pwm_combo = QComboBox()
        self.selected_pwm_combo.setObjectName("MechanicalPwmSelectionCombo")
        self.selected_pwm_combo.addItems([str(value) for value in range(-100, 101, 10)])
        self.selected_pwm_combo.setCurrentText("0")
        self.selected_pwm_combo.setMinimumWidth(76)
        self.selected_pwm_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.selected_pwm_combo)
        self.set_pwm_row_button = self._disabled_button("Set PWM", "MechanicalSetPwmRowButton")
        self.rpm_selector = QComboBox()
        self.rpm_selector.setObjectName("MechanicalRpmSelectionCombo")
        self.rpm_selector.addItems(["n/a"])
        self.rpm_selector.setEnabled(False)
        self.rpm_selector.setMinimumWidth(76)
        self.rpm_selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style_combo_box(self.rpm_selector)
        self.set_rpm_button = self._disabled_button("Set RPM", "MechanicalSetRpmButton")
        self.home_hunt_button = self._disabled_button("Hunt for Zero", "MechanicalHomeHuntButton")
        self.velocity_stop_motor_button = self._disabled_button("Stop Motor", "MechanicalVelocityStopMotorButton")
        self.current_position_value = self._readonly_line("n/a", "MechanicalCurrentPositionValue", width=88)
        self.get_position_button = self._disabled_button("Get Position", "MechanicalGetPositionButton")
        self.read_pwm_button.clicked.connect(self._handle_read_pwm_clicked)
        self.set_pwm_row_button.clicked.connect(self._handle_set_pwm_clicked)
        self.get_position_button.clicked.connect(self._handle_get_position_clicked)

        pwm_row = QGridLayout()
        pwm_row.setContentsMargins(0, 0, 0, 0)
        pwm_row.setHorizontalSpacing(8)
        pwm_row.setVerticalSpacing(6)
        pwm_row.addWidget(self.pwm_mode_radio, 0, 0)
        pwm_row.addWidget(self.current_pwm_value, 0, 1)
        pwm_row.addWidget(self.read_pwm_button, 0, 2)
        pwm_row.addWidget(self.selected_pwm_combo, 1, 1)
        pwm_row.addWidget(self.set_pwm_row_button, 1, 2)
        pwm_row.setColumnStretch(1, 1)
        pwm_row.setColumnStretch(2, 0)
        layout.addLayout(pwm_row)

        rpm_row = QGridLayout()
        rpm_row.setContentsMargins(0, 0, 0, 0)
        rpm_row.setHorizontalSpacing(8)
        rpm_row.setVerticalSpacing(6)
        rpm_row.addWidget(self.rpm_mode_radio, 0, 0)
        rpm_row.addWidget(self.current_rpm_value, 0, 1)
        rpm_row.addWidget(self.read_rpm_button, 0, 2)
        rpm_row.addWidget(self.rpm_selector, 1, 1)
        rpm_row.addWidget(self.set_rpm_button, 1, 2)
        rpm_row.setColumnStretch(1, 1)
        rpm_row.setColumnStretch(2, 0)
        layout.addLayout(rpm_row)

        position_row = QHBoxLayout()
        position_row.setContentsMargins(0, 0, 0, 0)
        position_row.setSpacing(8)
        position_row.addWidget(QLabel("Position"))
        position_row.addWidget(self.current_position_value)
        position_row.addWidget(self.get_position_button)
        position_row.addStretch(1)
        layout.addLayout(position_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self._equalize_button_widths(self.home_hunt_button, self.velocity_stop_motor_button)
        action_row.addWidget(self.home_hunt_button)
        action_row.addWidget(self.velocity_stop_motor_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        layout.addStretch(1)
        group.body_layout.addLayout(layout)
        return group

    def _build_pid_group(self) -> PanelFrame:
        group = PanelFrame("Position & Speed PID")
        group.setObjectName("MechanicalPidPanel")
        self._configure_module_panel(group, min_width=220)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        fields_grid = QGridLayout()
        fields_grid.setContentsMargins(0, 0, 0, 0)
        fields_grid.setHorizontalSpacing(8)
        fields_grid.setVerticalSpacing(8)

        self.pid_p_value = self._editable_line("n/a", "MechanicalPidPValue", width=82)
        self.pid_i_value = self._editable_line("n/a", "MechanicalPidIValue", width=82)
        self.pid_d_value = self._editable_line("n/a", "MechanicalPidDValue", width=82)
        self.pid_read_button = self._disabled_button("Read", "MechanicalPidReadButton")
        self.pid_write_button = self._disabled_button("Write", "MechanicalPidWriteButton")
        self.pid_read_button.clicked.connect(self._handle_pid_read_clicked)
        self.pid_write_button.clicked.connect(self._handle_pid_write_clicked)

        fields_grid.addWidget(QLabel("P"), 0, 0)
        fields_grid.addWidget(self.pid_p_value, 0, 1)
        fields_grid.addWidget(QLabel("I"), 1, 0)
        fields_grid.addWidget(self.pid_i_value, 1, 1)
        fields_grid.addWidget(QLabel("D"), 2, 0)
        fields_grid.addWidget(self.pid_d_value, 2, 1)
        fields_grid.setColumnStretch(2, 1)
        layout.addLayout(fields_grid)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self._equalize_button_widths(self.pid_read_button, self.pid_write_button)
        button_row.addWidget(self.pid_read_button)
        button_row.addWidget(self.pid_write_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)
        group.body_layout.addLayout(layout)
        return group

    def _build_ramp_group(self) -> PanelFrame:
        group = PanelFrame("Ramp Down Profile")
        group.setObjectName("MechanicalRampPanel")
        self._configure_module_panel(group, min_width=220)
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self.ramp_slope_value = self._editable_line("n/a", "MechanicalRampSlopeValue", width=82)
        self.ramp_step_value = self._editable_line("n/a", "MechanicalRampStepValue", width=82)
        self.ramp_min_velocity_value = self._editable_line("n/a", "MechanicalRampMinVelocityValue", width=82)
        self.ramp_target_offset_value = self._editable_line("n/a", "MechanicalRampTargetOffsetValue", width=82)
        self.ramp_region_value = self._editable_line("n/a", "MechanicalRampRegionValue", width=82)
        self.ramp_read_button = self._disabled_button("Read", "MechanicalRampReadButton")
        self.ramp_write_button = self._disabled_button("Write", "MechanicalRampWriteButton")
        self.ramp_read_button.clicked.connect(self._handle_ramp_read_clicked)
        self.ramp_write_button.clicked.connect(self._handle_ramp_write_clicked)

        layout.addWidget(QLabel("Slope"), 0, 0)
        layout.addWidget(self.ramp_slope_value, 0, 1)
        layout.addWidget(QLabel("Step"), 1, 0)
        layout.addWidget(self.ramp_step_value, 1, 1)
        layout.addWidget(QLabel("Min Velocity"), 2, 0)
        layout.addWidget(self.ramp_min_velocity_value, 2, 1)
        layout.addWidget(QLabel("Target Offset"), 3, 0)
        layout.addWidget(self.ramp_target_offset_value, 3, 1)
        layout.addWidget(QLabel("Region"), 4, 0)
        layout.addWidget(self.ramp_region_value, 4, 1)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        self._equalize_button_widths(self.ramp_read_button, self.ramp_write_button)
        button_row.addWidget(self.ramp_read_button)
        button_row.addWidget(self.ramp_write_button)
        button_row.addStretch(1)
        layout.addLayout(button_row, 5, 0, 1, 2)
        layout.setColumnStretch(2, 1)
        group.body_layout.addLayout(layout)
        return group

    def refresh(self) -> None:
        self._attach_runtime_packet_listener()
        raw_config = getattr(self._bridge, "raw_config", {}) or {}
        self._node_entries = self._collect_node_entries(raw_config)
        self._populate_node_combo()
        self._refresh_from_selected_node()
        if self._movement_popup is not None:
            self._movement_popup.set_node_options(self._node_entries)
            self._bind_movement_popup()
            self._sync_movement_popup_selection_from_page()
            self._sync_movement_popup_controls()
        self._update_control_states()

    def _populate_node_combo(self) -> None:
        current_node_id = self._selected_node_id()
        self.node_combo.blockSignals(True)
        self.node_combo.clear()
        if not self._node_entries:
            self.node_combo.addItem("No nodes available", None)
        else:
            for node in self._node_entries:
                self.node_combo.addItem(str(node["label"]), node)
            if current_node_id is not None:
                for index in range(self.node_combo.count()):
                    data = self.node_combo.itemData(index)
                    if isinstance(data, dict) and data.get("node_id") == current_node_id:
                        self.node_combo.setCurrentIndex(index)
                        break
        self.node_combo.blockSignals(False)

    def _selected_node_id(self) -> int | None:
        entry = self._selected_node_entry()
        if entry is None:
            return None
        node_id = entry.get("node_id")
        return int(node_id) if isinstance(node_id, int) else None

    def _selected_node_entry(self) -> dict[str, Any] | None:
        data = self.node_combo.currentData()
        return data if isinstance(data, dict) else None

    def _handle_selected_node_changed(self) -> None:
        self._cancel_release_watch("node_change")
        self._parameter_actual_texts = {}
        self._persistent_write_pending = False
        self._reset_sensor_state()
        self._refresh_from_selected_node()
        self._sync_movement_popup_selection_from_page()
        self._sync_movement_popup_controls()
        self._update_control_states()

    def _refresh_from_selected_node(self) -> None:
        entry = self._selected_node_entry()
        if entry is None:
            self.axis_type_value.setText("n/a")
            self._apply_nodeconfig_display(None)
            self.current_position_value.setText("n/a")
            self.current_pwm_value.setText("0")
            self.pid_p_value.setText("n/a")
            self.pid_i_value.setText("n/a")
            self.pid_d_value.setText("n/a")
            self.ramp_slope_value.setText("n/a")
            self.ramp_step_value.setText("n/a")
            self.ramp_min_velocity_value.setText("n/a")
            self.ramp_target_offset_value.setText("n/a")
            self.ramp_region_value.setText("n/a")
            self._render_sensor_state()
            return

        self.axis_type_value.setText(str(entry.get("axis", "n/a")))
        self._apply_nodeconfig_display(entry.get("node_config", "n/a"))
        self.pid_p_value.setText(str(entry.get("pos_kp", "n/a")))
        self.pid_i_value.setText(str(entry.get("pos_ki", "n/a")))
        self.pid_d_value.setText(str(entry.get("pos_kd", "n/a")))
        self.ramp_slope_value.setText(str(entry.get("ramp_down_slope", "n/a")))
        self.ramp_step_value.setText(str(entry.get("ramp_down_step", "n/a")))
        self.ramp_min_velocity_value.setText(str(entry.get("ramp_down_min_velocity", "n/a")))
        self.ramp_target_offset_value.setText(str(entry.get("ramp_down_target_offset", "n/a")))
        self.ramp_region_value.setText(str(entry.get("ramp_down_region", "n/a")))
        self.current_position_value.setText("n/a")
        self.current_pwm_value.setText("0")
        self._render_sensor_state()

    def _collect_node_entries(self, raw_config: dict) -> list[dict[str, Any]]:
        axes = self._schema_adapter.extract_axis_section(raw_config)
        entries_by_node: dict[int, dict[str, Any]] = {}
        for axis_name, axis_data in axes.items():
            if not isinstance(axis_data, dict):
                continue
            node_id = axis_data.get("node_id")
            if not isinstance(node_id, int):
                continue
            axis = str(axis_name).upper()
            entries_by_node[node_id] = {
                "label": f"Node {node_id}",
                "node_id": node_id,
                "axis": axis,
                "node_config": axis_data.get("node_config", "n/a"),
                "pos_kp": axis_data.get("pos_kp", "n/a"),
                "pos_ki": axis_data.get("pos_ki", "n/a"),
                "pos_kd": axis_data.get("pos_kd", "n/a"),
                "ramp_down_slope": axis_data.get("ramp_down_slope", "n/a"),
                "ramp_down_step": axis_data.get("ramp_down_step", "n/a"),
                "ramp_down_min_velocity": axis_data.get("ramp_down_min_velocity", "n/a"),
                "ramp_down_target_offset": axis_data.get("ramp_down_target_offset", "n/a"),
                "ramp_down_region": axis_data.get("ramp_down_region", "n/a"),
            }
        entries: list[dict[str, Any]] = []
        for node_id in range(3, 17):
            entry = entries_by_node.get(
                node_id,
                {
                    "label": f"Node {node_id}",
                    "node_id": node_id,
                    "axis": "n/a",
                    "node_config": "n/a",
                    "pos_kp": "n/a",
                    "pos_ki": "n/a",
                    "pos_kd": "n/a",
                    "ramp_down_slope": "n/a",
                    "ramp_down_step": "n/a",
                    "ramp_down_min_velocity": "n/a",
                    "ramp_down_target_offset": "n/a",
                    "ramp_down_region": "n/a",
                },
            )
            entries.append(entry)
        return entries

    def _open_motor_movement_popup(self) -> None:
        if self._movement_popup is None:
            self._movement_popup = MotorMovementControlPopup(self, self._node_entries)
            self._bind_movement_popup()
        else:
            self._movement_popup.set_node_options(self._node_entries)
        self._sync_movement_popup_selection_from_page()
        self._sync_movement_popup_controls()
        self._movement_popup.show()
        self._movement_popup.raise_()
        self._movement_popup.activateWindow()
        self._append_log("Opened Motor Movement Control popup.")

    def _bind_movement_popup(self) -> None:
        popup = self._movement_popup
        if popup is None or getattr(popup, "_mechanical_bound", False):
            return
        popup.node_combo.currentIndexChanged.connect(self._handle_popup_node_changed)
        popup.run_positive_button.clicked.connect(self._handle_popup_run_positive_clicked)
        popup.run_negative_button.clicked.connect(self._handle_popup_run_negative_clicked)
        popup.stop_button.clicked.connect(self._handle_popup_stop_clicked)
        popup._mechanical_bound = True

    def _handle_popup_node_changed(self) -> None:
        node_id = self._popup_selected_node_id()
        if node_id is not None:
            self._set_selected_node_id(node_id)
        self._sync_movement_popup_controls()

    def _handle_popup_run_positive_clicked(self) -> None:
        popup = self._movement_popup
        if popup is None:
            return
        velocity = abs(int(popup.pwm_input.value()))
        self._send_popup_run_command(velocity)

    def _handle_popup_run_negative_clicked(self) -> None:
        popup = self._movement_popup
        if popup is None:
            return
        velocity = -abs(int(popup.pwm_input.value()))
        self._send_popup_run_command(velocity)

    def _handle_popup_stop_clicked(self) -> None:
        self._cancel_release_watch("stop")
        node_id = self._popup_selected_node_id()
        if node_id is None or not self._has_supported_live_node_id(node_id):
            self._append_log("[Mechanical] Stop failed: no valid connected Mechanical node is selected.")
            return
        self._set_selected_node_id(node_id)
        adapter = self._ensure_transport_adapter(node_id)
        if adapter is None:
            self._append_log("[Mechanical] Stop failed: serial transport is unavailable.")
            return
        adapter.send(build_stopmotor())
        self._append_log(f"[Mechanical] Stop sent for Node {node_id:02d}.")

    def _send_popup_run_command(self, velocity: int) -> None:
        node_id = self._popup_selected_node_id()
        if node_id is None or not self._has_supported_live_node_id(node_id):
            self._append_log("[Mechanical] Run failed: no valid connected Mechanical node is selected.")
            return
        self._set_selected_node_id(node_id)
        adapter = self._ensure_transport_adapter(node_id)
        if adapter is None:
            self._append_log("[Mechanical] Run failed: serial transport is unavailable.")
            return
        adapter.send(build_run(int(velocity)))
        direction = "+" if int(velocity) > 0 else "-"
        self._append_log(f"[Mechanical] Run {direction} sent for Node {node_id:02d} at {abs(int(velocity))}.")
        self._maybe_start_release_watch_for_run(node_id, int(velocity))

    def _maybe_start_release_watch_for_run(self, node_id: int, velocity: int) -> None:
        if self._release_watch_helper.is_active:
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: duplicate watch already active.")
            return
        expected_sensor = self._release_watch_sensor_for_run(node_id, velocity)
        if expected_sensor is None:
            return
        started = self._release_watch_helper.start_release_watch(
            int(node_id),
            expected_sensor,
            lambda payload: self._send_release_watch_query(int(node_id), payload),
            on_released=self._handle_release_watch_released,
            on_timeout=self._handle_release_watch_timeout,
            on_stopped=self._handle_release_watch_stopped,
        )
        if started:
            self._append_log(
                f"[Mechanical] Release-watch started for Node {int(node_id):02d} sensor {expected_sensor}."
            )

    def _release_watch_sensor_for_run(self, node_id: int, velocity: int) -> str | None:
        if velocity == 0:
            return None
        interrupt_state = self._runtime_interrupt_state_for_node(node_id)
        left_cut = interrupt_state.get("left_cut")
        right_cut = interrupt_state.get("right_cut")
        if left_cut is None or right_cut is None:
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: interrupt state is incomplete.")
            return None
        if left_cut is True and right_cut is True:
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: both sensors are cut.")
            return None
        if left_cut is False and right_cut is False:
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: no cut sensor is active.")
            return None

        polarity = self._bridge.get_runtime_node_motion_polarity(node_id, create_if_missing=False)
        if not bool(polarity.get("known")):
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: NODECONFIG mapping is unknown.")
            return None

        toward_sensor = polarity.get("positive_run_sensor") if velocity > 0 else polarity.get("negative_run_sensor")
        if toward_sensor not in {"L", "R"}:
            self._append_log(f"[Mechanical] Release-watch skipped for Node {node_id:02d}: RUN direction mapping is unknown.")
            return None

        cut_sensor = "L" if left_cut is True else "R"
        if toward_sensor == cut_sensor:
            self._append_log(
                f"[Mechanical] Release-watch skipped for Node {node_id:02d}: RUN sign moves toward cut sensor {cut_sensor}."
            )
            return None
        return cut_sensor

    def _send_release_watch_query(self, node_id: int, payload: list[int]) -> None:
        adapter = self._ensure_transport_adapter(int(node_id))
        if adapter is None:
            return
        adapter.send(list(payload))

    def _cancel_release_watch(self, reason: str) -> None:
        self._release_watch_helper.stop_release_watch(str(reason))

    def _handle_release_watch_released(self, node_id: int, sensor: str) -> None:
        self._append_log(f"[Mechanical] Release detected for Node {node_id:02d} sensor {sensor}.")

    def _handle_release_watch_timeout(self, node_id: int, sensor: str) -> None:
        self._append_log(f"[Mechanical] Release-watch timeout for Node {node_id:02d} sensor {sensor}.")

    def _handle_release_watch_stopped(self, node_id: int, sensor: str, reason: str) -> None:
        if reason in {"released", "timeout"}:
            return
        self._append_log(
            f"[Mechanical] Release-watch cancelled for Node {node_id:02d} sensor {sensor} ({reason})."
        )

    def _sync_movement_popup_selection_from_page(self) -> None:
        popup = self._movement_popup
        node_id = self._selected_node_id()
        if popup is None or node_id is None:
            return
        popup.node_combo.blockSignals(True)
        try:
            for index in range(popup.node_combo.count()):
                data = popup.node_combo.itemData(index)
                if isinstance(data, dict) and int(data.get("node_id", -1)) == int(node_id):
                    popup.node_combo.setCurrentIndex(index)
                    break
        finally:
            popup.node_combo.blockSignals(False)

    def _popup_selected_node_id(self) -> int | None:
        popup = self._movement_popup
        if popup is None:
            return None
        return popup._current_node_id()

    def _set_selected_node_id(self, node_id: int) -> None:
        current = self._selected_node_id()
        if current == int(node_id):
            return
        self.node_combo.blockSignals(True)
        try:
            for index in range(self.node_combo.count()):
                data = self.node_combo.itemData(index)
                if isinstance(data, dict) and int(data.get("node_id", -1)) == int(node_id):
                    self.node_combo.setCurrentIndex(index)
                    break
        finally:
            self.node_combo.blockSignals(False)
        self._handle_selected_node_changed()

    def _sync_movement_popup_controls(self) -> None:
        popup = self._movement_popup
        if popup is None:
            return
        enabled = False
        node_id = self._popup_selected_node_id()
        if node_id is not None:
            enabled = self._has_supported_live_node_id(node_id)
        popup.run_positive_button.setEnabled(enabled)
        popup.run_negative_button.setEnabled(enabled)
        popup.stop_button.setEnabled(enabled)

    def _has_supported_live_node_id(self, node_id: int | None) -> bool:
        if node_id is None or not (MIN_TESTABLE_NODE_ID <= int(node_id) <= MAX_TESTABLE_NODE_ID):
            return False
        connected = False
        if hasattr(self._bridge, "get_runtime_connection_state"):
            serial_connected, _mcu_connected = self._bridge.get_runtime_connection_state(create_if_missing=False)
            connected = bool(serial_connected)
        else:
            runtime_window = self._bridge.get_runtime_window(create_if_missing=False)
            backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
            connected = bool(backend_client and backend_client.is_connected())
        return connected

    def _clear_log(self) -> None:
        self.log_output.clear()

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def _handle_get_position_clicked(self) -> None:
        self._start_simple_read(
            "Get Position",
            build_getpos(),
            expected_cmd=0x82,
            button=self.get_position_button,
            pending_button_text="Reading...",
        )

    def _handle_read_nodeconfig_clicked(self) -> None:
        self._start_simple_read(
            "Read NODECONFIG",
            build_nodeconfig_query_payload(),
            expected_cmd=0xC4,
            button=self.read_nodeconfig_button,
            pending_button_text="Reading...",
        )

    def _handle_read_lflag_clicked(self) -> None:
        self._start_simple_read(
            "Read LFLAG",
            build_lflag_query_payload(),
            expected_cmd=0xC9,
            button=self.read_lflag_button,
            pending_button_text="Reading...",
        )

    def _handle_read_rflag_clicked(self) -> None:
        self._start_simple_read(
            "Read RFLAG",
            build_rflag_query_payload(),
            expected_cmd=0xCA,
            button=self.read_rflag_button,
            pending_button_text="Reading...",
        )

    def _handle_read_pwm_clicked(self) -> None:
        self._start_parameter_read(
            "Read PWM",
            [self._parameter_definitions["PWM"]],
            button=self.read_pwm_button,
            pending_button_text="Reading...",
        )

    def _handle_set_pwm_clicked(self) -> None:
        selected_text = self.selected_pwm_combo.currentText().strip()
        try:
            parsed = parse_pwm_value(selected_text)
        except ValueError as exc:
            self._append_log(f"[Mechanical] Set PWM rejected: {exc}")
            return
        definition = self._parameter_definitions["PWM"]
        request = self._build_parameter_request(definition, str(parsed))
        self._start_parameter_write(
            "Set PWM",
            [request],
            enable_eeprom=False,
            button=self.set_pwm_row_button,
            pending_button_text="Writing...",
        )

    def _handle_pid_read_clicked(self) -> None:
        self._start_parameter_read(
            "Read PID",
            [
                self._parameter_definitions["PID_P"],
                self._parameter_definitions["PID_I"],
                self._parameter_definitions["PID_D"],
            ],
            button=self.pid_read_button,
            pending_button_text="Reading...",
        )

    def _handle_pid_write_clicked(self) -> None:
        try:
            requests = self._filter_requests_needing_write(self._build_pid_requests())
        except ValueError as exc:
            self._append_log(f"[Mechanical] Write PID rejected: {exc}")
            return
        if not requests:
            self._append_log("[Mechanical] PID write skipped: no values differ from current read-back.")
            return
        self._start_parameter_write(
            "Write PID",
            requests,
            enable_eeprom=True,
            button=self.pid_write_button,
            pending_button_text="Writing...",
        )

    def _handle_ramp_read_clicked(self) -> None:
        self._start_parameter_read(
            "Read Ramp Down",
            [
                self._parameter_definitions["RampDown_Slope"],
                self._parameter_definitions["RampDown_Step"],
                self._parameter_definitions["RampDown_MinVel"],
                self._parameter_definitions["RampDown_TargetOffset"],
                self._parameter_definitions["RampDown_Region"],
            ],
            button=self.ramp_read_button,
            pending_button_text="Reading...",
        )

    def _handle_ramp_write_clicked(self) -> None:
        try:
            requests = self._filter_requests_needing_write(self._build_ramp_requests())
        except ValueError as exc:
            self._append_log(f"[Mechanical] Write Ramp Down rejected: {exc}")
            return
        if not requests:
            self._append_log("[Mechanical] Ramp Down write skipped: no values differ from current read-back.")
            return
        self._start_parameter_write(
            "Write Ramp Down",
            requests,
            enable_eeprom=True,
            button=self.ramp_write_button,
            pending_button_text="Writing...",
        )

    def _handle_save_to_eeprom_clicked(self) -> None:
        if not self._persistent_write_pending:
            self._append_log("[Mechanical] Save to EEPROM ignored: no persistent writes are pending.")
            return
        if self._pending_request is not None:
            self._append_log("Another Mechanical request is still pending.")
            return
        node_id = self._selected_node_id()
        node_name = self._selected_node_label()
        if node_id is None or node_name is None:
            self._append_log("[Mechanical] Save to EEPROM failed: no valid node is selected.")
            return
        self._set_pending_request(
            _PendingMechanicalRequest(
                family="eeprom",
                action="save",
                node_id=node_id,
                timeout_owner="eeprom",
                button=self.save_to_eeprom_button,
                idle_button_text=self.save_to_eeprom_button.text(),
                pending_button_text="Saving...",
            ),
            message="[Mechanical] Save to EEPROM started.",
        )
        started = self._parameter_controller.save_parameters_to_eeprom(node_id, node_name)
        if not started:
            self._append_log("[Mechanical] Save to EEPROM failed to start.")
            self._clear_pending_request(family="eeprom", action="save")

    def _start_simple_read(
        self,
        name: str,
        payload: list[int],
        *,
        expected_cmd: int,
        button: QPushButton,
        pending_button_text: str,
    ) -> None:
        if self._pending_request is not None:
            self._append_log("Another Mechanical request is still pending.")
            return
        node_id = self._selected_node_id()
        if node_id is None or not self._has_supported_live_node():
            self._append_log(f"[Mechanical] {name} failed: no valid connected Mechanical node is selected.")
            return
        adapter = self._ensure_transport_adapter(node_id)
        if adapter is None:
            self._append_log(f"[Mechanical] {name} failed: serial transport is unavailable.")
            return
        self._set_pending_request(
            _PendingMechanicalRequest(
                family="simple_read",
                action=name,
                node_id=node_id,
                timeout_owner=name,
                button=button,
                idle_button_text=button.text(),
                pending_button_text=pending_button_text,
                expected_cmd=expected_cmd,
            ),
            message=f"[Mechanical] {name} started.",
        )
        adapter.send(payload)
        self._simple_request_timer.start(UUID_VERIFY_TIMEOUT_MS)

    def _handle_transport_payload(self, payload: list[int]) -> None:
        if not payload:
            return
        pending = self._pending_request
        if pending is None:
            return
        if pending.family == "simple_read":
            self._handle_simple_read_payload(payload)
            return
        if pending.family == "parameter":
            self._handle_parameter_payload(payload)
            return

    def _handle_simple_read_payload(self, payload: list[int]) -> None:
        pending = self._pending_request
        if pending is None or pending.family != "simple_read" or pending.expected_cmd is None:
            return
        cmd = int(payload[0]) & 0xFF
        if cmd != pending.expected_cmd:
            return
        self._simple_request_timer.stop()
        decoded_type, decoded_value = decode_command(cmd, payload[1:])
        if pending.action == "Get Position":
            self._handle_get_position_response(decoded_type, decoded_value, payload)
        elif pending.action == "Read NODECONFIG":
            self._handle_nodeconfig_response(decoded_type, decoded_value, payload)
        elif pending.action == "Read LFLAG":
            self._handle_flag_response(decoded_type, decoded_value, payload, side="left")
        elif pending.action == "Read RFLAG":
            self._handle_flag_response(decoded_type, decoded_value, payload, side="right")
        self._clear_pending_request(family="simple_read", action=pending.action)

    def _handle_parameter_payload(self, payload: list[int]) -> None:
        pending = self._pending_request
        if pending is None or pending.family != "parameter":
            return
        cmd = int(payload[0]) & 0xFF
        if pending.action == "read":
            definitions = list(pending.definitions or [])
            index = int(pending.index)
            if index >= len(definitions):
                return
            definition = definitions[index]
            if definition.decode_response is None:
                return
            decoded_ok, actual_value, error = definition.decode_response(payload)
            if not decoded_ok:
                return
            self._simple_request_timer.stop()
            actual_text = definition.format_actual(actual_value, self._current_parameter_display_text(definition.name))
            self._parameter_actual_texts[definition.name] = actual_text
            self._apply_parameter_actual_text(definition.name, actual_text)
            self._append_log(
                f"[Mechanical] Parsed {definition.label} RX: {self._hex_payload(payload)} -> {actual_text}."
            )
            pending.results = list(pending.results or [])
            pending.results.append((definition.name, True, "", actual_text))
            pending.index = index + 1
            adapter = self._ensure_transport_adapter(pending.node_id)
            if pending.index >= len(definitions):
                self._append_log(f"[Mechanical] {self._parameter_label(pending)} completed.")
                self._clear_pending_request(family="parameter", action="read")
                return
            if adapter is not None:
                self._send_next_parameter_read(adapter)
            return

        requests = list(pending.requests or [])
        index = int(pending.index)
        if index >= len(requests):
            return
        request = requests[index]
        definition = request.definition
        if definition.decode_response is None:
            return
        decoded_ok, actual_value, error = definition.decode_response(payload)
        if not decoded_ok:
            return
        self._simple_request_timer.stop()
        actual_text = definition.format_actual(actual_value, request.expected_text)
        normalized_expected_value = request.expected_value
        normalized_actual_value = actual_value
        if pending.action == "write":
            self._append_log(
                f"[Mechanical] {definition.label} write ACK: {self._hex_payload(payload)}."
            )
            pending.index = index + 1
            adapter = self._ensure_transport_adapter(pending.node_id)
            if pending.index >= len(requests):
                self._append_log(f"[Mechanical] {self._parameter_label(pending)} write ACKs completed.")
                pending.action = "verify_after_write"
                pending.index = 0
                if adapter is not None:
                    self._send_next_parameter_verify(adapter)
                return
            if adapter is not None:
                self._send_next_parameter_write(adapter)
            return

        if definition.parse_expected is not None:
            try:
                normalized_actual_value = definition.parse_expected(actual_text)
            except Exception:
                normalized_actual_value = actual_value
        passed = definition.compare(normalized_expected_value, request.expected_text, normalized_actual_value, actual_text)
        self._parameter_actual_texts[definition.name] = actual_text
        self._apply_parameter_actual_text(definition.name, actual_text)
        self._append_log(
            f"[Mechanical] {definition.label}: requested {request.expected_text}, read-back {actual_text}, "
            f"{'PASS' if passed else 'FAIL'}."
        )
        pending.results = list(pending.results or [])
        pending.results.append(
            ParameterVerificationResult(
                definition=definition,
                expected_text=request.expected_text,
                actual_text=actual_text,
                passed=passed,
                reason=(
                    f"{definition.label} read-back verification"
                    if passed
                    else f"{definition.label} read-back verification - expected {request.expected_text}, actual {actual_text}"
                ),
            )
        )
        pending.index = index + 1
        adapter = self._ensure_transport_adapter(pending.node_id)
        if pending.index >= len(requests):
            all_passed = all(result.passed for result in (pending.results or []) if isinstance(result, ParameterVerificationResult))
            if all_passed and pending.enable_eeprom:
                self._persistent_write_pending = True
                self.save_to_eeprom_button.setEnabled(self._has_supported_live_node())
            self._append_log(
                f"[Mechanical] {self._parameter_label(pending)} {'completed' if all_passed else 'completed with verification failures'}."
            )
            self._clear_pending_request(family="parameter", action="verify_after_write")
            return
        if adapter is not None:
            self._send_next_parameter_verify(adapter)

    def _handle_get_position_response(self, decoded_type: Any, decoded_value: Any, payload: list[int]) -> None:
        if decoded_type != "getpos" or not isinstance(decoded_value, tuple) or len(decoded_value) != 2:
            self._append_log(f"[Mechanical] Get Position failed: unexpected response {self._hex_payload(payload)}.")
            return
        _tag, position = decoded_value
        self.current_position_value.setText(str(position))
        self._append_log(f"[Mechanical] Parsed Get Position RX: {self._hex_payload(payload)} -> {position} counts.")

    def _handle_nodeconfig_response(self, decoded_type: Any, decoded_value: Any, payload: list[int]) -> None:
        if decoded_type != "nodeconfig" or not isinstance(decoded_value, int):
            self._append_log(f"[Mechanical] Read NODECONFIG failed: unexpected response {self._hex_payload(payload)}.")
            return
        formatted = self._format_nodeconfig_bits(decoded_value)
        self._apply_nodeconfig_display(decoded_value)
        self._append_log(f"[Mechanical] Parsed Read NODECONFIG RX: {self._hex_payload(payload)} -> {formatted}.")

    def _handle_flag_response(self, decoded_type: Any, decoded_value: Any, payload: list[int], *, side: str) -> None:
        if decoded_type not in {"lflag", "rflag"} or not isinstance(decoded_value, int):
            self._append_log(f"[Mechanical] Read {side.upper()}FLAG failed: unexpected response {self._hex_payload(payload)}.")
            return
        selected_node_id = self._selected_node_id()
        pending_node_id = self._pending_request.node_id if self._pending_request is not None else None
        if pending_node_id is None or selected_node_id != pending_node_id:
            self._append_log(f"[Mechanical] Ignored Read {side.upper()}FLAG RX for stale node context {pending_node_id!r}.")
            return
        self._sensor_state_node_id = pending_node_id
        self._sensor_state_cache[side] = decoded_value & 0xFF
        self._render_sensor_state()
        self._append_log(
            f"[Mechanical] Parsed Read {side.upper()}FLAG RX: {self._hex_payload(payload)} -> 0x{decoded_value:02X}."
        )

    def _handle_simple_request_timeout(self) -> None:
        pending = self._pending_request
        if pending is None:
            return
        if pending.family == "simple_read":
            self._append_log(f"[Mechanical] {pending.action} timed out waiting for Node {pending.node_id:02d}.")
            self._clear_pending_request(family="simple_read", action=pending.action)
            return
        if pending.family == "parameter":
            label = self._parameter_label(pending)
            self._append_log(f"[Mechanical] {label} timed out waiting for a response.")
            self._clear_pending_request(family="parameter", action=pending.action)

    def _send_next_parameter_read(self, adapter: FunctionalTransportAdapter) -> None:
        pending = self._pending_request
        if pending is None or pending.family != "parameter":
            return
        definitions = list(pending.definitions or [])
        index = int(pending.index)
        if index >= len(definitions):
            self._clear_pending_request(family="parameter")
            return
        definition = definitions[index]
        payload = definition.build_read_command() if definition.build_read_command is not None else []
        if not payload:
            self._append_log(f"[Mechanical] {definition.label} read is unavailable.")
            pending.index = index + 1
            self._send_next_parameter_read(adapter)
            return
        adapter.send(payload)
        self._simple_request_timer.start(UUID_VERIFY_TIMEOUT_MS)

    def _send_next_parameter_write(self, adapter: FunctionalTransportAdapter) -> None:
        pending = self._pending_request
        if pending is None or pending.family != "parameter":
            return
        requests = list(pending.requests or [])
        index = int(pending.index)
        if index >= len(requests):
            self._clear_pending_request(family="parameter")
            return
        request = requests[index]
        definition = request.definition
        payload = definition.build_write_command(request.expected_value) if definition.build_write_command is not None else []
        if not payload:
            self._append_log(f"[Mechanical] {definition.label} write is unavailable.")
            self._clear_pending_request(family="parameter")
            return
        adapter.send(payload)
        self._simple_request_timer.start(UUID_VERIFY_TIMEOUT_MS)

    def _send_next_parameter_verify(self, adapter: FunctionalTransportAdapter) -> None:
        pending = self._pending_request
        if pending is None or pending.family != "parameter":
            return
        requests = list(pending.requests or [])
        index = int(pending.index)
        if index >= len(requests):
            self._clear_pending_request(family="parameter")
            return
        request = requests[index]
        definition = request.definition
        payload = definition.build_read_command() if definition.build_read_command is not None else []
        if not payload:
            self._append_log(f"[Mechanical] {definition.label} read-back is unavailable.")
            self._clear_pending_request(family="parameter")
            return
        adapter.send(payload)
        self._simple_request_timer.start(UUID_VERIFY_TIMEOUT_MS)

    def _start_parameter_read(
        self,
        label: str,
        definitions: list[Any],
        *,
        button: QPushButton,
        pending_button_text: str,
    ) -> None:
        if self._pending_request is not None:
            self._append_log("Another Mechanical request is still pending.")
            return
        if not self._has_supported_live_node():
            self._append_log(f"[Mechanical] {label} failed: no valid connected Mechanical node is selected.")
            return
        node_id = self._selected_node_id()
        adapter = self._ensure_transport_adapter(node_id) if node_id is not None else None
        if adapter is None:
            self._append_log(f"[Mechanical] {label} failed: serial transport is unavailable.")
            return
        self._set_pending_request(
            _PendingMechanicalRequest(
                family="parameter",
                action="read",
                node_id=int(node_id),
                timeout_owner=label,
                button=button,
                idle_button_text=button.text(),
                pending_button_text=pending_button_text,
                definitions=list(definitions),
                results=[],
            ),
            message=f"[Mechanical] {label} started.",
        )
        self._send_next_parameter_read(adapter)

    def _start_parameter_write(
        self,
        label: str,
        requests: list[ParameterRequest],
        *,
        enable_eeprom: bool,
        button: QPushButton,
        pending_button_text: str,
    ) -> None:
        if self._pending_request is not None:
            self._append_log("Another Mechanical request is still pending.")
            return
        if not self._has_supported_live_node():
            self._append_log(f"[Mechanical] {label} failed: no valid connected Mechanical node is selected.")
            return
        node_id = self._selected_node_id()
        adapter = self._ensure_transport_adapter(node_id) if node_id is not None else None
        if adapter is None:
            self._append_log(f"[Mechanical] {label} failed: serial transport is unavailable.")
            return
        self._set_pending_request(
            _PendingMechanicalRequest(
                family="parameter",
                action="write",
                node_id=int(node_id),
                timeout_owner=label,
                button=button,
                idle_button_text=button.text(),
                pending_button_text=pending_button_text,
                requests=list(requests),
                results=[],
                enable_eeprom=enable_eeprom,
            ),
            message=f"[Mechanical] {label} started.",
        )
        self._send_next_parameter_write(adapter)

    def _on_parameter_write_finished(self, success: bool, message: str) -> None:
        return

    def _on_parameter_verification_finished(
        self,
        success: bool,
        reason: str,
        results: object,
    ) -> None:
        return

    def _on_eeprom_save_finished(self, success: bool, message: str) -> None:
        self._append_log(f"[Mechanical] {message}")
        if success:
            self._persistent_write_pending = False
        if self._pending_request is not None and self._pending_request.family == "eeprom":
            self._clear_pending_request(family="eeprom", action="save")

    def _build_pid_requests(self) -> list[ParameterRequest]:
        return [
            self._build_parameter_request(self._parameter_definitions["PID_P"], self.pid_p_value.text()),
            self._build_parameter_request(self._parameter_definitions["PID_I"], self.pid_i_value.text()),
            self._build_parameter_request(self._parameter_definitions["PID_D"], self.pid_d_value.text()),
        ]

    def _build_ramp_requests(self) -> list[ParameterRequest]:
        return [
            self._build_parameter_request(self._parameter_definitions["RampDown_Slope"], self.ramp_slope_value.text()),
            self._build_parameter_request(self._parameter_definitions["RampDown_Step"], self.ramp_step_value.text()),
            self._build_parameter_request(self._parameter_definitions["RampDown_MinVel"], self.ramp_min_velocity_value.text()),
            self._build_parameter_request(self._parameter_definitions["RampDown_TargetOffset"], self.ramp_target_offset_value.text()),
            self._build_parameter_request(self._parameter_definitions["RampDown_Region"], self.ramp_region_value.text()),
        ]

    def _build_parameter_request(self, definition, expected_text: str) -> ParameterRequest:
        node_id = self._selected_node_id()
        node_name = self._selected_node_label() or "Node"
        if node_id is None:
            raise ValueError("No valid node is selected.")
        text = str(expected_text).strip()
        expected_value = definition.parse_expected(text)
        return ParameterRequest(
            definition=definition,
            node_id=int(node_id),
            node_name=str(node_name),
            expected_text=text,
            expected_value=expected_value,
        )

    def _filter_requests_needing_write(self, requests: list[ParameterRequest]) -> list[ParameterRequest]:
        filtered: list[ParameterRequest] = []
        for request in requests:
            cached_actual = self._parameter_actual_texts.get(request.definition.name)
            if cached_actual is None or cached_actual != request.expected_text:
                filtered.append(request)
        return filtered

    def _apply_parameter_actual_text(self, name: str, actual_text: str) -> None:
        widget_map = {
            "PWM": self.current_pwm_value,
            "PID_P": self.pid_p_value,
            "PID_I": self.pid_i_value,
            "PID_D": self.pid_d_value,
            "RampDown_Slope": self.ramp_slope_value,
            "RampDown_Step": self.ramp_step_value,
            "RampDown_MinVel": self.ramp_min_velocity_value,
            "RampDown_TargetOffset": self.ramp_target_offset_value,
            "RampDown_Region": self.ramp_region_value,
        }
        widget = widget_map.get(name)
        if widget is not None:
            widget.setText(actual_text)

    def _current_parameter_display_text(self, name: str) -> str:
        widget_map = {
            "PWM": self.current_pwm_value,
            "PID_P": self.pid_p_value,
            "PID_I": self.pid_i_value,
            "PID_D": self.pid_d_value,
            "RampDown_Slope": self.ramp_slope_value,
            "RampDown_Step": self.ramp_step_value,
            "RampDown_MinVel": self.ramp_min_velocity_value,
            "RampDown_TargetOffset": self.ramp_target_offset_value,
            "RampDown_Region": self.ramp_region_value,
        }
        widget = widget_map.get(name)
        if widget is None:
            return self._parameter_actual_texts.get(name, "0")
        return widget.text().strip() or self._parameter_actual_texts.get(name, "0")

    def _reset_sensor_state(self) -> None:
        self._sensor_state_node_id = self._selected_node_id()
        self._sensor_state_cache = {"left": None, "right": None}

    def _render_sensor_state(self) -> None:
        selected_node_id = self._selected_node_id()
        if self._sensor_state_node_id != selected_node_id:
            self._sensor_state_cache = {"left": None, "right": None}
            self._sensor_state_node_id = selected_node_id
        self._apply_sensor_value("left", self.left_flag_led, self.left_flag_state_value, self.left_flag_setting_selector)
        self._apply_sensor_value("right", self.right_flag_led, self.right_flag_state_value, self.right_flag_setting_selector)

    def _apply_sensor_value(
        self,
        side: str,
        led: QLabel,
        state_value: QLineEdit,
        setting_selector: QComboBox,
    ) -> None:
        raw_value = self._sensor_state_cache.get(side)
        sensor_state = self._sensor_display_from_raw(raw_value)
        led_state = self._sensor_led_state(side)
        state_value.setText(sensor_state["text"])
        led.setStyleSheet(f"border-radius: 6px; background: {led_state['color']};")
        if raw_value is not None and str(raw_value) in {"1", "9", "11"}:
            setting_selector.setCurrentText(str(raw_value))

    @staticmethod
    def _sensor_display_from_raw(raw_value: int | None) -> dict[str, Any]:
        if raw_value is None:
            return {"text": "unknown"}
        return {"text": f"0x{int(raw_value) & 0xFF:02X}"}

    def _sensor_led_state(self, side: str) -> dict[str, Any]:
        interrupt_state = self._selected_runtime_interrupt_state()
        is_cut = interrupt_state.get(f"{side}_cut")
        return {
            "color": "#F39C12" if is_cut is True else "#777777",
            "active": is_cut is True,
            "known": is_cut is not None,
        }

    def _selected_runtime_interrupt_state(self) -> dict[str, object]:
        selected_node_id = self._selected_node_id()
        if selected_node_id is None:
            return {
                "left_cut": None,
                "right_cut": None,
                "int0": None,
                "int1": None,
                "last_source": None,
            }
        return self._runtime_interrupt_state_for_node(selected_node_id)

    def _runtime_interrupt_state_for_node(self, node_id: int) -> dict[str, object]:
        return self._bridge.get_runtime_node_interrupt_state(int(node_id), create_if_missing=False)

    def _attach_runtime_packet_listener(self) -> None:
        runtime_window = self._bridge.get_runtime_window(create_if_missing=False)
        if runtime_window is self._runtime_packet_window:
            return
        if self._runtime_packet_window is not None:
            try:
                self._runtime_packet_window.packet_received.disconnect(self._handle_runtime_packet_event)
            except (TypeError, RuntimeError):
                pass
        self._runtime_packet_window = runtime_window
        if runtime_window is not None and hasattr(runtime_window, "packet_received"):
            runtime_window.packet_received.connect(self._handle_runtime_packet_event)

    def _handle_runtime_packet_event(self, packet: object) -> None:
        if not isinstance(packet, dict):
            return
        if packet.get("type") != "can_over_uart":
            return
        selected_node_id = self._selected_node_id()
        sender = packet.get("sender")
        if selected_node_id is None or sender is None:
            return
        sender_id = int(sender)
        if sender_id != selected_node_id:
            pending = self._pending_request
            if pending is not None and pending.family == "simple_read":
                raw_cmd = int(packet.get("cmd", -1))
                raw_params = [int(value) & 0xFF for value in list(packet.get("params") or [])]
                raw_hex = " ".join(f"{value:02X}" for value in [raw_cmd, *raw_params])
                self._append_log(f"ignored packet: node={sender_id}, payload={raw_hex}, reason=wrong node {sender_id}")
            return
        if int(packet.get("cmd", 0)) & 0xFF not in (0x81, 0xD8):
            return
        QTimer.singleShot(0, self._render_sensor_state)

    def closeEvent(self, event) -> None:
        self._cancel_release_watch("page_closed")
        super().closeEvent(event)

    def _align_top_card_heights(self) -> None:
        equal_height = max(self.node_header_panel.sizeHint().height(), self.sensor_panel.sizeHint().height())
        self.node_header_panel.setMinimumHeight(equal_height)
        self.sensor_panel.setMinimumHeight(equal_height)

    def _ensure_transport_adapter(self, node_id: int) -> FunctionalTransportAdapter | None:
        runtime_window = self._bridge.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return None
        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            return None
        if self._transport_adapter is None or self._transport_runtime_window is not runtime_window or self._transport_node_id != node_id:
            if self._transport_adapter is not None:
                self._transport_adapter.detach_runtime_window()
            self._transport_adapter = FunctionalTransportAdapter(
                backend_client,
                node_id=node_id,
                tx_logger=self._append_log,
                rx_logger=self._append_log,
                controller_handler=self._handle_transport_payload,
            )
            self._transport_adapter.attach_runtime_window(runtime_window)
            self._transport_runtime_window = runtime_window
            self._transport_node_id = node_id
        return self._transport_adapter

    def _has_supported_live_node(self) -> bool:
        node_id = self._selected_node_id()
        if node_id is None or not (MIN_TESTABLE_NODE_ID <= node_id <= MAX_TESTABLE_NODE_ID):
            return False
        connected = False
        if hasattr(self._bridge, "get_runtime_connection_state"):
            serial_connected, _mcu_connected = self._bridge.get_runtime_connection_state(create_if_missing=False)
            connected = bool(serial_connected)
        else:
            runtime_window = self._bridge.get_runtime_window(create_if_missing=False)
            backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
            connected = bool(backend_client and backend_client.is_connected())
        return connected

    def _selected_node_label(self) -> str | None:
        entry = self._selected_node_entry()
        if entry is None:
            return None
        return str(entry.get("label", f"Node {entry.get('node_id', '?')}"))

    def _parameter_label(self, pending: _PendingMechanicalRequest) -> str:
        if pending.family != "parameter":
            return pending.timeout_owner
        requests = pending.requests or []
        definitions = pending.definitions or []
        if requests:
            names = {request.definition.name for request in requests}
        else:
            names = {definition.name for definition in definitions}
        if names == {"PWM"}:
            return "Set PWM" if pending.action in {"write", "verify_after_write"} else "Read PWM"
        if names == {"PID_P", "PID_I", "PID_D"}:
            return "Write PID" if pending.action in {"write", "verify_after_write"} else "Read PID"
        if names == {"RampDown_Slope", "RampDown_Step", "RampDown_MinVel", "RampDown_TargetOffset", "RampDown_Region"}:
            return "Write Ramp Down" if pending.action in {"write", "verify_after_write"} else "Read Ramp Down"
        return pending.timeout_owner

    def _set_pending_request(self, pending: _PendingMechanicalRequest, *, message: str) -> None:
        self._pending_request = pending
        self._apply_pending_button_state(pending, is_pending=True)
        self._append_log(message)

    def _clear_pending_request(self, *, family: str | None = None, action: str | None = None) -> None:
        pending = self._pending_request
        if pending is None:
            return
        if family is not None and pending.family != family:
            return
        if action is not None and pending.action != action:
            return
        self._simple_request_timer.stop()
        self._apply_pending_button_state(pending, is_pending=False)
        self._pending_request = None

    def _update_control_states(self) -> None:
        supported_live_node = self._has_supported_live_node()
        pending_button = self._pending_request.button if self._pending_request is not None else None
        if self.read_lflag_button is not pending_button:
            self.read_lflag_button.setEnabled(supported_live_node)
        if self.read_rflag_button is not pending_button:
            self.read_rflag_button.setEnabled(supported_live_node)
        if self.read_nodeconfig_button is not pending_button:
            self.read_nodeconfig_button.setEnabled(supported_live_node)
        if self.read_pwm_button is not pending_button:
            self.read_pwm_button.setEnabled(supported_live_node)
        self.selected_pwm_combo.setEnabled(supported_live_node)
        if self.set_pwm_row_button is not pending_button:
            self.set_pwm_row_button.setEnabled(supported_live_node)
        if self.get_position_button is not pending_button:
            self.get_position_button.setEnabled(supported_live_node)
        if self.pid_read_button is not pending_button:
            self.pid_read_button.setEnabled(supported_live_node)
        if self.pid_write_button is not pending_button:
            self.pid_write_button.setEnabled(supported_live_node)
        if self.ramp_read_button is not pending_button:
            self.ramp_read_button.setEnabled(supported_live_node)
        if self.ramp_write_button is not pending_button:
            self.ramp_write_button.setEnabled(supported_live_node)
        if self.save_to_eeprom_button is not pending_button:
            self.save_to_eeprom_button.setEnabled(supported_live_node and self._persistent_write_pending)

    def _apply_pending_button_state(self, pending: _PendingMechanicalRequest, *, is_pending: bool) -> None:
        button = pending.button
        if button is None:
            return
        if is_pending:
            if pending.pending_button_text:
                button.setText(pending.pending_button_text)
            button.setEnabled(False)
            return
        if pending.idle_button_text is not None:
            button.setText(pending.idle_button_text)
        if button is self.save_to_eeprom_button:
            button.setEnabled(self._has_supported_live_node() and self._persistent_write_pending)
        else:
            button.setEnabled(self._has_supported_live_node())

    @staticmethod
    def _hex_payload(payload: list[int]) -> str:
        return " ".join(f"{int(value) & 0xFF:02X}" for value in payload)

    @staticmethod
    def _normalize_nodeconfig_value(value: Any) -> int | None:
        if isinstance(value, int):
            return value & 0x0F
        text = str(value).strip()
        if not text or text.lower() == "n/a":
            return None
        try:
            return int(text, 16) & 0x0F
        except ValueError:
            return None

    @classmethod
    def _format_nodeconfig_bits(cls, value: Any) -> str:
        normalized = cls._normalize_nodeconfig_value(value)
        if normalized is None:
            return "n/a"
        return f"{normalized:04b}"

    def _apply_nodeconfig_display(self, value: Any) -> None:
        normalized = self._normalize_nodeconfig_value(value)
        self._actual_nodeconfig_value = normalized
        self._pending_nodeconfig_value = normalized
        self._sync_nodeconfig_editor_widgets()

    def _handle_nodeconfig_editor_changed(self) -> None:
        if self._updating_nodeconfig_editor:
            return
        baseline = self._actual_nodeconfig_value
        if baseline is None:
            baseline = self._pending_nodeconfig_value if self._pending_nodeconfig_value is not None else 0
        pending = int(baseline) & 0x0C
        if self.flag_selector_selector.currentIndex() == 1:
            pending |= 0x01
        if self.polarity_selector.currentIndex() == 1:
            pending |= 0x02
        self._pending_nodeconfig_value = pending & 0x0F
        self._sync_nodeconfig_editor_widgets(update_selectors=False)

    def _sync_nodeconfig_editor_widgets(self, *, update_selectors: bool = True) -> None:
        self.current_nodeconfig_value.setText(self._format_nodeconfig_bits(self._actual_nodeconfig_value))
        self.pending_nodeconfig_value.setText(self._format_nodeconfig_bits(self._pending_nodeconfig_value))
        is_unsaved = (
            self._actual_nodeconfig_value is not None
            and self._pending_nodeconfig_value is not None
            and self._actual_nodeconfig_value != self._pending_nodeconfig_value
        )
        self.nodeconfig_unsaved_indicator.setVisible(is_unsaved)
        if not update_selectors:
            return
        baseline = self._pending_nodeconfig_value
        if baseline is None:
            baseline = self._actual_nodeconfig_value if self._actual_nodeconfig_value is not None else 0
        self._updating_nodeconfig_editor = True
        try:
            self.flag_selector_selector.setCurrentIndex(1 if (int(baseline) & 0x01) else 0)
            self.polarity_selector.setCurrentIndex(1 if (int(baseline) & 0x02) else 0)
        finally:
            self._updating_nodeconfig_editor = False

    @staticmethod
    def _build_selector_row(title: str, selector: QComboBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(title)
        label.setObjectName("DetailValue")
        label.setMinimumWidth(118)
        row.addWidget(label)
        row.addWidget(selector, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch(1)
        return row

    @staticmethod
    def _equalize_button_widths(*buttons: QPushButton) -> None:
        width = max((button.minimumSizeHint().width() for button in buttons), default=0)
        for button in buttons:
            button.setMinimumWidth(width)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    @staticmethod
    def _style_enabled_button(button: QPushButton) -> None:
        button.setProperty("tone", "primary")
        button.setStyleSheet(
            "QPushButton {"
            " background: #FF9633;"
            " color: white;"
            " border: 1px solid #F18A2B;"
            " border-radius: 16px;"
            " font-size: 14px;"
            " font-weight: 600;"
            " padding: 8px 14px;"
            "}"
            "QPushButton:hover { background: #FA8D24; border: 1px solid #EC8119; }"
            "QPushButton:pressed { background: #E97F16; border: 1px solid #D77211; }"
            "QPushButton:focus { outline: none; border: 1px solid #D77211; }"
            "QPushButton:disabled {"
            " background: #FFF4EA;"
            " color: #C08854;"
            " border: 1px solid #F0D4BE;"
            "}"
        )

    @staticmethod
    def _style_disabled_button(button: QPushButton) -> None:
        MechanicalPage._style_enabled_button(button)

    @staticmethod
    def _configure_module_panel(panel: PanelFrame, *, min_width: int) -> None:
        panel.setProperty("surfaceTone", "config")
        panel.setMinimumWidth(min_width)
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        selector = panel.objectName() or "WorkspacePanel"
        panel.setStyleSheet(
            f"QFrame#{selector} {{"
            " background: rgba(255, 255, 255, 0.98);"
            " border: 1px solid #E6EBF1;"
            " border-radius: 18px;"
            "}"
            "QWidget { background: transparent; border: none; }"
            "QLabel#PanelTitle { color: #5A4C44; font-size: 15px; font-weight: 700; background: transparent; border: none; }"
            "QLabel#PanelSubtitle, QLabel#FieldLabel, QLabel#DetailValue { background: transparent; border: none; }"
        )

    @staticmethod
    def _build_sensor_row(
        title: str,
        led: QLabel,
        state_value: QLabel,
        setting_selector: QComboBox,
        write_button: QPushButton,
        *,
        row_object_name: str,
    ) -> QWidget:
        row_widget = QWidget()
        row_widget.setObjectName(row_object_name)
        row_layout = QGridLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setHorizontalSpacing(6)
        row_layout.setVerticalSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName(f"{row_object_name}Title")
        title_label.setMinimumWidth(92)
        title_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        state_label = QLabel("State:")
        state_label.setObjectName(f"{row_object_name}StateLabel")
        state_label.setMinimumWidth(34)
        setting_label = QLabel("Flag Setting:")
        setting_label.setObjectName(f"{row_object_name}SettingLabel")
        setting_label.setMinimumWidth(68)
        write_button.setMinimumWidth(max(write_button.minimumWidth(), 62))
        write_button.setMaximumWidth(74)
        write_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        row_layout.addWidget(led, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        row_layout.addWidget(title_label, 0, 1, 1, 5, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(state_label, 1, 1, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(state_value, 1, 2, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(setting_label, 1, 3, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(setting_selector, 1, 4, Qt.AlignmentFlag.AlignVCenter)
        row_layout.addWidget(write_button, 1, 5, Qt.AlignmentFlag.AlignVCenter)
        row_layout.setColumnStretch(4, 1)
        return row_widget

    @staticmethod
    def _style_combo_box(combo: QComboBox) -> None:
        combo.setMaxVisibleItems(10)
        combo.setStyleSheet(
            "QComboBox {"
            " background: #FFFFFF;"
            " color: #463A33;"
            " border: 1px solid #D7DEE7;"
            " border-radius: 12px;"
            " padding: 6px 28px 6px 10px;"
            " selection-background-color: #FFD7AE;"
            " selection-color: #463A33;"
            "}"
            "QComboBox:hover { border: 1px solid #C6D0DB; }"
            "QComboBox:focus { border: 1px solid #F18A2B; }"
            "QComboBox:disabled {"
            " background: #F6F1EB;"
            " color: #9A836E;"
            " border: 1px solid #E5D6C8;"
            "}"
            "QComboBox::drop-down { width: 26px; border: none; background: transparent; }"
            "QComboBox QAbstractItemView {"
            " background: #FFFFFF;"
            " color: #463A33;"
            " border: 1px solid #D7DEE7;"
            " outline: 0;"
            " padding: 4px;"
            " selection-background-color: #FFD7AE;"
            " selection-color: #463A33;"
            "}"
            "QComboBox QAbstractItemView::item { min-height: 24px; padding: 4px 8px; }"
            "QComboBox QAbstractItemView::item:hover { background: #FFE5C7; color: #463A33; }"
            "QComboBox QAbstractItemView::item:selected { background: #FFD7AE; color: #463A33; }"
        )

    @staticmethod
    def _readonly_line(text: str, object_name: str, *, width: int) -> QLineEdit:
        line = QLineEdit(text)
        line.setObjectName(object_name)
        line.setReadOnly(True)
        line.setMinimumWidth(width)
        line.setMaximumWidth(width + 24)
        return line

    @staticmethod
    def _readonly_display_label(text: str, object_name: str, *, width: int) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        label.setMinimumWidth(width)
        label.setMaximumWidth(width + 28)
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        label.setStyleSheet(
            "background: #F6F8FB;"
            " color: #463A33;"
            " border: 1px solid #DCE3EC;"
            " border-radius: 12px;"
            " padding: 6px 10px;"
        )
        return label

    @staticmethod
    def _editable_line(text: str, object_name: str, *, width: int) -> QLineEdit:
        line = QLineEdit(text)
        line.setObjectName(object_name)
        line.setReadOnly(False)
        line.setMinimumWidth(width)
        line.setMaximumWidth(width + 24)
        return line

    @staticmethod
    def _disabled_button(text: str, object_name: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setEnabled(False)
        button.setMinimumWidth(button.fontMetrics().horizontalAdvance(text) + 24)
        MechanicalPage._style_enabled_button(button)
        return button

    @staticmethod
    def _style_command_button(button: QPushButton) -> None:
        MechanicalPage._style_enabled_button(button)

    @staticmethod
    def _build_led(object_name: str) -> QLabel:
        led = QLabel()
        led.setObjectName(object_name)
        led.setFixedSize(12, 12)
        led.setFrameShape(QFrame.Shape.NoFrame)
        led.setStyleSheet("border-radius: 6px; background: #777777;")
        return led

    def _set_status_indicator(self, state: str) -> None:
        colors = {
            "neutral": "#777777",
            "connected": "#2ECC71",
            "warn": "#F39C12",
            "error": "#C0392B",
        }
        self.status_indicator.setStyleSheet(f"border-radius: 6px; background: {colors.get(state, '#777777')};")
