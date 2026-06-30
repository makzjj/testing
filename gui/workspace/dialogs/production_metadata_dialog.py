"""Modal dialog for Production workbook operator/assembler metadata."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox, QWidget


class ProductionMetadataDialog(QDialog):
    """Collect operator and assembler names for the active Production workbook."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        operator_name: str = "",
        assembler_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Production Workbook Metadata")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        layout.setLabelAlignment(layout.labelAlignment())

        self.operator_name_edit = QLineEdit()
        self.operator_name_edit.setObjectName("OperatorNameEdit")
        self.operator_name_edit.setPlaceholderText("Operator Name")
        self.operator_name_edit.setText(operator_name.strip())
        layout.addRow("Operator Name", self.operator_name_edit)

        self.assembler_name_edit = QLineEdit()
        self.assembler_name_edit.setObjectName("AssemblerNameEdit")
        self.assembler_name_edit.setPlaceholderText("Assembler Name")
        self.assembler_name_edit.setText(assembler_name.strip())
        layout.addRow("Assembler Name", self.assembler_name_edit)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Save")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addRow(self.button_box)

    def metadata_values(self) -> tuple[str, str]:
        """Return trimmed metadata values."""
        return self.operator_name_edit.text().strip(), self.assembler_name_edit.text().strip()

    def accept(self) -> None:  # noqa: D401
        operator_name, assembler_name = self.metadata_values()
        if not operator_name or not assembler_name:
            QMessageBox.warning(self, "Missing Metadata", "Operator Name and Assembler Name are required.")
            return
        self.operator_name_edit.setText(operator_name)
        self.assembler_name_edit.setText(assembler_name)
        super().accept()
