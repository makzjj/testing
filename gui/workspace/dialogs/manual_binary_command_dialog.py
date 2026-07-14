"""Manual Binary Command dialog for Firmware Integration."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareCommandDefinition


class ManualBinaryCommandDialog(QDialog):
    """UI-only dialog for one manual binary Firmware Integration request at a time."""

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._definitions: dict[str, FirmwareCommandDefinition] = {
            definition.name: definition for definition in controller.manual_binary_command_definitions()
        }

        self.setWindowTitle("Manual Binary Command")
        self.setModal(False)
        self.resize(860, 620)
        self.setMinimumSize(760, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        helper = QLabel(
            "Send one supported binary command at a time through the Firmware Integration controller. "
            "TX/RX history is local to this dialog."
        )
        helper.setWordWrap(True)
        helper.setObjectName("ManualBinaryHelperText")
        root.addWidget(helper)

        controls = QGridLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(8)
        controls.setVerticalSpacing(8)

        self.node_combo = QComboBox()
        self.node_combo.setObjectName("ManualBinaryNodeCombo")
        self.command_combo = QComboBox()
        self.command_combo.setObjectName("ManualBinaryCommandCombo")
        self.command_combo.currentIndexChanged.connect(self._refresh_parameter_ui)

        self.raw_hex_toggle = QCheckBox("Raw Hex")
        self.raw_hex_toggle.setObjectName("ManualBinaryRawHexToggle")
        self.raw_hex_toggle.toggled.connect(self._handle_raw_hex_toggled)

        self.raw_hex_input = QTextEdit()
        self.raw_hex_input.setObjectName("ManualBinaryRawHexInput")
        self.raw_hex_input.setFixedHeight(56)
        self.raw_hex_input.setPlaceholderText("Payload bytes only, for example: C8 3F")
        self.raw_hex_input.setEnabled(False)
        self.raw_hex_input.hide()

        self.parameter_label = QLabel("Parameter")
        self.parameter_label.setObjectName("ManualBinaryParameterLabel")
        self.parameter_spin = QSpinBox()
        self.parameter_spin.setObjectName("ManualBinaryInt16Input")
        self.parameter_spin.setRange(-32768, 32767)
        self.parameter_spin.setValue(30)

        self.parameter_text_input = QLineEdit()
        self.parameter_text_input.setObjectName("ManualBinaryParameterTextInput")

        self.parameter_placeholder = QLabel("No parameters")
        self.parameter_placeholder.setObjectName("ManualBinaryParameterPlaceholder")

        self.send_button = QPushButton("Send Binary")
        self.send_button.setObjectName("ManualBinarySendButton")
        self.send_button.setProperty("tone", "primary")
        self.send_button.clicked.connect(self._handle_send_clicked)

        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("ManualBinaryCloseButton")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)

        controls.addWidget(QLabel("Node ID:"), 0, 0)
        controls.addWidget(self.node_combo, 0, 1)
        controls.addWidget(QLabel("Cmd:"), 0, 2)
        controls.addWidget(self.command_combo, 0, 3)
        controls.addWidget(self.raw_hex_toggle, 0, 4)
        controls.addWidget(self.send_button, 0, 5)
        controls.addWidget(self.close_button, 0, 6)
        controls.addWidget(self.parameter_label, 1, 0)
        controls.addWidget(self.parameter_spin, 1, 1)
        controls.addWidget(self.parameter_text_input, 1, 1, 1, 3)
        controls.addWidget(self.parameter_placeholder, 1, 2, 1, 3)
        root.addLayout(controls)
        root.addWidget(self.raw_hex_input)

        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(8)
        status_grid.setVerticalSpacing(6)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("ManualBinaryStatusLabel")
        self.status_label.setWordWrap(True)
        self.latency_label = QLabel("--")
        self.latency_label.setObjectName("ManualBinaryLatencyLabel")
        self.decoded_label = QLabel("--")
        self.decoded_label.setObjectName("ManualBinaryDecodedResponseLabel")
        self.decoded_label.setWordWrap(True)
        self.tx_label = QLabel("--")
        self.tx_label.setObjectName("ManualBinaryTxPayloadLabel")
        self.tx_label.setWordWrap(True)
        self.rx_label = QLabel("--")
        self.rx_label.setObjectName("ManualBinaryRxHexLabel")
        self.rx_label.setWordWrap(True)

        status_grid.addWidget(QLabel("Status"), 0, 0)
        status_grid.addWidget(self.status_label, 0, 1)
        status_grid.addWidget(QLabel("Latency"), 1, 0)
        status_grid.addWidget(self.latency_label, 1, 1)
        status_grid.addWidget(QLabel("Decoded"), 2, 0)
        status_grid.addWidget(self.decoded_label, 2, 1)
        status_grid.addWidget(QLabel("TX"), 3, 0)
        status_grid.addWidget(self.tx_label, 3, 1)
        status_grid.addWidget(QLabel("RX"), 4, 0)
        status_grid.addWidget(self.rx_label, 4, 1)
        root.addLayout(status_grid)

        self.history_output = QTextEdit()
        self.history_output.setObjectName("ManualBinaryHistoryOutput")
        self.history_output.setReadOnly(True)
        self.history_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(self.history_output, 1)

        self._populate_node_options()
        self._populate_command_options()
        self._refresh_parameter_ui()

        self._controller.status_changed.connect(self._handle_status_changed)
        self._controller.pending_state_changed.connect(self._handle_pending_state_changed)
        self._controller.manual_binary_sent.connect(self._handle_manual_binary_sent)
        self._controller.manual_binary_result.connect(self._handle_manual_binary_result)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._controller.has_pending_manual_binary_request():
            self._controller.cancel_active_operation()
        super().closeEvent(event)

    def _populate_node_options(self) -> None:
        self.node_combo.clear()
        options = self._controller.get_manual_binary_node_options()
        for node_id, label in options:
            display = f"Node {int(node_id)} - {str(label)}" if str(label).strip() else f"Node {int(node_id)}"
            self.node_combo.addItem(display, int(node_id))
        if self.node_combo.count() == 0:
            self.node_combo.addItem("No nodes available", None)

    def _populate_command_options(self) -> None:
        self.command_combo.clear()
        for definition in self._controller.manual_binary_command_definitions():
            self.command_combo.addItem(str(definition.display_name or definition.name), definition.name)

    def _handle_raw_hex_toggled(self, checked: bool) -> None:
        self.raw_hex_input.setEnabled(bool(checked))
        self.raw_hex_input.setVisible(bool(checked))
        self.command_combo.setEnabled(not checked)
        self.parameter_spin.setEnabled(not checked and self._current_parameter_kind() == "int16")
        self.parameter_text_input.setEnabled(not checked and self._current_parameter_kind() not in {"none", "query_3f", "int16"})
        self.parameter_label.setEnabled(not checked)
        self.parameter_placeholder.setEnabled(not checked)
        if checked:
            self.parameter_label.hide()
            self.parameter_spin.hide()
            self.parameter_text_input.hide()
            self.parameter_placeholder.hide()
        else:
            self._refresh_parameter_ui()

    def _refresh_parameter_ui(self) -> None:
        if self.raw_hex_toggle.isChecked():
            self.parameter_label.hide()
            self.parameter_spin.hide()
            self.parameter_placeholder.hide()
            return
        definition = self._current_definition()
        parameter_schema = definition.parameter_schema or {}
        kind = str(parameter_schema.get("kind", "none"))
        if kind == "int16":
            self.parameter_label.setText(str(parameter_schema.get("label", "Parameter")))
            minimum = int(parameter_schema.get("minimum", -32768))
            maximum = int(parameter_schema.get("maximum", 32767))
            default = int(parameter_schema.get("default", 0))
            self.parameter_spin.setRange(minimum, maximum)
            self.parameter_spin.setValue(default)
            self.parameter_label.show()
            self.parameter_spin.show()
            self.parameter_text_input.hide()
            self.parameter_placeholder.hide()
            return
        if kind in {"int32", "set_3d", "bytes"}:
            self.parameter_label.setText(str(parameter_schema.get("label", "Parameter")))
            default = "" if parameter_schema.get("default") is None else str(parameter_schema.get("default"))
            self.parameter_text_input.setText(default)
            self.parameter_text_input.setPlaceholderText(default or "Value")
            self.parameter_label.show()
            self.parameter_spin.hide()
            self.parameter_text_input.show()
            self.parameter_placeholder.hide()
            return
        self.parameter_label.hide()
        self.parameter_spin.hide()
        self.parameter_text_input.hide()
        self.parameter_placeholder.show()

    def _handle_send_clicked(self) -> None:
        node_id = self.node_combo.currentData()
        if not isinstance(node_id, int):
            self.status_label.setText("Select a valid node before sending.")
            return

        if self.raw_hex_toggle.isChecked():
            self._controller.send_manual_binary_command(
                node_id=node_id,
                use_raw_hex=True,
                raw_hex_text=self.raw_hex_input.toPlainText(),
            )
            return

        definition = self._current_definition()
        parameter_value: object | None = None
        if self._current_parameter_kind() == "int16":
            parameter_value = int(self.parameter_spin.value())
        elif self._current_parameter_kind() in {"int32", "set_3d", "bytes"}:
            parameter_value = self.parameter_text_input.text()

        self._controller.send_manual_binary_command(
            node_id=node_id,
            command_name=definition.name,
            parameter_value=parameter_value,
            use_raw_hex=False,
        )

    def _handle_status_changed(self, message: str) -> None:
        self.status_label.setText(str(message))

    def _handle_pending_state_changed(self, pending: bool) -> None:
        self.send_button.setEnabled(not pending)
        self.node_combo.setEnabled(not pending)
        if not self.raw_hex_toggle.isChecked():
            self.command_combo.setEnabled(not pending)
            if self._current_parameter_kind() == "int16":
                self.parameter_spin.setEnabled(not pending)
            if self._current_parameter_kind() not in {"none", "query_3f", "int16"}:
                self.parameter_text_input.setEnabled(not pending)
        self.raw_hex_toggle.setEnabled(not pending)
        self.raw_hex_input.setEnabled(self.raw_hex_toggle.isChecked() and not pending)

    def _handle_manual_binary_sent(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        self.tx_label.setText(str(event.get("payload_hex", "--")))
        self.rx_label.setText("--")
        self.latency_label.setText("--")
        self.decoded_label.setText("Waiting for response...")
        self._append_history(
            f"TX Node {int(event.get('node_id', 0)):02d} {event.get('command_name', 'UNKNOWN')}: "
            f"{event.get('payload_hex', '--')}"
        )

    def _handle_manual_binary_result(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        status = str(event.get("status", "UNKNOWN"))
        self.rx_label.setText(str(event.get("response_hex", "--")))
        decoded_text = str(event.get("decoded_text", "--"))
        self.decoded_label.setText(decoded_text)
        latency_ms = event.get("latency_ms")
        if isinstance(latency_ms, (float, int)):
            self.latency_label.setText(f"{float(latency_ms):.1f} ms")
        else:
            self.latency_label.setText("--")

        if status == "PASS":
            self._append_history(
                f"RX Node {int(event.get('node_id', 0)):02d} {event.get('command_name', 'UNKNOWN')}: "
                f"{event.get('response_hex', '--')} -> {decoded_text}"
            )
            return

        self._append_history(
            f"{status} Node {int(event.get('node_id', 0)):02d} {event.get('command_name', 'UNKNOWN')}: {decoded_text}"
        )

    def _append_history(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history_output.append(f"[{timestamp}] {message}")

    def _current_definition(self) -> FirmwareCommandDefinition:
        name = str(self.command_combo.currentData() or self.command_combo.currentText())
        return self._definitions[name]

    def _current_parameter_kind(self) -> str:
        definition = self._current_definition()
        parameter_schema = definition.parameter_schema or {}
        return str(parameter_schema.get("kind", "none"))
