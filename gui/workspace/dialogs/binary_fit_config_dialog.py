"""Binary FIT configuration dialog for Firmware Integration."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareCommandDefinition, FirmwareTestCase


class BinaryFitConfigDialog(QDialog):
    """UI-only case/node selection dialog for Binary FIT runs."""

    run_requested = pyqtSignal(int, object)

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._case_definitions = controller.binary_fit_case_definitions()
        self._command_definitions_by_name: dict[str, FirmwareCommandDefinition] = {
            definition.name: definition for definition in controller.manual_binary_command_definitions()
        }

        self.setWindowTitle("Binary Firmware Integration Test")
        self.setModal(False)
        self.resize(900, 620)
        self.setMinimumSize(820, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        helper = QLabel(
            "Select a target node and the Binary FIT cases to run. "
            "This dialog only collects operator choices; the controller owns sequencing."
        )
        helper.setWordWrap(True)
        helper.setObjectName("BinaryFitConfigHelperText")
        root.addWidget(helper)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(8)

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("BinaryFitConfigNodeCombo")
        self.node_combo.currentIndexChanged.connect(self._refresh_run_button_state)

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setObjectName("BinaryFitConfigSelectAllButton")
        self.select_all_button.clicked.connect(self._select_all)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.setObjectName("BinaryFitConfigDeselectAllButton")
        self.deselect_all_button.clicked.connect(self._deselect_all)

        self.reset_defaults_button = QPushButton("Reset Defaults")
        self.reset_defaults_button.setObjectName("BinaryFitConfigResetDefaultsButton")
        self.reset_defaults_button.clicked.connect(self._reset_defaults)

        self.run_button = QPushButton("Run")
        self.run_button.setObjectName("BinaryFitConfigRunButton")
        self.run_button.setProperty("tone", "primary")
        self.run_button.clicked.connect(self._handle_run_clicked)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("BinaryFitConfigCancelButton")
        self.cancel_button.setProperty("tone", "secondary")
        self.cancel_button.clicked.connect(self.reject)

        controls.addWidget(QLabel("Target Node"), 0, 0)
        controls.addWidget(self.node_combo, 0, 1)
        controls.addWidget(self.select_all_button, 0, 2)
        controls.addWidget(self.deselect_all_button, 0, 3)
        controls.addWidget(self.reset_defaults_button, 0, 4)
        controls.addWidget(self.run_button, 0, 5)
        controls.addWidget(self.cancel_button, 0, 6)
        root.addLayout(controls)

        self.case_table = QTableWidget(0, 6)
        self.case_table.setObjectName("BinaryFitConfigCaseTable")
        self.case_table.setHorizontalHeaderLabels(
            ["Run", "Command / Test Name", "Opcode", "Parameter", "Expected Response", "Manual Check"]
        )
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.case_table.itemChanged.connect(self._handle_table_item_changed)
        root.addWidget(self.case_table, 1)

        self.status_label = QLabel("Select at least one case to run.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("BinaryFitConfigStatusLabel")
        root.addWidget(self.status_label)

        self._populate_node_options()
        self._populate_case_table()
        self._refresh_run_button_state()

    def selected_node_id(self) -> int | None:
        node_id = self.node_combo.currentData()
        return int(node_id) if isinstance(node_id, int) else None

    def selected_case_ids(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None and checkbox.isChecked():
                case_id = self.case_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                if isinstance(case_id, str):
                    selected.append(case_id)
        return selected

    def _populate_node_options(self) -> None:
        self.node_combo.clear()
        for node_id, label in self._controller.get_manual_binary_node_options():
            display = f"Node {int(node_id)} - {str(label)}" if str(label).strip() else f"Node {int(node_id)}"
            self.node_combo.addItem(display, int(node_id))
        if self.node_combo.count() == 0:
            self.node_combo.addItem("No nodes available", None)

    def _populate_case_table(self) -> None:
        self.case_table.blockSignals(True)
        self.case_table.setRowCount(len(self._case_definitions))
        for row, case in enumerate(self._case_definitions):
            command_definition = self._command_definitions_by_name[case.command_key]

            checkbox = QCheckBox()
            checkbox.setObjectName(f"BinaryFitConfigCaseCheck_{case.case_id}")
            checkbox.setChecked(bool(case.selected_by_default))
            checkbox.toggled.connect(self._refresh_run_button_state)
            checkbox_host = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_host)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            self.case_table.setCellWidget(row, 0, checkbox_host)

            name_item = QTableWidgetItem(case.name)
            name_item.setData(Qt.ItemDataRole.UserRole, case.case_id)
            self.case_table.setItem(row, 1, name_item)

            opcode_text = f"0x{int(command_definition.opcode or 0):02X}" if command_definition.opcode is not None else "--"
            self.case_table.setItem(row, 2, QTableWidgetItem(opcode_text))

            parameter_text = "--" if case.parameter_value is None else str(case.parameter_value)
            self.case_table.setItem(row, 3, QTableWidgetItem(parameter_text))
            self.case_table.setItem(row, 4, QTableWidgetItem(str(case.expected_response or "--")))
            self.case_table.setItem(row, 5, QTableWidgetItem("Yes" if case.manual_verification else "No"))

        self.case_table.resizeColumnsToContents()
        self.case_table.blockSignals(False)

    def _select_all(self) -> None:
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None:
                checkbox.setChecked(True)
        self._refresh_run_button_state()

    def _deselect_all(self) -> None:
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None:
                checkbox.setChecked(False)
        self._refresh_run_button_state()

    def _reset_defaults(self) -> None:
        for row, case in enumerate(self._case_definitions):
            checkbox = self._row_checkbox(row)
            if checkbox is not None:
                checkbox.setChecked(bool(case.selected_by_default))
        self._refresh_run_button_state()

    def _handle_run_clicked(self) -> None:
        node_id = self.selected_node_id()
        case_ids = self.selected_case_ids()
        if node_id is None:
            self.status_label.setText("Select a valid node before running Binary FIT.")
            return
        if not case_ids:
            self.status_label.setText("Select at least one Binary FIT case before running.")
            return
        self.run_requested.emit(node_id, list(case_ids))
        self.accept()

    def _handle_table_item_changed(self, _item: QTableWidgetItem) -> None:
        self._refresh_run_button_state()

    def _refresh_run_button_state(self) -> None:
        has_node = self.selected_node_id() is not None
        selected_count = len(self.selected_case_ids())
        self.run_button.setEnabled(has_node and selected_count > 0)
        if not has_node:
            self.status_label.setText("Select a target node to run Binary FIT.")
        elif selected_count == 0:
            self.status_label.setText("Select at least one Binary FIT case to run.")
        else:
            self.status_label.setText(f"Ready to run {selected_count} Binary FIT case(s).")

    def _row_checkbox(self, row: int) -> QCheckBox | None:
        host = self.case_table.cellWidget(row, 0)
        if host is None:
            return None
        return host.findChild(QCheckBox)
