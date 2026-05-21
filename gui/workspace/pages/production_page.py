"""Production page implementation (Phase 1 placeholder shell)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QListWidget, QPushButton, QTableWidgetItem

from ..bridges import WorkspaceRuntimeBridge
from ..models import DetailItem
from ..widgets import DetailListWidget, LabeledControl, PanelFrame, SimpleTableWidget
from ..widgets.layout_utils import clear_layout
from .base_page import BaseWorkspacePage

# TODO(Phase 2/3): move ML 2.0 node mapping to project-config/model-aware constants.
# TODO(Phase 2/3): replace old hardcoded node lists in legacy pages with model-aware config.
# TODO(Phase 2/3): align ML2.0.yaml-driven node identities when config integration is prioritized.
ML20_NODE_MAP: dict[int, str] = {
    1: "MCU Master",
    3: "X",
    4: "Y",
    5: "V",
    6: "H",
    7: "NZ",
    8: "RZ",
    9: "PZ",
    10: "HMI",
    11: "NGActuator",
    12: "Z",
}
_ML20_NODE_ORDER: tuple[int, ...] = (1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
_PLACEHOLDER_TEST_DURATION_MS = 900


def get_ml20_node_name(node_id: int) -> str:
    """Return the ML 2.0 display name for one node id."""
    return ML20_NODE_MAP.get(node_id, f"Node {node_id}")


def get_ml20_status_nodes() -> list[tuple[int, str]]:
    """Return all status-listed ML 2.0 nodes including MCU master."""
    return [(node_id, get_ml20_node_name(node_id)) for node_id in _ML20_NODE_ORDER]


def get_ml20_testable_nodes() -> list[tuple[int, str]]:
    """Return Production-selectable ML 2.0 test nodes (currently excluding Node 1 MCU Master)."""
    return [(node_id, get_ml20_node_name(node_id)) for node_id in _ML20_NODE_ORDER if node_id != 1]


class ProductionPage(BaseWorkspacePage):
    """Operator-focused Production page for placeholder node testing."""

    console_message = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Production", "Simple node-based quality control testing.")
        self._bridge = bridge

        self.connection_section = _ConnectionStatusSection()
        self.node_status_section = _NodeStatusSection()
        self.test_control_section = _TestControlSection()
        self.result_summary_section = _ResultSummarySection()
        self.progress_section = _TestProgressSection()
        self._pending_result_timer: QTimer | None = None
        self._active_node: tuple[int, str] | None = None

        self.test_control_section.run_requested.connect(self._handle_run_test)
        self.test_control_section.stop_requested.connect(self._handle_stop_test)
        self.test_control_section.clear_requested.connect(self._handle_clear_result)

        self.add_full_width(self.connection_section)
        self.add_row(self.node_status_section, self.test_control_section)
        self.add_full_width(self.result_summary_section)
        self.add_full_width(self.progress_section)

        self._reset_result_only()
        self._refresh_connection_status()

    def refresh(self) -> None:
        """Refresh lightweight placeholder status without resetting operator state."""
        self._refresh_connection_status()

    def _refresh_connection_status(self) -> None:
        # TODO(Phase 2): replace placeholder transport state with real bridge/runtime connectivity.
        self.connection_section.set_status(serial_connected=False, mcu_connected=False)

    def _handle_run_test(self) -> None:
        self._cancel_pending_completion()
        node_id, node_name = self.test_control_section.selected_node()
        self._active_node = (node_id, node_name)
        self.node_status_section.set_node_status(node_id, "Testing")
        self.result_summary_section.set_result("TESTING", "Running placeholder test flow.")
        self.progress_section.append_step(f"Started placeholder test for Node {node_id} {node_name}")
        self.console_message.emit(f"[Production] Started placeholder test for Node {node_id} {node_name}")

        # TODO(Phase 2): invoke ProductionTestController and route UART/CAN test commands.
        self._pending_result_timer = QTimer(self)
        self._pending_result_timer.setSingleShot(True)
        self._pending_result_timer.timeout.connect(self._complete_placeholder_test)
        self._pending_result_timer.start(_PLACEHOLDER_TEST_DURATION_MS)

    def _handle_stop_test(self) -> None:
        node_id, _ = self.test_control_section.selected_node()
        self._cancel_pending_completion()
        self._active_node = None
        self.node_status_section.set_node_status(node_id, "Aborted")
        self.result_summary_section.set_result("ABORTED", "Operator stopped the placeholder test.")
        self.progress_section.append_step("Placeholder test aborted")
        self.console_message.emit("[Production] Test aborted")

    def _handle_clear_result(self) -> None:
        self._reset_result_only()
        self._active_node = None
        self.console_message.emit("[Production] Cleared result summary and progress")

    def _reset_result_only(self) -> None:
        self.result_summary_section.set_result("READY", "No test has been run yet.")
        self.progress_section.reset_steps(
            [
                "1. Waiting for node selection",
                "2. Waiting for Run Test",
            ]
        )

    def _complete_placeholder_test(self) -> None:
        if self._active_node is None:
            return
        node_id, node_name = self._active_node
        self.node_status_section.set_node_status(node_id, "PASS (placeholder)")
        self.result_summary_section.set_result("PASS", "Placeholder test completed.")
        self.progress_section.append_step(f"Completed placeholder test for Node {node_id} {node_name}")
        self.console_message.emit(f"[Production] Placeholder test completed for Node {node_id} {node_name}")
        self._cancel_pending_completion()
        self._active_node = None

    def _cancel_pending_completion(self) -> None:
        if self._pending_result_timer is not None:
            self._pending_result_timer.stop()
            self._pending_result_timer.deleteLater()
            self._pending_result_timer = None


class _ConnectionStatusSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Connection Status", "")
        self._detail_list = DetailListWidget([])
        self.body_layout.addWidget(self._detail_list)

    def set_status(self, *, serial_connected: bool, mcu_connected: bool) -> None:
        clear_layout(self.body_layout)
        serial_text = "● Connected" if serial_connected else "○ Disconnected"
        mcu_text = "● Connected" if mcu_connected else "○ Not Connected"
        self._detail_list = DetailListWidget(
            [
                DetailItem("Serial Connection", serial_text),
                DetailItem("MCU Master", mcu_text),
            ]
        )
        self.body_layout.addWidget(self._detail_list)


class _NodeStatusSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Node Status", "")
        status_nodes = get_ml20_status_nodes()
        rows = [[str(node_id), node_name, "Not Tested"] for node_id, node_name in status_nodes]
        self._row_by_node_id = {node_id: row_index for row_index, (node_id, _name) in enumerate(status_nodes)}
        self.table = SimpleTableWidget(["Node ID", "Node Name", "Status"], rows)
        self.body_layout.addWidget(self.table)

    def set_node_status(self, node_id: int, status: str) -> None:
        row_index = self._row_by_node_id.get(node_id)
        if row_index is None:
            return
        item = QTableWidgetItem(status)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row_index, 2, item)


class _TestControlSection(PanelFrame):
    run_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__("Test Control", "")
        self._combo = QComboBox()
        self._combo.setObjectName("AxisSelectorCombo")
        for node_id, node_name in get_ml20_testable_nodes():
            self._combo.addItem(f"Node {node_id} - {node_name}", (node_id, node_name))
        self.body_layout.addWidget(LabeledControl("Selected Node", self._combo))

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)

        run_button = QPushButton("Run Test")
        run_button.setProperty("tone", "primary")
        run_button.clicked.connect(self.run_requested.emit)
        button_row.addWidget(run_button)

        stop_button = QPushButton("Stop")
        stop_button.setProperty("tone", "danger")
        stop_button.clicked.connect(self.stop_requested.emit)
        button_row.addWidget(stop_button)

        self.body_layout.addLayout(button_row)

        clear_button = QPushButton("Clear Result")
        clear_button.setProperty("tone", "secondary")
        clear_button.clicked.connect(self.clear_requested.emit)
        self.body_layout.addWidget(clear_button)

    def selected_node(self) -> tuple[int, str]:
        selected = self._combo.currentData()
        if not isinstance(selected, tuple) or len(selected) != 2:
            fallback_nodes = get_ml20_testable_nodes()
            return fallback_nodes[0]
        node_id, node_name = selected
        return int(node_id), str(node_name)


class _ResultSummarySection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Result Summary", "")
        self._status_label = QLabel("READY")
        self._status_label.setObjectName("MetricValue")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_layout.addWidget(self._status_label)

        self._reason_label = QLabel("Reason: No test has been run yet.")
        self._reason_label.setObjectName("DetailValue")
        self._reason_label.setWordWrap(True)
        self.body_layout.addWidget(self._reason_label)

    def set_result(self, status: str, reason: str) -> None:
        self._status_label.setText(status)
        self._reason_label.setText(f"Reason: {reason}")


class _TestProgressSection(PanelFrame):
    def __init__(self) -> None:
        super().__init__("Test Progress", "")
        self._list = QListWidget()
        self.body_layout.addWidget(self._list)

    def reset_steps(self, steps: list[str]) -> None:
        self._list.clear()
        self._list.addItems(steps)

    def append_step(self, step: str) -> None:
        self._list.addItem(step)
