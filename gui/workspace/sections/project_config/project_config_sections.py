"""Section widgets used by the Project Config page."""

from __future__ import annotations

import yaml

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myconfig.config_models import ConfigEditorModel, ConfigFieldModel, ConfigSectionModel
from myconfig.version_utils import is_valid_version_text

from ...widgets import PanelFrame
from ...widgets.layout_utils import clear_layout

_MAX_COMPACT_FIELD_COLUMNS = 4
_AXIS_SUMMARY_KEYS = ("node_id", "node_type", "node_config", "fw_version")
_AXIS_DETAIL_GROUPS: list[tuple[str, tuple[str, ...], int]] = [
    (
        "Software limits",
        (
            "sw_standby_position",
            "sw_range_max",
            "sw_counts_per_unit",
            "sw_encodercount_max",
            "sw_standby_encodercount",
        ),
        3,
    ),
    (
        "Firmware safety",
        (
            "fw_safety_pwm_max",
            "fw_safety_velocity_max",
            "fw_safety_encodercount_max",
        ),
        3,
    ),
    (
        "Motor defaults",
        (
            "fw_motor_deadband_default",
            "fw_motor_pos_targetoffset",
        ),
        2,
    ),
    (
        "PID tuning",
        (
            "pos_kp",
            "pos_ki",
            "pos_kd",
            "vel_kp",
            "vel_ki",
            "vel_kd",
        ),
        3,
    ),
]
_MANUAL_ROTATE_KEYS = ("manual_rotate_feature", "manual_rotate_pwm", "manual_rotate_report_time")
_SENSOR_KEY_ORDER = ("node_id", "reverse")
_SENSOR_ITEMS_PER_ROW = 2
_DEFAULT_AXIS_GROUP_EXPANSION = {
    "Software Limits": True,
    "Firmware Safety": False,
    "Motor Defaults": False,
    "PID Tuning": False,
    "Manual Rotate": True,
    "Additional": False,
}
_SPECIAL_LABELS = {
    "node_id": "Node ID",
    "node_type": "Node Type",
    "node_config": "Node Config",
    "fw_version": "FW Version",
    "manual_rotate_feature": "Manual rotate",
    "manual_rotate_pwm": "Manual rotate PWM",
    "manual_rotate_report_time": "Report time",
    "serial_port": "Serial Port",
}
_LABEL_TOKEN_OVERRIDES = {
    "fw": "FW",
    "sw": "SW",
    "mcu": "MCU",
    "id": "ID",
    "pid": "PID",
}


def _present_label(label: object) -> str:
    raw_label = str(label)
    special_label = _SPECIAL_LABELS.get(raw_label)
    if special_label is not None:
        return special_label

    normalized_text = raw_label.replace("_", " ").strip()
    if not normalized_text:
        return raw_label

    rendered_tokens: list[str] = []
    for token in normalized_text.split():
        lowered_token = token.casefold()
        rendered_tokens.append(_LABEL_TOKEN_OVERRIDES.get(lowered_token, token.capitalize()))
    return " ".join(rendered_tokens)


