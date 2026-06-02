"""Production parameter controller for UUID/PWM writing and verification."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..bridges import WorkspaceRuntimeBridge

UUID_COMMAND = 0xE0
UUID_READ_PARAM = 0x3F
UUID_WRITE_PARAM = 0x3D
UUID_RESPONSE_PARAM = 0x3A
PWM_SET_COMMAND = 0x84
PWM_GET_COMMAND = 0x85
EEPROM_SAVE_COMMAND = 0xC5
SET_COMMAND_SUFFIX = 0x21
UUID_VERIFY_TIMEOUT_MS = 3000
EEPROM_SAVE_SETTLE_MS = 2000
UUID_MAX_40BIT_VALUE = 0xFFFFFFFFFF
UUID_DECIMAL_LENGTH = 10
PWM_MAX_16BIT_VALUE = 0xFFFF
# Decimal segment lengths: 1(prefix) + 2(year) + 2(week) + 2(node-id) + 3(running-number).
UUID_DECIMAL_FORMAT = "1YYWWNNRRR"
UUID_DECIMAL_FORMAT_DESCRIPTION = "Prefix-Year-Week-Node-RunningNumber"
MIN_TESTABLE_NODE_ID = 3
MAX_TESTABLE_NODE_ID = 12

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


@dataclass(frozen=True)
class UuidCsvRow:
    row_index: int
    node_id: int
    node_name: str
    uuid_text: str
    uuid_int: int


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    expected_cell: str
    actual_cell: str
    result_cell: str
    parse_expected: Callable[[object], Any]
    build_write_command: Callable[[Any], list[int]] | None
    build_read_command: Callable[[], list[int]] | None
    response_command: int | None
    decode_response: Callable[[list[int] | tuple[int, ...]], tuple[bool, Any | None, str]] | None
    format_actual: Callable[[Any, str], str]
    compare: Callable[[Any, str, Any, str], bool]
    display_label: str = ""

    @property
    def label(self) -> str:
        return self.display_label or self.name


@dataclass(frozen=True)
class ParameterRequest:
    definition: ParameterDefinition
    node_id: int
    node_name: str
    expected_text: str
    expected_value: Any


@dataclass(frozen=True)
class ParameterVerificationResult:
    definition: ParameterDefinition
    expected_text: str
    actual_text: str
    passed: bool
    reason: str


def format_uuid_like_source(uuid_int: int, source_text: str) -> str:
    text = str(source_text).strip()
    if text.lower().startswith("0x"):
        hex_digits = text[2:]
        width = max(len(hex_digits), 1)
        formatter = "X" if any(char.isalpha() and char.isupper() for char in hex_digits) else "x"
        return f"{text[:2]}{uuid_int:0{width}{formatter}}"
    return f"{uuid_int:d}"


def parse_uuid_value(value: object) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("UUID is required.")

    try:
        if text.lower().startswith("0x"):
            parsed = int(text, 16)
        else:
            if not text.isdigit():
                raise ValueError("UUID decimal value must contain digits only.")
            parsed = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"UUID value '{text}' is not a valid decimal/hex number.") from exc

    if parsed < 0:
        raise ValueError("UUID must be non-negative.")
    if parsed > UUID_MAX_40BIT_VALUE:
        raise ValueError("UUID exceeds 5-byte command encoding range.")
    return parsed


def validate_uuid_format(uuid_int: int, node_id: int) -> tuple[bool, str]:
    text = f"{uuid_int:d}"
    if len(text) != UUID_DECIMAL_LENGTH:
        return (
            False,
            f"Decimal UUID must be exactly {UUID_DECIMAL_LENGTH} digits in format "
            f"{UUID_DECIMAL_FORMAT} ({UUID_DECIMAL_FORMAT_DESCRIPTION}).",
        )
    if text[0] != "1":
        return False, "Decimal UUID must start with prefix digit 1."
    expected_node_code = f"{node_id:02d}"
    actual_node_code = text[5:7]
    if actual_node_code != expected_node_code:
        return False, f"Decimal UUID node segment NN={actual_node_code} does not match node_id {expected_node_code}."
    return True, ""


def split_uuid_to_bytes(uuid_int: int, uuid_hi: int = 0) -> tuple[int, int, int, int, int]:
    """Split UUID into command bytes.

    `uuid_hi` is the explicit top byte used by the 5-byte UUID payload.
    When `uuid_hi` is left as 0 and `uuid_int` exceeds 32 bits, the high byte
    is derived from `uuid_int` so 40-bit UUID values are encoded correctly.
    """
    effective_hi = uuid_hi & 0xFF
    if uuid_int > 0xFFFFFFFF and uuid_hi == 0:
        effective_hi = (uuid_int >> 32) & 0xFF
    b3 = (uuid_int >> 24) & 0xFF
    b2 = (uuid_int >> 16) & 0xFF
    b1 = (uuid_int >> 8) & 0xFF
    b0 = uuid_int & 0xFF
    return effective_hi, b3, b2, b1, b0


def build_uuid_read_payload() -> list[int]:
    return [UUID_COMMAND, UUID_READ_PARAM]


def build_uuid_write_payload(uuid_int: int, uuid_hi: int = 0) -> list[int]:
    hi, b3, b2, b1, b0 = split_uuid_to_bytes(uuid_int, uuid_hi)
    return [UUID_COMMAND, UUID_WRITE_PARAM, hi, b3, b2, b1, b0]


def parse_pwm_value(value: object) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("PWM value is required.")
    if not text.isdigit():
        raise ValueError("PWM value must contain digits only.")
    parsed = int(text, 10)
    if parsed < 0:
        raise ValueError("PWM value must be non-negative.")
    if parsed > PWM_MAX_16BIT_VALUE:
        raise ValueError("PWM value exceeds 16-bit command encoding range.")
    return parsed


def build_pwm_write_payload(pwm_value: int) -> list[int]:
    safe_value = max(0, min(PWM_MAX_16BIT_VALUE, int(pwm_value)))
    return [PWM_SET_COMMAND, (safe_value >> 8) & 0xFF, safe_value & 0xFF]


def build_pwm_read_payload() -> list[int]:
    return [PWM_GET_COMMAND]


def build_eeprom_save_payload() -> list[int]:
    return [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]


def decode_pwm_response(payload: list[int] | tuple[int, ...]) -> tuple[bool, int | None, str]:
    if len(payload) < 3:
        return False, None, "PWM response payload is too short."
    if payload[0] != PWM_GET_COMMAND:
        return False, None, "PWM response command is not 0x85."
    pwm_value = ((payload[1] & 0xFF) << 8) | (payload[2] & 0xFF)
    return True, pwm_value, ""


def decode_eeprom_save_response(payload: list[int] | tuple[int, ...]) -> tuple[bool, str | None, str]:
    if len(payload) < 2:
        return False, None, "EEPROM save response payload is too short."
    if payload[0] != EEPROM_SAVE_COMMAND:
        return False, None, "EEPROM save response command is not 0xC5."
    ack_status = int(payload[1]) & 0xFF
    if ack_status not in {0x0A, ord("A")}:
        return False, None, f"EEPROM save response status is not ACK: {ack_status:02X}."
    if len(payload) > 3:
        return False, None, f"EEPROM save ACK response is too long: {' '.join(f'{byte & 0xFF:02X}' for byte in payload)}."
    if len(payload) == 3 and (int(payload[2]) & 0xFF) != 0x00:
        return False, None, f"EEPROM save ACK status byte is not 00: {int(payload[2]) & 0xFF:02X}."
    return True, "ACK", ""


def decode_uuid_response(payload: list[int] | tuple[int, ...]) -> tuple[bool, int | None, str]:
    if len(payload) < 7:
        return False, None, "UUID response payload is too short."
    if payload[0] != UUID_COMMAND:
        return False, None, "UUID response command is not 0xE0."
    if payload[1] != UUID_RESPONSE_PARAM:
        return False, None, "UUID response param is not 0x3A."

    uuid_value = (
        ((payload[2] & 0xFF) << 32)
        | ((payload[3] & 0xFF) << 24)
        | ((payload[4] & 0xFF) << 16)
        | ((payload[5] & 0xFF) << 8)
        | (payload[6] & 0xFF)
    )
    return True, uuid_value, ""


def _format_uuid_actual(actual_value: object, expected_text: str) -> str:
    return format_uuid_like_source(int(actual_value), expected_text)


def _format_decimal_actual(actual_value: object, _expected_text: str) -> str:
    return f"{int(actual_value):d}"


def _compare_text_case_aware(_expected_value: object, expected_text: str, _actual_value: object, actual_text: str) -> bool:
    if expected_text.lower().startswith("0x"):
        return actual_text.lower() == expected_text.lower()
    return actual_text == expected_text


def _compare_integer_text(expected_value: object, _expected_text: str, actual_value: object, _actual_text: str) -> bool:
    return parse_pwm_value(expected_value) == parse_pwm_value(actual_value)


def default_workbook_parameter_definitions() -> tuple[ParameterDefinition, ...]:
    return (
        ParameterDefinition(
            name="UUID",
            display_label="S/N",
            expected_cell="B4",
            actual_cell="C4",
            result_cell="D4",
            parse_expected=parse_uuid_value,
            build_write_command=build_uuid_write_payload,
            build_read_command=build_uuid_read_payload,
            response_command=UUID_COMMAND,
            decode_response=decode_uuid_response,
            format_actual=_format_uuid_actual,
            compare=_compare_text_case_aware,
        ),
        ParameterDefinition(
            name="PWM",
            display_label="PWM",
            expected_cell="B5",
            actual_cell="C5",
            result_cell="D5",
            parse_expected=parse_pwm_value,
            build_write_command=build_pwm_write_payload,
            build_read_command=build_pwm_read_payload,
            response_command=PWM_GET_COMMAND,
            decode_response=decode_pwm_response,
            format_actual=_format_decimal_actual,
            compare=_compare_integer_text,
        ),
    )


class ProductionParameterController(QObject):
    """Manage Production workbook parameter writing and verification.

    Responsibilities include generic ParameterDefinition pipeline orchestration,
    EEPROM save operations, and read-back verification. Legacy UUID/PWM paths
    are maintained as compatibility wrappers.
    """

    log_message = pyqtSignal(str)
    verification_finished = pyqtSignal(bool, str)
    pwm_verification_finished = pyqtSignal(bool, str)
    parameter_verification_finished = pyqtSignal(bool, str, object)
    eeprom_save_finished = pyqtSignal(bool, str)

    def __init__(
        self,
        bridge: WorkspaceRuntimeBridge,
        node_map: dict[int, str] | None = None,
        timeout_ms: int = UUID_VERIFY_TIMEOUT_MS,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._node_map = dict(node_map or ML20_NODE_MAP)
        self._timeout_ms = int(timeout_ms)
        self._rows: list[UuidCsvRow] = []
        self._errors: list[str] = []
        self._csv_path: Path | None = None

        self._runtime_window = None
        self._verify_rows: list[UuidCsvRow] = []
        self._verify_index = 0
        self._pending_row: UuidCsvRow | None = None
        self._last_verify_actual_uuid: int | None = None
        self._last_verify_actual_uuid_text: str = ""
        self._last_verify_raw_response_hex: str = ""
        self._pending_pwm_row: UuidCsvRow | None = None
        self._last_verify_actual_pwm: int | None = None
        self._last_verify_actual_pwm_text: str = ""
        self._last_verify_pwm_raw_response_hex: str = ""
        self._parameter_requests: list[ParameterRequest] = []
        self._parameter_results: list[ParameterVerificationResult] = []
        self._parameter_verify_index = 0
        self._pending_parameter_request: ParameterRequest | None = None

        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.timeout.connect(self._handle_verify_timeout)
        self._pwm_verify_timer = QTimer(self)
        self._pwm_verify_timer.setSingleShot(True)
        self._pwm_verify_timer.timeout.connect(self._handle_pwm_verify_timeout)

        self._parameter_verify_timer = QTimer(self)
        self._parameter_verify_timer.setSingleShot(True)
        self._parameter_verify_timer.timeout.connect(self._handle_parameter_verify_timeout)
        self._eeprom_save_timer = QTimer(self)
        self._eeprom_save_timer.setSingleShot(True)
        self._eeprom_save_timer.timeout.connect(self._handle_eeprom_save_timeout)
        self._eeprom_settle_timer = QTimer(self)
        self._eeprom_settle_timer.setSingleShot(True)
        self._eeprom_settle_timer.timeout.connect(self._handle_eeprom_settle_timeout)
        self._pending_eeprom_save: tuple[int, str] | None = None
        self._eeprom_settle_active = False

    @property
    def csv_path(self) -> Path | None:
        return self._csv_path

    @property
    def rows(self) -> list[UuidCsvRow]:
        return list(self._rows)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def last_verify_actual_uuid(self) -> int | None:
        return self._last_verify_actual_uuid

    @property
    def last_verify_actual_uuid_text(self) -> str:
        return self._last_verify_actual_uuid_text

    @property
    def last_verify_raw_response_hex(self) -> str:
        return self._last_verify_raw_response_hex

    @property
    def last_verify_actual_pwm(self) -> int | None:
        return self._last_verify_actual_pwm

    @property
    def last_verify_actual_pwm_text(self) -> str:
        return self._last_verify_actual_pwm_text

    @property
    def last_verify_pwm_raw_response_hex(self) -> str:
        return self._last_verify_pwm_raw_response_hex

    def has_valid_rows(self) -> bool:
        return bool(self._rows) and not self._errors

    def load_uuid_csv(self, path: str) -> bool:
        csv_path = Path(path).expanduser()
        self._csv_path = csv_path
        self._rows = []
        self._errors = []

        try:
            with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = reader.fieldnames or []
                required = ["node_id", "node_name", "uuid"]
                missing = [field for field in required if field not in headers]
                if missing:
                    self._errors.append(f"Missing required CSV column(s): {', '.join(missing)}.")
                    return False

                for row_number, row in enumerate(reader, start=2):
                    self._validate_and_add_row(row_number, row)
        except FileNotFoundError:
            self._errors.append(f"CSV file not found: {csv_path}")
            return False
        except OSError as exc:
            self._errors.append(f"Failed to read CSV file: {exc}")
            return False

        if not self._rows and not self._errors:
            self._errors.append("CSV contains no data rows.")
        return self.has_valid_rows()

    def write_loaded_uuid(self, node_id: int, node_name: str) -> tuple[bool, str]:
        if self._errors:
            return False, "CSV validation failed. Fix errors before writing UUIDs."
        if not self._rows:
            return False, "No UUID rows loaded."
        selected_row, selection_error = self._resolve_selected_row(node_id, node_name)
        if selected_row is None:
            return False, selection_error or "Selected node UUID data is unavailable."
        return self._write_uuid_row(selected_row)

    def write_uuid(
        self,
        node_id: int,
        node_name: str,
        uuid_int: int,
        *,
        expected_uuid_text: str | None = None,
    ) -> tuple[bool, str]:
        supported_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            return False, support_error
        selected_row = UuidCsvRow(
            row_index=0,
            node_id=node_id,
            node_name=supported_name or str(node_name),
            uuid_text=(expected_uuid_text or str(uuid_int)).strip(),
            uuid_int=int(uuid_int),
        )
        return self._write_uuid_row(selected_row)

    def write_pwm(self, node_id: int, node_name: str, pwm_value: int, *, expected_pwm_text: str | None = None) -> tuple[bool, str]:
        supported_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            return False, support_error
        selected_row = UuidCsvRow(
            row_index=0,
            node_id=node_id,
            node_name=supported_name or str(node_name),
            uuid_text=(expected_pwm_text or str(pwm_value)).strip(),
            uuid_int=int(pwm_value),
        )
        return self._write_pwm_row(selected_row)

    def build_parameter_request(
        self,
        definition: ParameterDefinition,
        node_id: int,
        node_name: str,
        expected_text: object,
    ) -> ParameterRequest:
        text = str(expected_text).strip()
        if not text:
            raise ValueError(f"Expected {definition.label} is unavailable from workbook cell {definition.expected_cell}.")
        expected_value = definition.parse_expected(text)
        return ParameterRequest(
            definition=definition,
            node_id=int(node_id),
            node_name=str(node_name),
            expected_text=text,
            expected_value=expected_value,
        )

    def write_parameters(self, requests: list[ParameterRequest] | tuple[ParameterRequest, ...]) -> tuple[bool, str]:
        if not requests:
            return False, "No workbook parameters are available to write."
        first = requests[0]
        _supported_name, support_error = self._resolve_supported_node(first.node_id, first.node_name)
        if support_error is not None:
            return False, support_error
        _runtime_window, backend_client, readiness_error = self._resolve_runtime_for_parameter_operation()
        if readiness_error is not None:
            return False, readiness_error
        assert backend_client is not None

        written_labels: list[str] = []
        for request in requests:
            builder = request.definition.build_write_command
            if builder is None:
                continue
            try:
                payload = builder(request.expected_value)
                backend_client.send_command_bytes(request.node_id, payload)
            except Exception as exc:
                return False, f"Failed to write {request.definition.label} for Node {request.node_id} {request.node_name}: {exc}"
            written_labels.append(request.definition.label)
        if not written_labels:
            return True, "No writable workbook parameters were defined."
        return True, f"{'/'.join(written_labels)} write sent to Node {first.node_id} {first.node_name}."

    def save_parameters_to_eeprom(self, node_id: int, node_name: str) -> bool:
        supported_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            self.eeprom_save_finished.emit(False, support_error)
            return False
        runtime_window, backend_client, readiness_error = self._resolve_runtime_for_parameter_operation()
        if readiness_error is not None:
            self.eeprom_save_finished.emit(False, readiness_error)
            return False
        assert backend_client is not None

        self._attach_runtime_window(runtime_window)
        self._eeprom_settle_timer.stop()
        self._eeprom_settle_active = False
        self._pending_eeprom_save = (node_id, supported_name or str(node_name))
        self._eeprom_save_timer.start(self._timeout_ms)
        payload = build_eeprom_save_payload()
        self.log_message.emit(f"[Production] Saving parameters to EEPROM for Node {node_id} {supported_name or node_name}")
        try:
            backend_client.send_command_bytes(node_id, payload)
        except Exception as exc:
            self._finish_eeprom_save_failure(f"Failed to request EEPROM save for Node {node_id} {supported_name or node_name}: {exc}")
            return False

        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] TX[EEPROM Save] -> Node {node_id:02d}: {payload_text}")
        return True

    def verify_parameters(self, requests: list[ParameterRequest] | tuple[ParameterRequest, ...]) -> bool:
        if not requests:
            self.parameter_verification_finished.emit(False, "No workbook parameters are available to verify.", [])
            return False
        if self._pending_eeprom_save is not None or self._eeprom_settle_active:
            self.parameter_verification_finished.emit(
                False,
                "EEPROM save settle is still active; wait before starting read-back verification.",
                [],
            )
            return False
        first = requests[0]
        _supported_name, support_error = self._resolve_supported_node(first.node_id, first.node_name)
        if support_error is not None:
            self.parameter_verification_finished.emit(False, support_error, [])
            return False
        runtime_window, _backend_client, readiness_error = self._resolve_runtime_for_parameter_operation()
        if readiness_error is not None:
            self.parameter_verification_finished.emit(False, readiness_error, [])
            return False
        self._attach_runtime_window(runtime_window)
        self._parameter_requests = list(requests)
        self._parameter_results = []
        self._parameter_verify_index = 0
        self._pending_parameter_request = None
        self._last_verify_actual_uuid = None
        self._last_verify_actual_uuid_text = ""
        self._last_verify_raw_response_hex = ""
        self._last_verify_actual_pwm = None
        self._last_verify_actual_pwm_text = ""
        self._last_verify_pwm_raw_response_hex = ""
        self._send_next_parameter_verify_request()
        return True

    def _write_uuid_row(self, selected_row: UuidCsvRow) -> tuple[bool, str]:
        _runtime_window, backend_client, readiness_error = self._resolve_runtime_for_parameter_operation()
        if readiness_error is not None:
            return False, readiness_error
        self.log_message.emit(f"[Production] Writing UUID to Node {selected_row.node_id} {selected_row.node_name}")
        try:
            payload = build_uuid_write_payload(selected_row.uuid_int)
            backend_client.send_command_bytes(selected_row.node_id, payload)
            payload_text = " ".join(f"{byte:02X}" for byte in payload)
            self.log_message.emit(f"[Production] TX[UUID Write] -> Node {selected_row.node_id:02d}: {payload_text}")
        except Exception as exc:
            return False, f"Failed to write UUID for Node {selected_row.node_id} {selected_row.node_name}: {exc}"
        return True, f"UUID write sent to Node {selected_row.node_id} {selected_row.node_name}."

    def _write_pwm_row(self, selected_row: UuidCsvRow) -> tuple[bool, str]:
        _runtime_window, backend_client, readiness_error = self._resolve_runtime_for_parameter_operation()
        if readiness_error is not None:
            return False, readiness_error
        self.log_message.emit(f"[Production] Writing PWM to Node {selected_row.node_id} {selected_row.node_name}")
        try:
            payload = build_pwm_write_payload(selected_row.uuid_int)
            backend_client.send_command_bytes(selected_row.node_id, payload)
            payload_text = " ".join(f"{byte:02X}" for byte in payload)
            self.log_message.emit(f"[Production] TX[PWM Write] -> Node {selected_row.node_id:02d}: {payload_text}")
        except Exception as exc:
            return False, f"Failed to write PWM for Node {selected_row.node_id} {selected_row.node_name}: {exc}"
        return True, f"PWM write sent to Node {selected_row.node_id} {selected_row.node_name}."

    def verify_loaded_uuid(self, node_id: int, node_name: str) -> bool:
        if self._errors:
            self.verification_finished.emit(False, "CSV validation failed. Fix errors before verification.")
            return False
        if not self._rows:
            self.verification_finished.emit(False, "No UUID rows loaded.")
            return False
        selected_row, selection_error = self._resolve_selected_row(node_id, node_name)
        if selected_row is None:
            self.verification_finished.emit(False, selection_error or "Selected node UUID data is unavailable.")
            return False
        return self._start_verify_for_row(selected_row)

    def verify_uuid(
        self,
        node_id: int,
        node_name: str,
        expected_uuid: int,
        *,
        expected_uuid_text: str | None = None,
    ) -> bool:
        supported_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            self.verification_finished.emit(False, support_error)
            return False
        selected_row = UuidCsvRow(
            row_index=0,
            node_id=node_id,
            node_name=supported_name or str(node_name),
            uuid_text=(expected_uuid_text or str(expected_uuid)).strip(),
            uuid_int=int(expected_uuid),
        )
        return self._start_verify_for_row(selected_row)

    def verify_pwm(
        self,
        node_id: int,
        node_name: str,
        expected_pwm: int,
        *,
        expected_pwm_text: str | None = None,
    ) -> bool:
        supported_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            self.pwm_verification_finished.emit(False, support_error)
            return False
        selected_row = UuidCsvRow(
            row_index=0,
            node_id=node_id,
            node_name=supported_name or str(node_name),
            uuid_text=(expected_pwm_text or str(expected_pwm)).strip(),
            uuid_int=int(expected_pwm),
        )
        return self._start_pwm_verify_for_row(selected_row)

    def _start_verify_for_row(self, selected_row: UuidCsvRow, *, runtime_window=None) -> bool:
        if runtime_window is None:
            runtime_window, _backend_client, readiness_error = self._resolve_runtime_for_uuid_operation()
            if readiness_error is not None:
                self.verification_finished.emit(False, readiness_error)
                return False
        self._attach_runtime_window(runtime_window)
        self._verify_rows = [selected_row]
        self._verify_index = 0
        self._pending_row = None
        self._last_verify_actual_uuid = None
        self._last_verify_actual_uuid_text = ""
        self._last_verify_raw_response_hex = ""
        self.log_message.emit(f"[Production] Verifying UUID for Node {selected_row.node_id} {selected_row.node_name}")
        self._send_next_verify_request()
        return True

    def _start_pwm_verify_for_row(self, selected_row: UuidCsvRow, *, runtime_window=None) -> bool:
        if runtime_window is None:
            runtime_window, _backend_client, readiness_error = self._resolve_runtime_for_uuid_operation()
            if readiness_error is not None:
                self.pwm_verification_finished.emit(False, readiness_error)
                return False
        self._attach_runtime_window(runtime_window)
        self._pending_pwm_row = None
        self._last_verify_actual_pwm = None
        self._last_verify_actual_pwm_text = ""
        self._last_verify_pwm_raw_response_hex = ""
        self.log_message.emit(f"[Production] Verifying PWM for Node {selected_row.node_id} {selected_row.node_name}")
        self._send_pwm_verify_request(selected_row)
        return True

    def _resolve_selected_row(self, node_id: int, node_name: str) -> tuple[UuidCsvRow | None, str | None]:
        expected_name, support_error = self._resolve_supported_node(node_id, node_name)
        if support_error is not None:
            return None, support_error

        matching_rows = [row for row in self._rows if row.node_id == node_id]
        if not matching_rows:
            return None, f"No UUID CSV row found for selected node {node_id} {expected_name}."
        if len(matching_rows) > 1:
            return None, f"Multiple UUID CSV rows found for selected node {node_id} {expected_name}."
        return matching_rows[0], None

    def _resolve_supported_node(self, node_id: int, node_name: str) -> tuple[str | None, str | None]:
        expected_name = self._node_map.get(node_id)
        if expected_name is None or not (MIN_TESTABLE_NODE_ID <= node_id <= MAX_TESTABLE_NODE_ID):
            return (
                None,
                f"Selected node {node_id} {node_name} is not supported for UUID operations "
                f"(allowed range: {MIN_TESTABLE_NODE_ID}-{MAX_TESTABLE_NODE_ID}).",
            )
        return expected_name, None

    def _resolve_runtime_for_uuid_operation(self) -> tuple[Any | None, Any | None, str | None]:
        runtime_window = self._bridge.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return None, None, "Runtime backend is unavailable for UUID operations."

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            return None, None, "Serial port not connected."

        if not hasattr(runtime_window, "packet_received"):
            return None, None, "Runtime packet listener is unavailable."
        return runtime_window, backend_client, None

    def _validate_and_add_row(self, row_number: int, row: dict[str, str]) -> None:
        node_id_text = str(row.get("node_id", "")).strip()
        node_name = str(row.get("node_name", "")).strip()
        uuid_text = str(row.get("uuid", "")).strip()

        try:
            node_id = int(node_id_text, 10)
        except ValueError:
            self._errors.append(f"Row {row_number}: node_id '{node_id_text}' is not a valid integer.")
            return

        expected_name = self._node_map.get(node_id)
        if expected_name is None:
            self._errors.append(f"Row {row_number}: node_id {node_id} is not defined in the ML 2.0 node map.")
            return
        if not (MIN_TESTABLE_NODE_ID <= node_id <= MAX_TESTABLE_NODE_ID):
            self._errors.append(
                f"Row {row_number}: node_id {node_id} is not testable "
                f"(allowed range: {MIN_TESTABLE_NODE_ID}-{MAX_TESTABLE_NODE_ID})."
            )
            return
        if node_name != expected_name:
            self._errors.append(
                f"Row {row_number}: node_name '{node_name}' does not match expected '{expected_name}' for node_id {node_id}."
            )
            return

        try:
            uuid_int = parse_uuid_value(uuid_text)
        except ValueError as exc:
            self._errors.append(f"Row {row_number}: {exc}")
            return

        # Hex UUID values are accepted as-is for compatibility, so strict decimal
        # format checks (1YYWWNNRRR) are only applied to non-hex CSV UUID values.
        if not uuid_text.lower().startswith("0x"):
            is_valid, reason = validate_uuid_format(uuid_int, node_id)
            if not is_valid:
                self._errors.append(f"Row {row_number}: {reason}")
                return

        self._rows.append(
            UuidCsvRow(
                row_index=row_number,
                node_id=node_id,
                node_name=node_name,
                uuid_text=uuid_text,
                uuid_int=uuid_int,
            )
        )

    def _attach_runtime_window(self, runtime_window) -> None:
        if runtime_window is self._runtime_window:
            return

        if self._runtime_window is not None and hasattr(self._runtime_window, "packet_received"):
            try:
                self._runtime_window.packet_received.disconnect(self._handle_runtime_packet)
            except (TypeError, RuntimeError):
                pass

        runtime_window.packet_received.connect(self._handle_runtime_packet)
        self._runtime_window = runtime_window

    def _send_next_verify_request(self) -> None:
        if self._verify_index >= len(self._verify_rows):
            self._verify_timer.stop()
            self._verify_rows = []
            self._pending_row = None
            self.verification_finished.emit(True, "UUID verification passed for all loaded rows.")
            return

        row = self._verify_rows[self._verify_index]
        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is None or not backend_client.is_connected():
            self._finish_verify_failure("Serial port not connected.")
            return

        self._pending_row = row
        payload = build_uuid_read_payload()
        self.log_message.emit(f"[Production] Reading UUID from Node {row.node_id} {row.node_name}")
        try:
            backend_client.send_command_bytes(row.node_id, payload)
        except Exception as exc:
            self._finish_verify_failure(f"Failed to request UUID read for Node {row.node_id} {row.node_name}: {exc}")
            return

        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] TX[UUID Read] -> Node {row.node_id:02d}: {payload_text}")
        self._verify_timer.start(self._timeout_ms)

    def _handle_runtime_packet(self, packet: object) -> None:
        if (
            self._pending_row is None
            and self._pending_pwm_row is None
            and self._pending_parameter_request is None
            and self._pending_eeprom_save is None
        ):
            return
        if not isinstance(packet, dict):
            return
        if packet.get("status") != "ok" or packet.get("type") != "can_over_uart":
            return

        cmd = int(packet.get("cmd", -1))
        if self._pending_parameter_request is not None and cmd == self._pending_parameter_request.definition.response_command:
            self._handle_runtime_packet_parameter(packet)
            return
        if self._pending_eeprom_save is not None and cmd == EEPROM_SAVE_COMMAND:
            self._handle_runtime_packet_eeprom_save(packet)
            return
        if self._pending_row is not None and cmd == UUID_COMMAND:
            self._handle_runtime_packet_uuid(packet)
            return
        if self._pending_pwm_row is not None and cmd == PWM_GET_COMMAND:
            self._handle_runtime_packet_pwm(packet)
            return

    def _handle_runtime_packet_uuid(self, packet: dict) -> None:
        sender = int(packet.get("sender", -1))
        pending_row = self._pending_row
        if pending_row is None:
            return
        if sender != pending_row.node_id:
            self._finish_verify_failure(
                f"UUID response came from wrong node (expected Node {pending_row.node_id}, got Node {sender})."
            )
            return

        cmd = int(packet.get("cmd", -1))
        params = packet.get("params")
        if not isinstance(params, list):
            self._finish_verify_failure("UUID response payload is missing params.")
            return

        decoded_ok, actual_uuid, error = decode_uuid_response([cmd, *params])
        if not decoded_ok:
            self._finish_verify_failure(error)
            return
        if actual_uuid is None:
            self._finish_verify_failure("UUID response decode failed.")
            return
        self._last_verify_actual_uuid = actual_uuid
        expected_uuid_text = pending_row.uuid_text
        actual_uuid_text = format_uuid_like_source(actual_uuid, expected_uuid_text)
        self._last_verify_actual_uuid_text = actual_uuid_text
        self._last_verify_raw_response_hex = " ".join(f"{value & 0xFF:02X}" for value in [cmd, *params])

        if expected_uuid_text.lower().startswith("0x"):
            uuids_match = actual_uuid_text.lower() == expected_uuid_text.lower()
        else:
            uuids_match = actual_uuid_text == expected_uuid_text

        if not uuids_match:
            self._finish_verify_failure(
                f"UUID read-back mismatch for Node {pending_row.node_id} {pending_row.node_name}: "
                f"expected {expected_uuid_text}, got {actual_uuid_text}."
            )
            return

        self._verify_timer.stop()
        self.log_message.emit(
            f"[Production] UUID verified for Node {pending_row.node_id} {pending_row.node_name}: {actual_uuid}"
        )
        self._verify_index += 1
        self._pending_row = None
        self._send_next_verify_request()

    def _send_pwm_verify_request(self, row: UuidCsvRow) -> None:
        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is None or not backend_client.is_connected():
            self._finish_pwm_verify_failure("Serial port not connected.")
            return

        self._pending_pwm_row = row
        payload = build_pwm_read_payload()
        self.log_message.emit(f"[Production] Reading PWM from Node {row.node_id} {row.node_name}")
        try:
            backend_client.send_command_bytes(row.node_id, payload)
        except Exception as exc:
            self._finish_pwm_verify_failure(f"Failed to request PWM read for Node {row.node_id} {row.node_name}: {exc}")
            return

        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] TX[PWM Read] -> Node {row.node_id:02d}: {payload_text}")
        self._pwm_verify_timer.start(self._timeout_ms)

    def _handle_runtime_packet_pwm(self, packet: dict) -> None:
        sender = int(packet.get("sender", -1))
        pending_row = self._pending_pwm_row
        if pending_row is None:
            return
        if sender != pending_row.node_id:
            self._finish_pwm_verify_failure(
                f"PWM response came from wrong node (expected Node {pending_row.node_id}, got Node {sender})."
            )
            return

        cmd = int(packet.get("cmd", -1))
        params = packet.get("params")
        if not isinstance(params, list):
            self._finish_pwm_verify_failure("PWM response payload is missing params.")
            return
        decoded_ok, actual_pwm, error = decode_pwm_response([cmd, *params])
        if not decoded_ok:
            self._finish_pwm_verify_failure(error)
            return
        if actual_pwm is None:
            self._finish_pwm_verify_failure("PWM response decode failed.")
            return

        self._last_verify_actual_pwm = actual_pwm
        self._last_verify_actual_pwm_text = f"{actual_pwm:d}"
        self._last_verify_pwm_raw_response_hex = " ".join(f"{value & 0xFF:02X}" for value in [cmd, *params])
        self.log_message.emit(f"[Production] PWM read-back received for Node {pending_row.node_id:02d}: {actual_pwm}")

        expected_pwm_text = pending_row.uuid_text
        if self._last_verify_actual_pwm_text != expected_pwm_text:
            self._finish_pwm_verify_failure(
                f"PWM read-back mismatch for Node {pending_row.node_id} {pending_row.node_name}: "
                f"expected {expected_pwm_text}, got {self._last_verify_actual_pwm_text}."
            )
            return

        self._pwm_verify_timer.stop()
        self._pending_pwm_row = None
        self.log_message.emit(f"[Production] PWM verified for Node {pending_row.node_id} {pending_row.node_name}: {actual_pwm}")
        self.pwm_verification_finished.emit(
            True,
            f"PWM read-back PASS for Node {pending_row.node_id} {pending_row.node_name}: expected {expected_pwm_text}, actual {actual_pwm}.",
        )

    def _handle_verify_timeout(self) -> None:
        if self._pending_row is None:
            return
        row = self._pending_row
        self._finish_verify_failure(f"Timed out waiting for UUID read-back from Node {row.node_id} {row.node_name}.")

    def _handle_pwm_verify_timeout(self) -> None:
        if self._pending_pwm_row is None:
            return
        row = self._pending_pwm_row
        self._finish_pwm_verify_failure(f"Timed out waiting for PWM read-back from Node {row.node_id} {row.node_name}.")

    def _finish_verify_failure(self, reason: str) -> None:
        self._verify_timer.stop()
        self._verify_rows = []
        self._pending_row = None
        self.log_message.emit(f"[Production] {reason}")
        self.verification_finished.emit(False, reason)

    def _finish_pwm_verify_failure(self, reason: str) -> None:
        self._pwm_verify_timer.stop()
        self._pending_pwm_row = None
        self.log_message.emit(f"[Production] {reason}")
        self.pwm_verification_finished.emit(False, reason)

    def _send_next_parameter_verify_request(self) -> None:
        if self._parameter_verify_index >= len(self._parameter_requests):
            self._parameter_verify_timer.stop()
            self._pending_parameter_request = None
            passed = all(result.passed for result in self._parameter_results)
            if passed:
                reason = "Workbook parameter read-back verification"
            else:
                failures = [result.reason for result in self._parameter_results if not result.passed]
                reason = " | ".join(failures) if failures else "Workbook parameter read-back verification failed."
            self.parameter_verification_finished.emit(passed, reason, list(self._parameter_results))
            return

        request = self._parameter_requests[self._parameter_verify_index]
        definition = request.definition
        if definition.build_read_command is None or definition.decode_response is None or definition.response_command is None:
            self._parameter_results.append(
                ParameterVerificationResult(
                    definition=definition,
                    expected_text=request.expected_text,
                    actual_text="",
                    passed=False,
                    reason=f"{definition.label} read-back is unavailable.",
                )
            )
            self._parameter_verify_index += 1
            self._send_next_parameter_verify_request()
            return

        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is None or not backend_client.is_connected():
            self._parameter_results.append(
                ParameterVerificationResult(
                    definition=definition,
                    expected_text=request.expected_text,
                    actual_text="",
                    passed=False,
                    reason=f"{definition.label} read-back failed: serial port not connected.",
                )
            )
            self._parameter_verify_index += 1
            self._send_next_parameter_verify_request()
            return

        self._pending_parameter_request = request
        payload = definition.build_read_command()
        self.log_message.emit(f"[Production] Reading {definition.label} for Node {request.node_id}")
        try:
            backend_client.send_command_bytes(request.node_id, payload)
        except Exception as exc:
            self._record_parameter_failure(f"Failed to request {definition.label} read for Node {request.node_id}: {exc}")
            return
        self._parameter_verify_timer.start(self._timeout_ms)

    def _handle_runtime_packet_parameter(self, packet: dict) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        definition = request.definition
        sender = int(packet.get("sender", -1))
        if sender != request.node_id:
            self._record_parameter_failure(
                f"{definition.label} response came from wrong node (expected Node {request.node_id}, got Node {sender})."
            )
            return

        params = packet.get("params")
        if not isinstance(params, list):
            self._record_parameter_failure(f"{definition.label} response payload is missing params.")
            return
        cmd = int(packet.get("cmd", -1))
        assert definition.decode_response is not None
        decoded_ok, actual_value, error = definition.decode_response([cmd, *params])
        if not decoded_ok:
            self._record_parameter_failure(error or f"{definition.label} response decode failed.")
            return
        if actual_value is None:
            self._record_parameter_failure(f"{definition.label} response decode failed.")
            return

        actual_text = definition.format_actual(actual_value, request.expected_text)
        normalized_expected_value = request.expected_value
        normalized_actual_value = actual_value
        if definition.parse_expected is not None:
            try:
                normalized_expected_value = definition.parse_expected(request.expected_text)
            except Exception:
                normalized_expected_value = request.expected_value
            try:
                normalized_actual_value = definition.parse_expected(actual_text)
            except Exception:
                normalized_actual_value = actual_value

        passed = definition.compare(
            normalized_expected_value,
            request.expected_text,
            normalized_actual_value,
            actual_text,
        )
        if definition.name == "UUID":
            self._last_verify_actual_uuid = int(actual_value)
            self._last_verify_actual_uuid_text = actual_text
            self._last_verify_raw_response_hex = " ".join(f"{value & 0xFF:02X}" for value in [cmd, *params])
        elif definition.name == "PWM":
            self._last_verify_actual_pwm = int(actual_value)
            self._last_verify_actual_pwm_text = actual_text
            self._last_verify_pwm_raw_response_hex = " ".join(f"{value & 0xFF:02X}" for value in [cmd, *params])

        if passed:
            reason = f"{definition.label} read-back verification"
        else:
            reason = f"{definition.label} read-back verification - expected {request.expected_text}, actual {actual_text}"
        self._parameter_results.append(
            ParameterVerificationResult(
                definition=definition,
                expected_text=request.expected_text,
                actual_text=actual_text,
                passed=passed,
                reason=reason,
            )
        )
        self._parameter_verify_timer.stop()
        self._pending_parameter_request = None
        self._parameter_verify_index += 1
        self._send_next_parameter_verify_request()

    def _handle_runtime_packet_eeprom_save(self, packet: dict) -> None:
        if self._pending_eeprom_save is None:
            return

        params = packet.get("params")
        if not isinstance(params, list):
            self._finish_eeprom_save_failure("EEPROM save ACK not received; check command payload and quiet mode.")
            return
        cmd = int(packet.get("cmd", -1))
        decoded_ok, _response_text, error = decode_eeprom_save_response([cmd, *params])
        if not decoded_ok:
            self._finish_eeprom_save_failure(error or "EEPROM save ACK not received; check command payload and quiet mode.")
            return

        self._eeprom_save_timer.stop()
        self._pending_eeprom_save = None
        self._eeprom_settle_active = True
        self._eeprom_settle_timer.start(EEPROM_SAVE_SETTLE_MS)
        self.log_message.emit("[Production] EEPROM save ACK received.")
        self.eeprom_save_finished.emit(True, "EEPROM save ACK received.")

    def _handle_parameter_verify_timeout(self) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        self._record_parameter_failure(
            f"{request.definition.label} read-back verification - expected {request.expected_text}, actual timeout"
        )

    def _record_parameter_failure(self, reason: str) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        self._parameter_verify_timer.stop()
        self._parameter_results.append(
            ParameterVerificationResult(
                definition=request.definition,
                expected_text=request.expected_text,
                actual_text="",
                passed=False,
                reason=reason,
            )
        )
        self._pending_parameter_request = None
        self._parameter_verify_index += 1
        self._send_next_parameter_verify_request()

    def _handle_eeprom_save_timeout(self) -> None:
        if self._pending_eeprom_save is None:
            return
        self.log_message.emit("[Production] Timed out waiting for EEPROM save ACK.")
        self._finish_eeprom_save_failure("EEPROM save ACK not received; check command payload and quiet mode.")

    def finish_eeprom_settle(self) -> None:
        self._handle_eeprom_settle_timeout()

    def _handle_eeprom_settle_timeout(self) -> None:
        self._eeprom_settle_timer.stop()
        self._eeprom_settle_active = False

    def _finish_eeprom_save_failure(self, reason: str) -> None:
        self._eeprom_save_timer.stop()
        self._eeprom_settle_timer.stop()
        self._pending_eeprom_save = None
        self._eeprom_settle_active = False
        self.log_message.emit(f"[Production] {reason}")
        self.eeprom_save_finished.emit(False, reason)

    def _resolve_runtime_for_parameter_operation(self) -> tuple[Any | None, Any | None, str | None]:
        runtime_window = self._bridge.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            return None, None, "Runtime backend is unavailable for Production operations."

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            return None, None, "Serial port not connected."

        if not hasattr(runtime_window, "packet_received"):
            return None, None, "Runtime packet listener is unavailable."
        return runtime_window, backend_client, None
