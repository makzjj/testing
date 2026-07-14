"""Binary FIT configuration dialog for Firmware Integration."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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

        self.setWindowTitle("Binary Command Suite Configuration")
        self.setModal(False)
        self.resize(750, 520)
        self.setMinimumSize(750, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        node_layout = QHBoxLayout()
        node_layout.addWidget(QLabel("Target CAN Node ID (2-17):"))

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("BinaryFitConfigNodeCombo")
        self.node_combo.setMaximumWidth(60)
        self.node_combo.currentIndexChanged.connect(self._refresh_run_button_state)
        node_layout.addWidget(self.node_combo)
        node_layout.addStretch()
        root.addLayout(node_layout)

        root.addWidget(QLabel("Configure and select Binary commands (Section 7) to verify:"))

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setObjectName("BinaryFitConfigSelectAllButton")
        self.select_all_button.clicked.connect(self._select_all)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.setObjectName("BinaryFitConfigDeselectAllButton")
        self.deselect_all_button.clicked.connect(self._deselect_all)

        self.reset_defaults_button = QPushButton("Reset Defaults")
        self.reset_defaults_button.setObjectName("BinaryFitConfigResetDefaultsButton")
        self.reset_defaults_button.clicked.connect(self._reset_defaults)

        self.run_button = QPushButton("Start Test Run")
        self.run_button.setObjectName("BinaryFitConfigRunButton")
        self.run_button.setProperty("tone", "primary")
        self.run_button.clicked.connect(self._handle_run_clicked)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("BinaryFitConfigCancelButton")
        self.cancel_button.setProperty("tone", "secondary")
        self.cancel_button.clicked.connect(self.reject)

        self.case_table = QTableWidget(0, 5)
        self.case_table.setObjectName("BinaryFitConfigCaseTable")
        self.case_table.setHorizontalHeaderLabels(
            ["Test?", "Hex Code", "Command Name", "Parameters (Hex bytes)", "Param Type"]
        )
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.case_table.horizontalHeader().setStretchLastSection(True)
        self.case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.case_table.setColumnWidth(0, 55)
        self.case_table.setColumnWidth(1, 80)
        self.case_table.setColumnWidth(2, 220)
        self.case_table.setColumnWidth(3, 160)
        self.case_table.itemChanged.connect(self._handle_table_item_changed)
        root.addWidget(self.case_table, 1)

        controls = QHBoxLayout()
        controls.addWidget(self.select_all_button)
        controls.addWidget(self.deselect_all_button)
        controls.addWidget(self.reset_defaults_button)
        controls.addStretch()
        root.addLayout(controls)

        self.status_label = QLabel("Select at least one case to run.")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("BinaryFitConfigStatusLabel")
        root.addWidget(self.status_label)

        dialog_buttons = QHBoxLayout()
        dialog_buttons.addStretch()
        dialog_buttons.addWidget(self.run_button)
        dialog_buttons.addWidget(self.cancel_button)
        root.addLayout(dialog_buttons)

        self._populate_node_options()
        self._populate_case_table()
        self._refresh_run_button_state()

    def selected_node_id(self) -> int | None:
        node_id = self.node_combo.currentData()
        return int(node_id) if isinstance(node_id, int) else None

    def selected_case_ids(self) -> list[str]:
        return [case.case_id for case in self.selected_cases()]

    def selected_cases(self) -> list[FirmwareTestCase]:
        selected: list[FirmwareTestCase] = []
        cases_by_id = {case.case_id: case for case in self._case_definitions}
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None and checkbox.isChecked():
                case_id = self.case_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                if isinstance(case_id, str):
                    case = cases_by_id.get(case_id)
                    if case is not None:
                        selected.append(replace(case, parameter_value=self._row_parameter_value(row, case)))
        return selected

    def _populate_node_options(self) -> None:
        self.node_combo.clear()
        for node_id in range(2, 18):
            self.node_combo.addItem(str(node_id), int(node_id))
        self.node_combo.setCurrentText("3")

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

            opcode_text = f"0x{int(command_definition.opcode or 0):02X}" if command_definition.opcode is not None else "--"
            opcode_item = QTableWidgetItem(opcode_text)
            opcode_item.setData(Qt.ItemDataRole.UserRole, case.case_id)
            self.case_table.setItem(row, 1, opcode_item)

            legacy_name = str((command_definition.validation or {}).get("legacy_name") or case.name)
            name_item = QTableWidgetItem(legacy_name)
            name_item.setData(Qt.ItemDataRole.UserRole, case.case_id)
            self.case_table.setItem(row, 2, name_item)

            parameter_input = QLineEdit()
            parameter_input.setObjectName(f"BinaryFitConfigValueInput_{case.case_id}")
            parameter_input.setText("" if case.parameter_value is None else str(case.parameter_value))
            parameter_input.textChanged.connect(self._refresh_run_button_state)
            parameter_kind = str((command_definition.parameter_schema or {}).get("kind", "none"))
            parameter_input.setEnabled(parameter_kind not in {"none", "query_3f"})
            if parameter_kind in {"none", "query_3f"}:
                parameter_input.setPlaceholderText("No value required")
                parameter_input.setVisible(False)
                parameter_input.setStyleSheet("background-color: #eee;")
            self.case_table.setCellWidget(row, 3, parameter_input)
            self.case_table.setItem(
                row,
                4,
                QTableWidgetItem(str((command_definition.validation or {}).get("params_type") or parameter_kind).upper()),
            )

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
            value_input = self.case_table.cellWidget(row, 3)
            if isinstance(value_input, QLineEdit):
                value_input.setText("" if case.parameter_value is None else str(case.parameter_value))
        self._refresh_run_button_state()

    def _handle_run_clicked(self) -> None:
        node_id = self.selected_node_id()
        cases = self.selected_cases()
        if node_id is None:
            self.status_label.setText("Select a valid node before running Binary FIT.")
            return
        if not cases:
            self.status_label.setText("Select at least one Binary FIT case before running.")
            return
        self.run_requested.emit(node_id, list(cases))
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

    def _row_parameter_value(self, row: int, case: FirmwareTestCase) -> object | None:
        definition = self._command_definitions_by_name.get(case.command_key)
        kind = str((definition.parameter_schema or {}).get("kind", "none")) if definition is not None else "none"
        if kind in {"none", "query_3f"}:
            return None
        widget = self.case_table.cellWidget(row, 3)
        if isinstance(widget, QLineEdit):
            return widget.text()
        return case.parameter_value
