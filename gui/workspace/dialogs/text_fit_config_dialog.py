"""Text FIT configuration dialog for Firmware Integration."""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
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


class TextFitConfigDialog(QDialog):
    """UI-only case selection dialog for Text FIT runs."""

    run_requested = pyqtSignal(object)

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._case_definitions = controller.text_fit_case_definitions()
        self._command_definitions_by_name: dict[str, FirmwareCommandDefinition] = {
            definition.name: definition for definition in controller.manual_text_command_definitions()
        }

        self.setWindowTitle("Text Command Suite Configuration")
        self.setModal(False)
        self.resize(700, 500)
        self.setMinimumSize(700, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        root.addWidget(QLabel("Configure and select Text-based commands to verify:"))

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setObjectName("TextFitConfigSelectAllButton")
        self.select_all_button.clicked.connect(self._select_all)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.setObjectName("TextFitConfigDeselectAllButton")
        self.deselect_all_button.clicked.connect(self._deselect_all)

        self.reset_defaults_button = QPushButton("Reset Defaults")
        self.reset_defaults_button.setObjectName("TextFitConfigResetDefaultsButton")
        self.reset_defaults_button.clicked.connect(self._reset_defaults)

        self.run_button = QPushButton("Start Test Run")
        self.run_button.setObjectName("TextFitConfigRunButton")
        self.run_button.setProperty("tone", "primary")
        self.run_button.clicked.connect(self._handle_run_clicked)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("TextFitConfigCancelButton")
        self.cancel_button.setProperty("tone", "secondary")
        self.cancel_button.clicked.connect(self.reject)

        self.case_table = QTableWidget(0, 4)
        self.case_table.setObjectName("TextFitConfigCaseTable")
        self.case_table.setHorizontalHeaderLabels(
            ["Test?", "Command Format", "Value/Param", "Type"]
        )
        self.case_table.verticalHeader().setVisible(False)
        self.case_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.case_table.horizontalHeader().setStretchLastSection(True)
        self.case_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.case_table.setColumnWidth(0, 55)
        self.case_table.setColumnWidth(1, 160)
        self.case_table.setColumnWidth(2, 180)
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
        self.status_label.setObjectName("TextFitConfigStatusLabel")
        root.addWidget(self.status_label)

        dialog_buttons = QHBoxLayout()
        dialog_buttons.addStretch()
        dialog_buttons.addWidget(self.run_button)
        dialog_buttons.addWidget(self.cancel_button)
        root.addLayout(dialog_buttons)

        self._populate_case_table()
        self._refresh_run_button_state()

    def selected_case_ids(self) -> list[str]:
        selected: list[str] = []
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is not None and checkbox.isChecked():
                case_id = self.case_table.item(row, 1).data(Qt.ItemDataRole.UserRole)
                if isinstance(case_id, str):
                    selected.append(case_id)
        return selected

    def selected_cases(self) -> list[FirmwareTestCase]:
        selected: list[FirmwareTestCase] = []
        cases_by_id = {case.case_id: case for case in self._case_definitions}
        for row in range(self.case_table.rowCount()):
            checkbox = self._row_checkbox(row)
            if checkbox is None or not checkbox.isChecked():
                continue
            case_item = self.case_table.item(row, 1)
            if case_item is None:
                continue
            case_id = case_item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(case_id, str) or case_id not in cases_by_id:
                continue
            case = cases_by_id[case_id]
            value_input = self._row_value_input(row)
            if value_input is None or not value_input.isEnabled():
                selected.append(case)
            else:
                selected.append(replace(case, parameter_value=value_input.text().strip()))
        return selected

    def _populate_case_table(self) -> None:
        self.case_table.blockSignals(True)
        self.case_table.setColumnCount(4)
        self.case_table.setHorizontalHeaderLabels(
            ["Test?", "Command Format", "Value/Param", "Type"]
        )
        self.case_table.setRowCount(len(self._case_definitions))
        for row, case in enumerate(self._case_definitions):
            command_definition = self._command_definitions_by_name[case.command_key]
            schema = command_definition.parameter_schema or {}
            kind = str(schema.get("kind", "none"))

            checkbox = QCheckBox()
            checkbox.setObjectName(f"TextFitConfigCaseCheck_{case.case_id}")
            checkbox.setChecked(bool(case.selected_by_default))
            checkbox.toggled.connect(self._refresh_run_button_state)
            checkbox_host = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_host)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            self.case_table.setCellWidget(row, 0, checkbox_host)

            command_text = str(command_definition.text_command or case.name)
            name_item = QTableWidgetItem(command_text)
            name_item.setData(Qt.ItemDataRole.UserRole, case.case_id)
            self.case_table.setItem(row, 1, name_item)
            value_input = QLineEdit()
            value_input.setObjectName(f"TextFitConfigValueInput_{case.case_id}")
            value_input.setText("" if case.parameter_value is None else str(case.parameter_value))
            value_input.setEnabled(kind != "none")
            value_input.setPlaceholderText("No value required" if kind == "none" else str(schema.get("label", "Value")))
            if kind == "none":
                value_input.setStyleSheet("background-color: #eee;")
            self.case_table.setCellWidget(row, 2, value_input)
            type_text = str((command_definition.text_command or "").rstrip("=")[-1:] and "Action")
            if str(command_definition.text_command or "").endswith("?"):
                type_text = "QUERY"
            elif str(command_definition.text_command or "").endswith("="):
                type_text = "SET"
            self.case_table.setItem(row, 3, QTableWidgetItem(type_text.upper()))

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
            value_input = self._row_value_input(row)
            if value_input is not None:
                value_input.setText("" if case.parameter_value is None else str(case.parameter_value))
        self._refresh_run_button_state()

    def _handle_run_clicked(self) -> None:
        selected_cases = self.selected_cases()
        if not selected_cases:
            self.status_label.setText("Select at least one Text FIT case before running.")
            return
        self.run_requested.emit(list(selected_cases))
        self.accept()

    def _handle_table_item_changed(self, _item: QTableWidgetItem) -> None:
        self._refresh_run_button_state()

    def _refresh_run_button_state(self) -> None:
        selected_count = len(self.selected_case_ids())
        self.run_button.setEnabled(selected_count > 0)
        if selected_count == 0:
            self.status_label.setText("Select at least one Text FIT case to run.")
        else:
            self.status_label.setText(f"Ready to run {selected_count} Text FIT case(s).")

    def _row_checkbox(self, row: int) -> QCheckBox | None:
        host = self.case_table.cellWidget(row, 0)
        if host is None:
            return None
        return host.findChild(QCheckBox)

    def _row_value_input(self, row: int) -> QLineEdit | None:
        widget = self.case_table.cellWidget(row, 2)
        if isinstance(widget, QLineEdit):
            return widget
        return widget.findChild(QLineEdit) if widget is not None else None