class ConfigHeaderPanel(QFrame):
    """Compact tool-header summary for the Project Config page."""

    save_requested = pyqtSignal()
    reload_requested = pyqtSignal()
    reveal_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConfigHeaderPanel")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)

        self._title_label = QLabel("Project Config")
        self._title_label.setObjectName("ConfigToolbarTitle")
        top_row.addWidget(self._title_label, 0)
        top_row.addStretch(1)

        self._action_cluster = QFrame()
        self._action_cluster.setObjectName("ConfigActionCluster")
        action_row = QHBoxLayout(self._action_cluster)
        action_row.setContentsMargins(3, 3, 3, 3)
        action_row.setSpacing(4)

        self._save_button = QPushButton("Save")
        self._save_button.setToolTip("Save the current Project Config as a versioned YAML file")
        self._save_button.setProperty("tone", "primary")
        self._save_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._save_button.clicked.connect(self.save_requested.emit)
        action_row.addWidget(self._save_button)

        self._reload_button = QPushButton("Reload")
        self._reload_button.setToolTip("Reload the workspace from the current Project Config state")
        self._reload_button.setProperty("tone", "secondary")
        self._reload_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._reload_button.clicked.connect(self.reload_requested.emit)
        action_row.addWidget(self._reload_button)

        self._reveal_button = QPushButton("Reveal")
        self._reveal_button.setToolTip("Reveal the active project config file in Explorer")
        self._reveal_button.setProperty("tone", "secondary")
        self._reveal_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._reveal_button.clicked.connect(self.reveal_requested.emit)
        action_row.addWidget(self._reveal_button)

        top_row.addWidget(self._action_cluster, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(top_row)

        self._meta_label = QLabel("")
        self._meta_label.setObjectName("ConfigToolbarMeta")
        self._meta_label.setWordWrap(True)
        root.addWidget(self._meta_label)

        self._message_label = QLabel("")
        self._message_label.setObjectName("ConfigActionHint")
        self._message_label.setWordWrap(True)
        self._message_label.hide()
        root.addWidget(self._message_label)

        self._issue_label = QLabel("")
        self._issue_label.setObjectName("ConfigIssueBanner")
        self._issue_label.setWordWrap(True)
        self._issue_label.hide()
        root.addWidget(self._issue_label)

    def update_model(self, editor_model: ConfigEditorModel) -> None:
        """Refresh the compact metadata row from the latest editor model."""
        filename = editor_model.source_path.name
        version_text = editor_model.version or "missing"
        issue_count = len(editor_model.validation_issues)
        self._meta_label.setText(
            f"{filename}  |  {editor_model.project_name}  |  v{version_text}  |  {len(editor_model.sections)} sections"
        )
        self._meta_label.setToolTip(str(editor_model.source_path))
        if issue_count:
            preview = "; ".join(issue.message for issue in editor_model.validation_issues[:2])
            self._issue_label.setText(f"Validation issues: {preview}")
            self._issue_label.show()
        else:
            self._issue_label.hide()

    def set_message(self, text: str) -> None:
        """Update the compact status line beneath the action buttons."""
        self._message_label.setText(text)
        self._message_label.setVisible(bool(text.strip()))


class ConfigSectionPanel(PanelFrame):
    """One editable top-level YAML section."""

    def __init__(self, section_model: ConfigSectionModel) -> None:
        super().__init__(_present_label(section_model.title), "")
        self._section_model = section_model
        self.setProperty("surfaceTone", "config")
        self.body_layout.setSpacing(5)
        self._field_widgets: list[QWidget] = []
        self._list_editor: ConfigListEditor | None = None
        self._build_fields()

    @property
    def section_key(self) -> str:
        return self._section_model.section_key

    @property
    def raw_value_type(self) -> str:
        return self._section_model.raw_value_type

    def refresh_model(self, section_model: ConfigSectionModel) -> None:
        """Replace the field tree with the latest editor model for this section."""
        self._section_model = section_model
        self._build_fields()

    def collect_value(self):
        """Collect the current edited value for this top-level YAML section."""
        if self._list_editor is not None:
            collected_value = self._list_editor.collect_value()
            if not collected_value and self._section_model.preserve_empty_as_null:
                return None
            return collected_value
        if self._section_model.raw_value_type == "mapping":
            return {widget.field_key: widget.collect_value() for widget in self._field_widgets}
        if self._section_model.raw_value_type == "list":
            return [widget.collect_value() for widget in self._field_widgets]
        if not self._field_widgets:
            return None
        return self._field_widgets[0].collect_value()

    def _build_fields(self) -> None:
        clear_layout(self.body_layout)
        self._field_widgets = []
        self._list_editor = None

        if self._section_model.raw_value_type == "list":
            self._list_editor = ConfigListEditor(self._section_model.section_key, self._section_model.fields)
            self.body_layout.addWidget(self._list_editor)
            return

        if not self._section_model.fields:
            empty_label = QLabel("No values in this section.")
            empty_label.setObjectName("ConfigEmptyLabel")
            self.body_layout.addWidget(empty_label)
            return

        scalar_widgets: list[ConfigFieldWidget] = []
        nested_widgets: list[QWidget] = []
        for field in self._section_model.fields:
            widget = self._build_field_widget(field)
            self._field_widgets.append(widget)
            if isinstance(widget, ConfigFieldWidget) and widget._field.value_type not in {"mapping", "list"}:
                scalar_widgets.append(widget)
                continue
            nested_widgets.append(widget)

        if scalar_widgets:
            self.body_layout.addLayout(_build_compact_grid(scalar_widgets))
        for widget in nested_widgets:
            self.body_layout.addWidget(widget)

    def _build_field_widget(self, field: ConfigFieldModel) -> QWidget:
        if self._is_axis_field(field):
            return AxisSelectorEditor(field)
        if self._is_sensor_field(field):
            return SensorListEditor(field)
        return ConfigFieldWidget(field)

    def _is_axis_field(self, field: ConfigFieldModel) -> bool:
        return (
            field.value_type == "mapping"
            and field.path[-1] == "axes"
            and self._section_model.section_key in {"robot arm configuration", "robot"}
        )

    def _is_sensor_field(self, field: ConfigFieldModel) -> bool:
        return (
            field.value_type == "mapping"
            and field.path[-1] in {"sensors", "encoders"}
            and self._section_model.section_key in {"robot arm configuration", "robot"}
        )


class ConfigListEditor(QWidget):
    """Compact repeatable list editor used by list-typed config sections."""

    def __init__(self, section_key: str, fields: list[ConfigFieldModel]) -> None:
        super().__init__()
        self._section_key = section_key
        self._item_fields = list(fields)
        self._prototype_field = fields[0] if fields else None
        self._item_cards: list[ConfigListItemCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self._summary_label = QLabel("")
        self._summary_label.setObjectName("ConfigInlineMeta")
        toolbar.addWidget(self._summary_label, 0)
        toolbar.addStretch(1)

        self._add_button = QPushButton(self._add_button_text())
        self._add_button.setObjectName("ConfigInlineActionButton")
        self._add_button.setProperty("tone", "secondary")
        self._add_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._add_button.clicked.connect(self._handle_add_requested)
        toolbar.addWidget(self._add_button, 0)
        root.addLayout(toolbar)

        self._empty_notice = QFrame()
        self._empty_notice.setObjectName("ConfigCompactNotice")
        empty_layout = QHBoxLayout(self._empty_notice)
        empty_layout.setContentsMargins(7, 5, 7, 5)
        empty_layout.setSpacing(6)

        self._empty_label = QLabel(self._empty_state_text())
        self._empty_label.setObjectName("ConfigEmptyLabel")
        empty_layout.addWidget(self._empty_label, 0)
        empty_layout.addStretch(1)
        root.addWidget(self._empty_notice)

        self._items_host = QWidget()
        self._items_layout = QVBoxLayout(self._items_host)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(4)
        root.addWidget(self._items_host)

        self._rebuild_items()

    def collect_value(self) -> list:
        """Collect the current list value from all rendered item cards."""
        return [item_card.collect_value() for item_card in self._item_cards]

    def _handle_add_requested(self) -> None:
        item_index = len(self._item_fields)
        item_path = (self._section_key, item_index)
        item_label = self._item_label(item_index)

        if self._prototype_field is not None:
            new_field = _clone_empty_field_model(self._prototype_field, item_path, item_label)
        else:
            new_field = ConfigFieldModel(
                path=item_path,
                label=item_label,
                value="",
                value_type="string",
                editable=True,
            )
            self._prototype_field = new_field

        self._item_fields.append(new_field)
        self._rebuild_items()

    def _handle_remove_requested(self, item_index: int) -> None:
        self._item_fields.pop(item_index)
        self._rebuild_items()

    def _rebuild_items(self) -> None:
        clear_layout(self._items_layout)
        self._item_cards = []

        self._summary_label.setText(self._summary_text())
        self._empty_notice.setVisible(not self._item_fields)
        for item_index, item_field in enumerate(self._item_fields):
            item_field.label = self._item_label(item_index)
            item_card = ConfigListItemCard(item_field)
            item_card.remove_requested.connect(
                lambda _checked=False, index=item_index: self._handle_remove_requested(index)
            )
            self._items_layout.addWidget(item_card)
            self._item_cards.append(item_card)

    def _add_button_text(self) -> str:
        if self._section_key == "command list":
            return "Add Command"
        return "Add Item"

    def _empty_state_text(self) -> str:
        if self._section_key == "command list":
            return "No commands configured"
        return "No items configured"

    def _item_label(self, item_index: int) -> str:
        if self._section_key == "command list":
            return f"Command {item_index + 1}"
        return f"Item {item_index + 1}"

    def _summary_text(self) -> str:
        item_count = len(self._item_fields)
        if self._section_key == "command list":
            return f"{item_count} command{'s' if item_count != 1 else ''}"
        return f"{item_count} item{'s' if item_count != 1 else ''}"


class ConfigListItemCard(QFrame):
    """One removable item inside a repeatable config list."""

    remove_requested = pyqtSignal()

    def __init__(self, field: ConfigFieldModel) -> None:
        super().__init__()
        self._field = field
        self._content_widgets: list[ConfigFieldWidget] = []
        self._single_widget: ConfigFieldWidget | None = None

        self.setObjectName("ConfigListItemFrame")

        if field.value_type == "mapping":
            self._build_mapping_item()
            return

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)

        title_label = QLabel(field.label)
        title_label.setObjectName("ConfigListItemTitle")
        root.addWidget(title_label, 0)

        self._single_widget = ConfigFieldWidget(field)
        root.addWidget(self._single_widget, 1)

        remove_button = QPushButton("Remove")
        remove_button.setProperty("tone", "secondary")
        remove_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        remove_button.clicked.connect(self.remove_requested.emit)
        root.addWidget(remove_button, 0)

    def collect_value(self):
        """Collect the current value represented by this list item."""
        if self._field.value_type == "mapping":
            return {widget.field_key: widget.collect_value() for widget in self._content_widgets}
        if self._single_widget is None:
            return None
        return self._single_widget.collect_value()

    def _build_mapping_item(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(5)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel(self._field.label)
        title_label.setObjectName("ConfigListItemTitle")
        header_row.addWidget(title_label, 1)

        remove_button = QPushButton("Remove")
        remove_button.setProperty("tone", "secondary")
        remove_button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        remove_button.clicked.connect(self.remove_requested.emit)
        header_row.addWidget(remove_button, 0)
        root.addLayout(header_row)

        scalar_widgets: list[ConfigFieldWidget] = []
        nested_widgets: list[ConfigFieldWidget] = []
        for child in self._field.children:
            widget = ConfigFieldWidget(child)
            self._content_widgets.append(widget)
            if child.value_type in {"mapping", "list"}:
                nested_widgets.append(widget)
                continue
            scalar_widgets.append(widget)

        if scalar_widgets:
            root.addLayout(_build_compact_grid(scalar_widgets))
        for widget in nested_widgets:
            root.addWidget(widget)


def _clone_empty_field_model(
    field: ConfigFieldModel,
    path: tuple[str | int, ...],
    label: str | None = None,
) -> ConfigFieldModel:
    """Clone one field model into an empty editable template for new list items."""
    if field.value_type == "mapping":
        cloned_children = [
            _clone_empty_field_model(
                child,
                path + (child.path[-1],),
                child.label,
            )
            for child in field.children
        ]
        return ConfigFieldModel(
            path=path,
            label=label or field.label,
            value=None,
            value_type="mapping",
            editable=False,
            children=cloned_children,
        )

    if field.value_type == "list":
        return ConfigFieldModel(
            path=path,
            label=label or field.label,
            value=None,
            value_type="list",
            editable=False,
            children=[],
        )

    return ConfigFieldModel(
        path=path,
        label=label or field.label,
        value=_default_scalar_value(field.value_type),
        value_type=field.value_type,
        editable=field.editable,
    )


def _default_scalar_value(value_type: str):
    """Create a sensible empty default for newly added scalar list items."""
    if value_type == "bool":
        return False
    if value_type in {"int", "float", "null", "version"}:
        return None
    return ""


def _resolve_compact_grid_columns(widgets: list[QWidget]) -> int:
    if len(widgets) <= 1:
        return 1
    if any(getattr(widget, "prefers_full_row", False) for widget in widgets):
        return min(2, len(widgets))
    return min(_MAX_COMPACT_FIELD_COLUMNS, len(widgets))


def _build_compact_grid(widgets: list[QWidget], columns: int | None = None) -> QGridLayout:
    """Lay out compact field editors in a multi-column grid."""
    columns = columns or _resolve_compact_grid_columns(widgets)
    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(4)

    row = 0
    column = 0
    for widget in widgets:
        if getattr(widget, "prefers_full_row", False) and columns > 1:
            if column != 0:
                row += 1
                column = 0
            grid.addWidget(widget, row, 0, 1, columns)
            row += 1
            continue

        grid.addWidget(widget, row, column)
        column += 1
        if column >= columns:
            row += 1
            column = 0

    for column in range(columns):
        grid.setColumnStretch(column, 1)
    return grid


class AxisSelectorEditor(QWidget):
    """Shared editor layout for all configured axes, switched through one YAML-driven selector."""

    def __init__(self, field: ConfigFieldModel) -> None:
        super().__init__()
        self._field = field
        self._axis_names: list[str] = []
        self._axis_summaries: dict[str, AxisSummaryPanel] = {}
        self._axis_details: dict[str, AxisDetailsPanel] = {}
        self.axis_selector: QComboBox | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        if not field.children:
            empty_label = QLabel("No axes configured.")
            empty_label.setObjectName("ConfigEmptyLabel")
            root.addWidget(empty_label)
            return

        header = QFrame()
        header.setObjectName("ConfigAxisHeaderFrame")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setSpacing(8)

        selector_block = QWidget()
        selector_layout = QVBoxLayout(selector_block)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(3)

        selector_label = QLabel("Axis")
        selector_label.setObjectName("ConfigGroupTitle")
        selector_layout.addWidget(selector_label, 0)

        self._summary_stack = CurrentWidgetStack()
        self._summary_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._detail_stack = CurrentWidgetStack()
        self._detail_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        for axis_field in field.children:
            axis_name = str(axis_field.path[-1])
            self._axis_names.append(axis_name)

            summary_panel = AxisSummaryPanel(axis_field)
            detail_panel = AxisDetailsPanel(axis_field)
            self._axis_summaries[axis_name] = summary_panel
            self._axis_details[axis_name] = detail_panel
            self._summary_stack.addWidget(summary_panel)
            self._detail_stack.addWidget(detail_panel)

        self.axis_selector = QComboBox()
        self.axis_selector.setObjectName("AxisSelectorCombo")
        self.axis_selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for axis_name in self._axis_names:
            self.axis_selector.addItem(axis_name, axis_name)
        self.axis_selector.currentIndexChanged.connect(self._handle_axis_changed)
        selector_layout.addWidget(self.axis_selector, 0)

        header_layout.addWidget(selector_block, 0)
        header_layout.addWidget(self._summary_stack, 2)
        root.addWidget(header)
        root.addWidget(self._detail_stack, 0)

        self._sync_current_axis(self._axis_names[0])

    @property
    def field_key(self):
        return self._field.path[-1]

    def collect_value(self):
        """Collect edited values for every configured axis, not only the visible one."""
        collected_axes: dict[str, dict] = {}
        for axis_name in self._axis_names:
            axis_values: dict = {}
            axis_values.update(self._axis_summaries[axis_name].collect_value())
            axis_values.update(self._axis_details[axis_name].collect_value())
            collected_axes[axis_name] = axis_values
        return collected_axes

    def iter_scalar_widgets(self):
        """Yield every scalar widget from every axis form for tests and helpers."""
        for axis_name in self._axis_names:
            yield from self._axis_summaries[axis_name].iter_scalar_widgets()
            yield from self._axis_details[axis_name].iter_scalar_widgets()

    def set_current_axis(self, axis_name: str) -> None:
        if self.axis_selector is None or axis_name not in self._axis_names:
            return
        axis_index = self.axis_selector.findData(axis_name)
        if axis_index < 0:
            return
        self.axis_selector.setCurrentIndex(axis_index)

    def _handle_axis_changed(self, index: int) -> None:
        if index < 0 or self.axis_selector is None:
            return
        axis_name = str(self.axis_selector.itemData(index))
        self._sync_current_axis(axis_name)

    def _sync_current_axis(self, axis_name: str) -> None:
        if axis_name not in self._axis_names:
            return
        index = self._axis_names.index(axis_name)
        self._summary_stack.setCurrentIndex(index)
        self._detail_stack.setCurrentIndex(index)


class AxisSummaryPanel(QWidget):
    """Compact summary bar for the currently selected axis."""

    def __init__(self, axis_field: ConfigFieldModel) -> None:
        super().__init__()
        self._widgets: list[ConfigFieldWidget] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QGridLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setHorizontalSpacing(6)
        root.setVerticalSpacing(4)

        child_map = {str(child.path[-1]): child for child in axis_field.children}
        column = 0
        for key in _AXIS_SUMMARY_KEYS:
            child = child_map.get(key)
            if child is None:
                continue
            widget = ConfigFieldWidget(child, variant="summary", label_override=_present_label(key))
            self._widgets.append(widget)
            root.addWidget(widget, 0, column)
            root.setColumnStretch(column, 1)
            column += 1

        if not self._widgets:
            empty_label = QLabel("No summary values.")
            empty_label.setObjectName("ConfigEmptyLabel")
            root.addWidget(empty_label, 0, 0)

    def collect_value(self) -> dict:
        return {widget.field_key: widget.collect_value() for widget in self._widgets}

    def iter_scalar_widgets(self):
        for widget in self._widgets:
            yield from widget.iter_scalar_widgets()


class AxisDetailsPanel(QWidget):
    """Grouped detail editor for one selected axis."""

    def __init__(self, axis_field: ConfigFieldModel) -> None:
        super().__init__()
        self._axis_field = axis_field
        self._widgets: list[ConfigFieldWidget] = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        child_map = {str(child.path[-1]): child for child in axis_field.children}
        used_keys = set(_AXIS_SUMMARY_KEYS)

        for title, keys, columns in _AXIS_DETAIL_GROUPS:
            widgets: list[ConfigFieldWidget] = []
            for key in keys:
                child = child_map.get(key)
                if child is None:
                    continue
                widget = ConfigFieldWidget(child)
                self._widgets.append(widget)
                widgets.append(widget)
                used_keys.add(key)

            if not widgets:
                continue

            group = AxisGroupFrame(title, expanded=_DEFAULT_AXIS_GROUP_EXPANSION.get(title, False))
            group.add_field_grid(widgets, columns=columns)
            root.addWidget(group, 0)

        manual_group = self._build_manual_rotate_group(child_map)
        if manual_group is not None:
            root.addWidget(manual_group, 0)
            used_keys.update(_MANUAL_ROTATE_KEYS)

        remaining_widgets: list[ConfigFieldWidget] = []
        for child in self._axis_field.children:
            key = str(child.path[-1])
            if key in used_keys:
                continue
            widget = ConfigFieldWidget(child)
            self._widgets.append(widget)
            remaining_widgets.append(widget)

        if remaining_widgets:
            group = AxisGroupFrame("Additional", expanded=_DEFAULT_AXIS_GROUP_EXPANSION.get("Additional", False))
            group.add_field_grid(remaining_widgets)
            root.addWidget(group, 0)

    def collect_value(self) -> dict:
        return {widget.field_key: widget.collect_value() for widget in self._widgets}

    def iter_scalar_widgets(self):
        for widget in self._widgets:
            yield from widget.iter_scalar_widgets()

    def _build_manual_rotate_group(self, child_map: dict[str, ConfigFieldModel]) -> AxisGroupFrame | None:
        relevant_keys = [key for key in _MANUAL_ROTATE_KEYS if key in child_map]
        if not relevant_keys:
            return None

        group = AxisGroupFrame("Manual Rotate", expanded=_DEFAULT_AXIS_GROUP_EXPANSION.get("Manual Rotate", True))

        feature_child = child_map.get("manual_rotate_feature")
        feature_widget: ConfigFieldWidget | None = None
        if feature_child is not None:
            feature_widget = ConfigFieldWidget(
                feature_child,
                label_override=_present_label(feature_child.label),
            )
            self._widgets.append(feature_widget)
            group.add_widget(feature_widget)

        dependent_widgets: list[ConfigFieldWidget] = []
        for key in ("manual_rotate_pwm", "manual_rotate_report_time"):
            child = child_map.get(key)
            if child is None:
                continue
            widget = ConfigFieldWidget(child, label_override=_present_label(child.label))
            self._widgets.append(widget)
            dependent_widgets.append(widget)

        if not dependent_widgets:
            return group

        dependent_host = QWidget()
        dependent_layout = QVBoxLayout(dependent_host)
        dependent_layout.setContentsMargins(0, 0, 0, 0)
        dependent_layout.setSpacing(0)
        dependent_layout.addLayout(_build_compact_grid(dependent_widgets, columns=2))
        group.add_widget(dependent_host)

        def refresh_manual_state() -> None:
            enabled = bool(feature_widget is None or feature_widget._checkbox is None or feature_widget._checkbox.isChecked())
            dependent_host.setVisible(enabled)
            group.setProperty("muted", not enabled)
            group.style().unpolish(group)
            group.style().polish(group)

        if feature_widget is not None and feature_widget._checkbox is not None:
            feature_widget._checkbox.toggled.connect(lambda _checked: refresh_manual_state())
        refresh_manual_state()
        return group


class AxisGroupFrame(QFrame):
    """Lightweight grouped subsection inside the selected axis editor."""

    def __init__(self, title: str, expanded: bool = True) -> None:
        super().__init__()
        self.setObjectName("ConfigSubpanelFrame")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(9, 7, 9, 7)
        self._root.setSpacing(4)

        self._toggle_button = QToolButton()
        self._toggle_button.setObjectName("ConfigSubsectionToggle")
        self._toggle_button.setText(title)
        self._toggle_button.setCheckable(True)
        self._toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._toggle_button.toggled.connect(self._set_expanded)
        self._root.addWidget(self._toggle_button, 0)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(5)
        self._root.addWidget(self._content, 0)

        self._toggle_button.setChecked(expanded)
        self._set_expanded(expanded)

    def add_field_grid(self, widgets: list[QWidget], columns: int | None = None) -> None:
        self._content_layout.addLayout(_build_compact_grid(widgets, columns=columns))

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def _set_expanded(self, expanded: bool) -> None:
        self._content.setVisible(expanded)
        self._toggle_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.setProperty("expanded", expanded)
        self.style().unpolish(self)
        self.style().polish(self)


class CurrentWidgetStack(QStackedWidget):
    """Stack whose height follows the currently selected page instead of the tallest page."""

    def __init__(self) -> None:
        super().__init__()
        self.currentChanged.connect(self._handle_current_changed)

    def sizeHint(self):
        current_widget = self.currentWidget()
        if current_widget is None:
            return super().sizeHint()
        return current_widget.sizeHint()

    def minimumSizeHint(self):
        current_widget = self.currentWidget()
        if current_widget is None:
            return super().minimumSizeHint()
        return current_widget.minimumSizeHint()

    def _handle_current_changed(self, _index: int) -> None:
        self.updateGeometry()


class SensorListEditor(QWidget):
    """Compact table-like editor for robot-arm sensors."""

    def __init__(self, field: ConfigFieldModel) -> None:
        super().__init__()
        self._field = field
        self._rows: list[SensorRowEditor] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(3)

        table = QFrame()
        table.setObjectName("ConfigSensorTableFrame")
        table_layout = QVBoxLayout(table)
        table_layout.setContentsMargins(8, 5, 8, 5)
        table_layout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(16)
        for header_text, stretch in (("Sensor", 0), ("Node ID", 1), ("Reverse", 0)):
            label = QLabel(header_text)
            label.setObjectName("ConfigCollectionHeader")
            header_row.addWidget(label, stretch)
        header_row.addSpacing(12)
        for header_text, stretch in (("Sensor", 0), ("Node ID", 1), ("Reverse", 0)):
            label = QLabel(header_text)
            label.setObjectName("ConfigCollectionHeader")
            header_row.addWidget(label, stretch)
        header_row.addStretch(1)
        table_layout.addLayout(header_row)

        if not field.children:
            empty_label = QLabel("No sensors configured.")
            empty_label.setObjectName("ConfigEmptyLabel")
            table_layout.addWidget(empty_label)
        else:
            for start_index in range(0, len(field.children), _SENSOR_ITEMS_PER_ROW):
                pair_host = QWidget()
                pair_host.setObjectName("ConfigSensorPairRow")
                pair_layout = QHBoxLayout(pair_host)
                pair_layout.setContentsMargins(0, 0, 0, 0)
                pair_layout.setSpacing(8)

                sensor_slice = field.children[start_index : start_index + _SENSOR_ITEMS_PER_ROW]
                for sensor_field in sensor_slice:
                    row = SensorRowEditor(sensor_field)
                    self._rows.append(row)
                    pair_layout.addWidget(row, 1)

                if len(sensor_slice) < _SENSOR_ITEMS_PER_ROW:
                    pair_layout.addStretch(1)

                table_layout.addWidget(pair_host)

        group = AxisGroupFrame("Sensors", expanded=True)
        group.add_widget(table)
        root.addWidget(group)

    @property
    def field_key(self):
        return self._field.path[-1]

    def collect_value(self) -> dict:
        return {row.sensor_name: row.collect_value() for row in self._rows}

    def iter_scalar_widgets(self):
        for row in self._rows:
            yield from row.iter_scalar_widgets()


class SensorRowEditor(QFrame):
    """One compact table-like row inside the sensors subsection."""

    def __init__(self, field: ConfigFieldModel) -> None:
        super().__init__()
        self._field = field
        self._widgets: list[ConfigFieldWidget] = []
        self.setObjectName("ConfigSensorRow")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 5, 8, 5)
        root.setSpacing(8)

        sensor_label = QLabel(field.label)
        sensor_label.setObjectName("ConfigCollectionText")
        sensor_label.setMinimumWidth(52)
        root.addWidget(sensor_label, 0)

        child_map = {str(child.path[-1]): child for child in field.children}
        ordered_keys = [key for key in _SENSOR_KEY_ORDER if key in child_map]
        remaining_keys = [key for key in child_map.keys() if key not in ordered_keys]

        if "node_id" in ordered_keys:
            node_widget = ConfigFieldWidget(child_map["node_id"], variant="sensor_cell")
            self._widgets.append(node_widget)
            root.addWidget(node_widget, 1)

        if "reverse" in ordered_keys:
            reverse_widget = ConfigFieldWidget(child_map["reverse"], variant="sensor_boolean")
            self._widgets.append(reverse_widget)
            root.addWidget(reverse_widget, 0, Qt.AlignmentFlag.AlignVCenter)

        for key in remaining_keys:
            widget = ConfigFieldWidget(child_map[key])
            self._widgets.append(widget)
            root.addWidget(widget, 1)

    @property
    def sensor_name(self) -> str:
        return self._field.label

    def collect_value(self) -> dict:
        return {widget.field_key: widget.collect_value() for widget in self._widgets}

    def iter_scalar_widgets(self):
        for widget in self._widgets:
            yield from widget.iter_scalar_widgets()


class ConfigFieldWidget(QWidget):
    """Recursive editor widget for one YAML field."""

    def __init__(
        self,
        field: ConfigFieldModel,
        depth: int = 0,
        variant: str = "default",
        label_override: str | None = None,
    ) -> None:
        super().__init__()
        self._field = field
        self._depth = depth
        self._variant = variant
        self._label_text = label_override or _present_label(field.label)
        self._children: list[ConfigFieldWidget] = []
        self._line_edit: QLineEdit | None = None
        self._checkbox: QCheckBox | None = None
        self._overlay_label: QLabel | None = None
        self._uses_stacked_control = False
        self._build_widget()

    @property
    def field_key(self):
        return self._field.path[-1]

    @property
    def prefers_full_row(self) -> bool:
        if self._variant in {"summary", "sensor_cell", "sensor_boolean"}:
            return False
        if self._field.value_type == "mapping":
            return self._should_flatten_mapping()
        if self._field.value_type in {"list", "bool"}:
            return False
        if self._field.live_overlay is not None:
            return True

        terminal_key = str(self._field.path[-1]).casefold() if self._field.path else ""
        value_length = len(self._format_scalar_value())
        return terminal_key in {"notes"} or value_length > 42

    def iter_scalar_widgets(self):
        """Yield scalar editors recursively for tests and compact section helpers."""
        if self._field.value_type in {"mapping", "list"}:
            for child in self._children:
                yield from child.iter_scalar_widgets()
            return
        yield self

    def collect_value(self):
        """Collect the current edited value for this YAML field."""
        if self._field.value_type == "mapping":
            return {child.field_key: child.collect_value() for child in self._children}
        if self._field.value_type == "list":
            return [child.collect_value() for child in self._children]
        return self._collect_scalar_value()

    def _build_widget(self) -> None:
        if self._field.value_type in {"mapping", "list"}:
            self._build_container()
            return
        self._build_scalar_editor()

    def _build_container(self) -> None:
        if self._should_flatten_mapping():
            self._build_flattened_container()
            return

        root = QVBoxLayout(self)
        root.setContentsMargins(max(0, self._depth * 6), 0, 0, 0)
        root.setSpacing(4)

        container = QFrame()
        container.setObjectName("ConfigContainerFrame")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(8, 7, 8, 7)
        container_layout.setSpacing(5)

        title = QLabel(self._label_text)
        title.setObjectName("ConfigKeyLabel")
        container_layout.addWidget(title)

        if not self._field.children:
            empty_label = QLabel("No nested values.")
            empty_label.setObjectName("ConfigEmptyLabel")
            container_layout.addWidget(empty_label)
        else:
            scalar_children: list[ConfigFieldWidget] = []
            nested_children: list[ConfigFieldWidget] = []
            for child in self._field.children:
                widget = ConfigFieldWidget(child, depth=self._depth + 1)
                self._children.append(widget)
                if child.value_type in {"mapping", "list"}:
                    nested_children.append(widget)
                else:
                    scalar_children.append(widget)

            if scalar_children:
                container_layout.addLayout(_build_compact_grid(scalar_children))
            for widget in nested_children:
                container_layout.addWidget(widget)

        root.addWidget(container)

    def _build_flattened_container(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(max(0, self._depth * 6), 0, 0, 0)
        root.setSpacing(3)

        title = QLabel(self._label_text)
        title.setObjectName("ConfigSubsectionLabel")
        root.addWidget(title)

        scalar_children: list[ConfigFieldWidget] = []
        nested_children: list[ConfigFieldWidget] = []
        for child in self._field.children:
            widget = ConfigFieldWidget(child, depth=self._depth + 1)
            self._children.append(widget)
            if child.value_type in {"mapping", "list"}:
                nested_children.append(widget)
            else:
                scalar_children.append(widget)

        if scalar_children:
            root.addLayout(_build_compact_grid(scalar_children, columns=min(2, len(scalar_children))))
        for widget in nested_children:
            root.addWidget(widget)

    def _build_scalar_editor(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0 if self._variant == "summary" else max(0, self._depth * 6), 0, 0, 0)
        root.setSpacing(2)

        field_row = QFrame()
        field_row.setObjectName("ConfigSummaryField" if self._variant == "summary" else "ConfigFieldRow")

        if self._field.value_type == "bool":
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            field_row.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            row_layout = QHBoxLayout(field_row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)

            self._checkbox = QCheckBox()
            self._checkbox.setText("")
            self._checkbox.setChecked(bool(self._field.value))
            self._checkbox.toggled.connect(self._refresh_live_overlay_visibility)
            if self._variant == "sensor_boolean":
                self._checkbox.setToolTip(self._label_text)
                row_layout.addWidget(self._checkbox, 0, Qt.AlignmentFlag.AlignCenter)
            else:
                key_label = QLabel(self._label_text)
                key_label.setObjectName("ConfigKeyLabel")
                row_layout.addWidget(key_label, 0)
                row_layout.addWidget(self._checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            if self._variant == "sensor_cell":
                row_layout = QHBoxLayout(field_row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(0)
                stacked_variant = False
                shows_label = False
            else:
                stacked_variant = True
                row_layout = QVBoxLayout(field_row)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(3)
                shows_label = True
            self._uses_stacked_control = stacked_variant
            if shows_label:
                key_label = QLabel(self._label_text)
                key_label.setObjectName("ConfigSummaryLabel" if self._variant == "summary" else "ConfigKeyLabel")
                key_label.setWordWrap(True)
                row_layout.addWidget(key_label, 0)

            self._line_edit = QLineEdit(self._format_scalar_value())
            if self._field.value_type == "null":
                self._line_edit.setPlaceholderText("Not set")
            elif self._field.value_type == "version":
                self._line_edit.setPlaceholderText("e.g. 0.0.1.6")
            self._line_edit.textChanged.connect(self._refresh_live_overlay_visibility)
            self._line_edit.textChanged.connect(self._update_line_edit_width)
            self._line_edit.setToolTip(self._line_edit.text())
            self._line_edit.textChanged.connect(self._line_edit.setToolTip)
            if self._variant == "sensor_cell":
                row_layout.addWidget(self._line_edit, 0)
            else:
                control_row = QHBoxLayout()
                control_row.setContentsMargins(0, 0, 0, 0)
                control_row.setSpacing(0)
                control_row.addWidget(self._line_edit, 1 if self._should_expand_line_edit() else 0)
                control_row.addStretch(1)
                row_layout.addLayout(control_row, 0)
            self._update_line_edit_width()
            if self._line_edit.text():
                self._line_edit.setCursorPosition(0)

        root.addWidget(field_row)

        if self._field.live_overlay is not None:
            self._overlay_label = QLabel(self._field.live_overlay.display_text)
            self._overlay_label.setObjectName("ConfigLiveValueLabel")
            self._overlay_label.setWordWrap(True)
            root.addWidget(self._overlay_label)
            self._refresh_live_overlay_visibility()

    def _should_flatten_mapping(self) -> bool:
        if self._field.value_type != "mapping" or not self._field.children:
            return False
        return all(child.value_type not in {"mapping", "list"} for child in self._field.children)

    def _format_scalar_value(self) -> str:
        if self._field.value_type == "code":
            return self._normalized_code_text(self._field.value)
        if self._field.value is None:
            return ""
        return str(self._field.value)

    def _collect_scalar_value(self):
        if self._checkbox is not None:
            return self._checkbox.isChecked()

        if self._line_edit is None:
            return self._field.value

        text = self._line_edit.text()
        stripped_text = text.strip()

        if self._field.value_type == "code":
            return self._normalized_code_text(stripped_text)

        if self._field.value_type == "int":
            if not stripped_text:
                raise ValueError(f"{self._field.label} requires an integer value")
            try:
                return int(stripped_text)
            except ValueError as exc:
                raise ValueError(f"{self._field.label} requires an integer value") from exc

        if self._field.value_type == "float":
            if not stripped_text:
                raise ValueError(f"{self._field.label} requires a numeric value")
            try:
                return float(stripped_text)
            except ValueError as exc:
                raise ValueError(f"{self._field.label} requires a numeric value") from exc

        if self._field.value_type == "null":
            if not stripped_text:
                return None
            try:
                parsed_value = yaml.safe_load(stripped_text)
            except yaml.YAMLError as exc:
                raise ValueError(f"{self._field.label} contains invalid YAML scalar text") from exc
            if isinstance(parsed_value, (dict, list)):
                raise ValueError(f"{self._field.label} must stay a scalar value")
            return parsed_value

        if self._field.value_type == "version":
            if not stripped_text:
                return None
            if not is_valid_version_text(stripped_text):
                raise ValueError(
                    f"{self._field.label} must use digits separated by dots, for example 0.0.1.6"
                )
            return stripped_text

        return text

    def _refresh_live_overlay_visibility(self) -> None:
        if self._overlay_label is None or self._field.live_overlay is None:
            return
        try:
            current_value = self._collect_scalar_value()
        except ValueError:
            current_value = self._line_edit.text() if self._line_edit is not None else self._field.value
        should_show = str(current_value).strip() != str(self._field.live_overlay.live_value).strip()
        self._overlay_label.setVisible(should_show)

    def _normalized_code_text(self, value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, int):
            return f"{value:02d}"

        cleaned_value = str(value).strip()
        if cleaned_value.isdigit():
            return cleaned_value.zfill(2)
        return cleaned_value

    def _semantic_key(self) -> str:
        if not self._field.path:
            return ""
        return str(self._field.path[-1]).strip().casefold().replace("_", " ")

    def _update_line_edit_width(self) -> None:
        if self._line_edit is None:
            return

        preferred_width = self._preferred_line_edit_width()
        if self._should_expand_line_edit():
            self._line_edit.setMinimumWidth(preferred_width)
            self._line_edit.setMaximumWidth(16777215)
            self._line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            return

        self._line_edit.setFixedWidth(preferred_width)
        self._line_edit.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def _preferred_line_edit_width(self) -> int:
        if self._line_edit is None:
            return 84

        metrics = self._line_edit.fontMetrics()
        sample_text = self._width_sample_text()
        measured_width = metrics.horizontalAdvance(sample_text + "  ") + 28
        min_width, max_width = self._line_edit_width_bounds()
        return max(min_width, min(max_width, measured_width))

    def _line_edit_width_bounds(self) -> tuple[int, int]:
        semantic_key = self._semantic_key()
        if self._variant == "sensor_cell":
            return (56, 76)
        if semantic_key == "notes":
            return (240, 900)
        if semantic_key == "hardware info":
            return (168, 260)
        if semantic_key == "probe transducer distance":
            return (88, 114)
        if self._field.value_type == "code":
            return (60, 86)
        if self._field.value_type == "version" or semantic_key in {"config version", "firmware version", "fw version"}:
            return (104, 152)
        if semantic_key in {"node id", "node type", "axes number"}:
            return (62, 92)
        if "baud" in semantic_key:
            return (88, 116)
        if "encodercount" in semantic_key:
            return (90, 118)
        if "count" in semantic_key:
            return (90, 124)
        if semantic_key in {"fw motor deadband default", "fw motor pos targetoffset"}:
            return (72, 98)
        if self._field.value_type == "float":
            return (84, 128)
        if self._field.value_type == "int":
            return (72, 108)
        if self._field.value_type == "null":
            return (96, 156)
        return (96, 192)

    def _width_sample_text(self) -> str:
        semantic_key = self._semantic_key()
        current_text = self._line_edit.text().strip() if self._line_edit is not None else self._format_scalar_value().strip()
        placeholder_text = self._line_edit.placeholderText().strip() if self._line_edit is not None else ""

        if current_text:
            return current_text
        if semantic_key == "notes":
            return "Engineer note"
        if semantic_key == "hardware info":
            return "S32K148_12012025"
        if semantic_key == "probe transducer distance":
            return "44.59"
        if self._field.value_type == "code":
            return "00"
        if self._field.value_type == "version" or semantic_key in {"config version", "firmware version", "fw version"}:
            return "0.0.1.6"
        if "baud" in semantic_key:
            return "115200"
        if semantic_key in {"node id", "node type", "axes number"}:
            return "99"
        if "encodercount" in semantic_key:
            return "819300"
        if "counts per unit" in semantic_key:
            return "16384.00"
        if "count" in semantic_key:
            return "819200"
        if self._field.value_type == "float":
            return "123.45"
        if self._field.value_type == "int":
            return "1234"
        if self._field.value_type == "null" and placeholder_text:
            return placeholder_text
        if semantic_key == "name" and "serial_port" in {str(part) for part in self._field.path}:
            return "COM123"
        if placeholder_text:
            return placeholder_text
        return self._label_text or "Value"

    def _should_expand_line_edit(self) -> bool:
        if self._variant == "sensor_cell":
            return False
        if self.prefers_full_row:
            return True
        return self._semantic_key() in {"notes"}


class VersionChangeDialog(QDialog):
    """Explicit save dialog that requires a new config version when the config version was unchanged."""

    def __init__(self, current_version: str | None, parent=None) -> None:
        super().__init__(parent)
        self._current_version = (current_version or "").strip()
        self.setWindowTitle("Update Config Version")
        self.setModal(True)
        self.resize(420, 160)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        intro = QLabel(
            "The config version was not updated. Enter the new config version below before saving the updated config file."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        current_label = QLabel(f"Current config version: {self._current_version or 'missing'}")
        current_label.setObjectName("ConfigMetaValue")
        root.addWidget(current_label)

        self._version_input = QLineEdit()
        self._version_input.setPlaceholderText("e.g. 0.0.0.2")
        self._version_input.textChanged.connect(self._update_accept_state)
        root.addWidget(self._version_input)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        root.addWidget(self._button_box)

        self._update_accept_state()

    def requested_version(self) -> str:
        return self._version_input.text().strip()

    def _update_accept_state(self) -> None:
        save_button = self._button_box.button(QDialogButtonBox.StandardButton.Save)
        has_new_version = bool(self.requested_version()) and self.requested_version() != self._current_version
        save_button.setEnabled(has_new_version)
