"""Section widgets used by the Mechanical page."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QProgressBar

from ...bridges import WorkspaceRuntimeBridge
from ...widgets import ChipGroupWidget, DetailListWidget, LabeledControl, PanelFrame, SimpleTableWidget
from ...widgets.layout_utils import clear_layout
from ..section_utils import build_grid_layout


class MotorBehaviourSection(PanelFrame):
    """Mechanical behaviour observation module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Motor behaviour", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        rows = []
        for index, (axis_name, axis_data) in enumerate(_axis_map(self._bridge.raw_config).items(), start=1):
            standby = axis_data.get("standby_position", 0)
            pwm = f"{16 + index * 6}%"
            rows.append([axis_name.upper(), f"{standby:+.1f}", pwm])
        self.body_layout.addWidget(SimpleTableWidget(["Axis", "Offset", "PWM"], rows or [["A1", "0.0", "0%"]]))


class AxisMotionControlSection(PanelFrame):
    """Mechanical axis-control module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Axis motion control", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        apply_button = QPushButton("Apply")
        apply_button.setProperty("tone", "secondary")
        actions.addStretch(1)
        actions.addWidget(apply_button)

        stop_button = QPushButton("Stop")
        stop_button.setProperty("tone", "danger")
        actions.addWidget(stop_button)
        self.body_layout.addLayout(actions)

        grid = build_grid_layout(spacing=10)

        for row_index, (axis_name, axis_data) in enumerate(list(_axis_map(self._bridge.raw_config).items())[:4]):
            current = QPushButton(f"{axis_data.get('standby_position', 0):+.1f}")
            current.setEnabled(False)
            current.setProperty("tone", "secondary")

            target = QLineEdit(f"{axis_data.get('standby_position', 0):.1f} deg")
            minus_button = QPushButton("-")
            minus_button.setProperty("tone", "secondary")
            plus_button = QPushButton("+")
            plus_button.setProperty("tone", "secondary")
            move_button = QPushButton("Move")
            move_button.setProperty("tone", "primary")
            move_button.setMinimumWidth(move_button.fontMetrics().horizontalAdvance("Move") + 44)

            grid.addWidget(LabeledControl(axis_name.upper(), current), row_index, 0)
            grid.addWidget(LabeledControl("Target", target), row_index, 1)

            jog_row = QHBoxLayout()
            jog_row.setContentsMargins(0, 0, 0, 0)
            jog_row.setSpacing(8)
            jog_row.addWidget(minus_button)
            jog_row.addWidget(plus_button)
            jog_row.addWidget(move_button)

            grid.addLayout(jog_row, row_index, 2)

        self.body_layout.addLayout(grid)


class RepeatabilitySection(PanelFrame):
    """Repeatability module home."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Repeatability check", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        axis_names = list(_axis_map(self._bridge.raw_config).keys())

        grid = build_grid_layout()

        axis_input = QLineEdit(axis_names[0].upper() if axis_names else "A1")
        cycles_input = QLineEdit("5")
        tolerance_input = QLineEdit("+/- 0.20")

        grid.addWidget(LabeledControl("Axis", axis_input), 0, 0)
        grid.addWidget(LabeledControl("Cycles", cycles_input), 0, 1)
        grid.addWidget(LabeledControl("Tolerance", tolerance_input), 1, 0, 1, 2)
        self.body_layout.addLayout(grid)

        self.body_layout.addWidget(ChipGroupWidget([("Last max dev 0.14", "success"), ("Pass rate 5 / 5", "info")], columns=2))

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(100)
        self.body_layout.addWidget(progress)

        self.body_layout.addWidget(ChipGroupWidget([(f"C{index}", "success") for index in range(1, 6)], columns=5))


class SensorLimitsSection(PanelFrame):
    """Sensor limits and offsets module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Sensor limits & offsets", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        rows = []
        for key, value in self._bridge.raw_config.get("geometry", {}).items():
            rows.append([key.replace("_", " "), str(value), "geom"])
        for key, value in self._bridge.raw_config.get("calibration", {}).items():
            rows.append([key.replace("_", " "), str(value), "cal"])
        self.body_layout.addWidget(SimpleTableWidget(["Item", "Value", "Type"], rows or [["limit", "n/a", "idle"]]))


class SelectedAxisSnapshotSection(PanelFrame):
    """Selected-axis snapshot module."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Selected axis snapshot", "")
        self._bridge = bridge
        self.refresh()

    def refresh(self) -> None:
        clear_layout(self.body_layout)
        self.body_layout.addWidget(DetailListWidget(self._bridge.get_axis_snapshot_items()))


def _axis_map(raw_config: dict) -> dict[str, dict]:
    axes = raw_config.get("robot", {}).get("axes", {})
    return axes if isinstance(axes, dict) else {}
