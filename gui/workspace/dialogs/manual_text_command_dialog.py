"""Manual Text Command dialog for Firmware Integration."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..models import FirmwareCommandDefinition


class ManualTextCommandDialog(QDialog):
    """UI-only dialog for one manual text Firmware Integration request at a time."""

    def __init__(self, controller: FirmwareIntegrationController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._definitions: dict[str, FirmwareCommandDefinition] = {
            definition.name: definition for definition in controller.manual_text_command_definitions()
        }

        self.setWindowTitle("Manual Text Command")
        self.setModal(False)
        self.resize(760, 560)
        self.setMinimumSize(680, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        self.command_combo = QComboBox()
        self.command_combo.setObjectName("ManualTextCommandCombo")
        self.command_combo.setEditable(True)
        self.command_combo.currentTextChanged.connect(self._refresh_form_state)

        self.value_input = QLineEdit()
        self.value_input.setObjectName("ManualTextValueInput")
        self.value_input.setMaximumWidth(120)
        self.value_input.setPlaceholderText("Enter parameter...")
        self.value_input.textChanged.connect(self._refresh_send_button_state)

        self.send_button = QPushButton("Send Text")
        self.send_button.setObjectName("ManualTextSendButton")
        self.send_button.setProperty("tone", "primary")
        self.send_button.clicked.connect(self._handle_send_clicked)

        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("ManualTextCloseButton")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.close)

        controls.addWidget(QLabel("Text Command:"))
        controls.addWidget(self.command_combo)
        self.value_label = QLabel("Value:")
        controls.addWidget(self.value_label)
        controls.addWidget(self.value_input)
        controls.addWidget(self.send_button)
        controls.addWidget(self.close_button)
        controls.addStretch()
        root.addLayout(controls)

        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(8)
        status_grid.setVerticalSpacing(6)

        self.status_label = QLabel("Idle")
        self.status_label.setObjectName("ManualTextStatusLabel")
        self.status_label.setWordWrap(True)
        self.latency_label = QLabel("--")
        self.latency_label.setObjectName("ManualTextLatencyLabel")
        self.response_label = QLabel("--")
        self.response_label.setObjectName("ManualTextResponseLabel")
        self.response_label.setWordWrap(True)
        self.tx_label = QLabel("--")
        self.tx_label.setObjectName("ManualTextTxHexLabel")
        self.tx_label.setWordWrap(True)
        self.rx_label = QLabel("--")
        self.rx_label.setObjectName("ManualTextRxHexLabel")
        self.rx_label.setWordWrap(True)

        status_grid.addWidget(QLabel("Status"), 0, 0)
        status_grid.addWidget(self.status_label, 0, 1)
        status_grid.addWidget(QLabel("Latency"), 1, 0)
        status_grid.addWidget(self.latency_label, 1, 1)
        status_grid.addWidget(QLabel("Response"), 2, 0)
        status_grid.addWidget(self.response_label, 2, 1)
        status_grid.addWidget(QLabel("TX"), 3, 0)
        status_grid.addWidget(self.tx_label, 3, 1)
        status_grid.addWidget(QLabel("RX"), 4, 0)
        status_grid.addWidget(self.rx_label, 4, 1)
        root.addLayout(status_grid)

        history_header = QHBoxLayout()
        history_header.setContentsMargins(0, 0, 0, 0)
        history_header.addWidget(QLabel("TX / RX History"))
        history_header.addStretch(1)
        root.addLayout(history_header)

        self.history_output = QTextEdit()
        self.history_output.setObjectName("ManualTextHistoryOutput")
        self.history_output.setReadOnly(True)
        self.history_output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        root.addWidget(self.history_output, 1)

        self._populate_command_options()
        self._refresh_form_state()

        self._controller.status_changed.connect(self._handle_status_changed)
        self._controller.pending_state_changed.connect(self._handle_pending_state_changed)
        self._controller.manual_text_sent.connect(self._handle_manual_text_sent)
        self._controller.manual_text_result.connect(self._handle_manual_text_result)

        if self._controller.last_action:
            self.status_label.setText(str(self._controller.last_action))
        self._handle_pending_state_changed(self._controller.has_pending_firmware_request())

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._controller.has_pending_manual_text_request():
            self._controller.cancel_active_operation()
        super().closeEvent(event)

    def _populate_command_options(self) -> None:
        self.command_combo.clear()
        command_texts = []
        for definition in self._controller.manual_text_command_definitions():
            command_text = str(definition.text_command or definition.name)
            command_texts.append(command_text)
            self.command_combo.addItem(definition.name, definition.name)
        completer = QCompleter(command_texts, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.command_combo.setCompleter(completer)

    def _refresh_form_state(self) -> None:
        definition = self._current_definition()
        schema = definition.parameter_schema or {}
        kind = str(schema.get("kind", "none"))

        is_setter = "=" in str(definition.text_command or self.command_combo.currentText())
        self.value_label.setVisible(is_setter)
        self.value_input.setVisible(is_setter)
        if kind == "none":
            self.value_input.clear()
            self.value_input.setEnabled(False)
            self.value_input.setPlaceholderText("No value required")
        else:
            self.value_input.setEnabled(True)
            default_value = str(schema.get("default", "") or "")
            if not self.value_input.text().strip() and default_value:
                self.value_input.setText(default_value)
            placeholder = str(schema.get("label", "Value"))
            self.value_input.setPlaceholderText(f"Enter {placeholder.lower()}")

        self._refresh_send_button_state()

    def _refresh_send_button_state(self) -> None:
        busy = self._controller.has_pending_firmware_request()
        if busy:
            self.send_button.setEnabled(False)
            return

        definition = self._current_definition()
        schema = definition.parameter_schema or {}
        kind = str(schema.get("kind", "none"))
        if kind == "none":
            self.send_button.setEnabled(True)
            return

        self.send_button.setEnabled(bool(self.value_input.text().strip()))

    def _handle_send_clicked(self) -> None:
        definition = self._current_definition()
        value: str | None = None
        schema = definition.parameter_schema or {}
        if str(schema.get("kind", "none")) != "none":
            value = self.value_input.text().strip()
            if not value:
                self.status_label.setText(f"{definition.name} requires a value.")
                return

        self._controller.send_manual_text_command(definition.name, value)

    def _handle_status_changed(self, message: str) -> None:
        self.status_label.setText(str(message))

    def _handle_pending_state_changed(self, pending: bool) -> None:
        mode = self._controller.pending_request_mode()
        definition = self._current_definition()
        kind = str((definition.parameter_schema or {}).get("kind", "none"))
        owns_pending_text = pending and mode == "text"

        self.command_combo.setEnabled(not pending)
        self.value_input.setEnabled((not pending) and kind != "none")
        self._refresh_send_button_state()

        if pending and mode == "binary":
            self.status_label.setText("Manual Binary Command is currently active.")
        elif pending and owns_pending_text:
            self.status_label.setText("Manual Text Command is pending.")

    def _handle_manual_text_sent(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        self.tx_label.setText(str(event.get("frame_hex", "--")))
        self.rx_label.setText("--")
        self.latency_label.setText("--")
        self.response_label.setText("Waiting for response...")
        value_display = ""
        command_text = str(event.get("command_text", "") or "")
        if "=" in command_text:
            value_display = f" ({command_text})"
        self._append_history(f"TX {event.get('command_name', 'UNKNOWN')}{value_display}: {event.get('frame_hex', '--')}")

    def _handle_manual_text_result(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        status = str(event.get("status", "UNKNOWN"))
        decoded_text = str(event.get("decoded_text", "--"))
        self.response_label.setText(decoded_text)
        self.rx_label.setText(str(event.get("response_hex", "--")))
        latency_ms = event.get("latency_ms")
        if isinstance(latency_ms, (int, float)):
            self.latency_label.setText(f"{float(latency_ms):.1f} ms")
        else:
            self.latency_label.setText("--")

        if status == "PASS":
            self._append_history(
                f"RX {event.get('command_name', 'UNKNOWN')}: {event.get('response_hex', '--')} -> {decoded_text}"
            )
        else:
            self._append_history(f"{status} {event.get('command_name', 'UNKNOWN')}: {decoded_text}")

        self._refresh_send_button_state()

    def _append_history(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.history_output.append(f"[{timestamp}] {message}")

    def _current_definition(self) -> FirmwareCommandDefinition:
        entered_text = self.command_combo.currentText().strip()
        if entered_text in self._definitions:
            return self._definitions[entered_text]
        for definition in self._definitions.values():
            if definition.text_command == entered_text:
                return definition
        name = str(self.command_combo.currentData() or "")
        if name in self._definitions:
            return self._definitions[name]
        return next(iter(self._definitions.values()))
