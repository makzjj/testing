"""Production parameter controller for workbook parameter writing and verification."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..bridges import WorkspaceRuntimeBridge
from myconfig.node_display import ML20_NODE_MAP

UUID_COMMAND = 0xE0
UUID_READ_PARAM = 0x3F
UUID_WRITE_PARAM = 0x3D
UUID_RESPONSE_PARAM = 0x3A
PWM_SET_COMMAND = 0x84
PWM_GET_COMMAND = 0x85
PWM_WRITE_RESPONSE_PARAM = 0x53
EEPROM_SAVE_COMMAND = 0xC5
SET_COMMAND_SUFFIX = 0x21
UUID_VERIFY_TIMEOUT_MS = 3000
EEPROM_SAVE_SETTLE_MS = 2000
UUID_MAX_40BIT_VALUE = 0xFFFFFFFFFF
UUID_DECIMAL_LENGTH = 10
PWM_MAX_16BIT_VALUE = 0xFFFF
GAIN_SCALE = 1_000_000
# Decimal segment lengths: 1(prefix) + 2(year) + 2(week) + 2(node-id) + 3(running-number).
UUID_DECIMAL_FORMAT = "1YYWWNNRRR"
UUID_DECIMAL_FORMAT_DESCRIPTION = "Prefix-Year-Week-Node-RunningNumber"
MIN_TESTABLE_NODE_ID = 3
MAX_TESTABLE_NODE_ID = 12

PID_P_COMMAND = 0xE7
PID_I_COMMAND = 0xE7
PID_D_COMMAND = 0xE7
PID_SLEW_RATE_COMMAND = 0xED
RAMPDOWN_SLOPE_COMMAND = 0x89
RAMPDOWN_STEP_COMMAND = 0x8B
RAMPDOWN_MINVEL_COMMAND = 0x8C
RAMPDOWN_TARGET_OFFSET_COMMAND = 0xE1
RAMPDOWN_REGION_COMMAND = 0xE2
ACCEPTABLE_ERROR_COMMAND = 0xEC

PID_P_SUB_ID = 0x70
PID_I_SUB_ID = 0x69
PID_D_SUB_ID = 0x64

PARAM_WRITE = 0x3D
PARAM_READ = 0x3F
PARAM_RESPONSE = 0x3A


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
    command_id: int
    write_operator: int | None
    read_operator: int | None
    write_response_operator: int | None
    read_response_operator: int | None
    value_size: int
    signed: bool
    persistent: bool
    sub_id: int | None
    parse_expected: Callable[[object], Any]
    build_write_command: Callable[[Any], list[int]] | None
    build_read_command: Callable[[], list[int]] | None
    decode_response: Callable[[list[int] | tuple[int, ...]], tuple[bool, Any | None, str]] | None
    format_actual: Callable[[Any, str], str]
    compare: Callable[[Any, str, Any, str], bool]
    display_label: str = ""
    scale: int = 1

    @property
    def label(self) -> str:
        return self.display_label or self.name

    @property
    def response_command(self) -> int | None:
        return self.read_response_operator


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


def _encode_big_endian_integer(value: int, size: int, *, signed: bool) -> list[int]:
    if size not in {1, 2, 4, 5}:
        raise ValueError(f"Unsupported integer size {size}.")
    minimum = -(1 << (size * 8 - 1)) if signed else 0
    maximum = (1 << (size * 8 - 1)) - 1 if signed else (1 << (size * 8)) - 1
    coerced = int(value)
    if coerced < minimum:
        coerced = minimum
    if coerced > maximum:
        coerced = maximum
    return list(coerced.to_bytes(size, byteorder="big", signed=signed))


def _decode_big_endian_integer(payload: list[int] | tuple[int, ...], *, size: int, signed: bool, start_index: int) -> int:
    if len(payload) < start_index + size:
        raise ValueError("Integer response payload is too short.")
    raw = bytes(int(payload[start_index + offset]) & 0xFF for offset in range(size))
    return int.from_bytes(raw, byteorder="big", signed=signed)


def _parse_integer_text(value: object, *, signed: bool, minimum: int, maximum: int, label: str) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} value is required.")
    try:
        parsed = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"{label} value '{text}' is not a valid integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} value must be between {minimum} and {maximum}.")
    if not signed and parsed < 0:
        raise ValueError(f"{label} value must be non-negative.")
    return parsed


def _parse_scaled_gain_value(value: object) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("PID gain value is required.")
    try:
        if any(marker in text for marker in (".", "e", "E")):
            gain = float(text)
            scaled = int(round(gain * GAIN_SCALE))
        else:
            scaled = int(text, 10)
    except ValueError as exc:
        raise ValueError(f"PID gain value '{text}' is not valid.") from exc
    if scaled < -(1 << 31) or scaled > (1 << 31) - 1:
        raise ValueError("PID gain exceeds 4-byte signed command encoding range.")
    return scaled


def _format_scaled_gain_actual(actual_value: object, expected_text: str) -> str:
    expected = str(expected_text).strip()
    raw_value = int(actual_value)
    if any(marker in expected for marker in (".", "e", "E")):
        gain = raw_value / GAIN_SCALE
        formatted = f"{gain:.6f}".rstrip("0").rstrip(".")
        return formatted or "0"
    return f"{raw_value:d}"


def _build_parameter_payload(command_id: int, operator: int, *, sub_id: int | None = None, value_bytes: list[int] | None = None) -> list[int]:
    payload = [command_id, operator]
    if sub_id is not None:
        payload.append(sub_id & 0xFF)
    if value_bytes:
        payload.extend(int(byte) & 0xFF for byte in value_bytes)
    return payload


def _decode_parameter_response(
    payload: list[int] | tuple[int, ...],
    *,
    command_id: int,
    response_operator: int,
    value_size: int,
    signed: bool,
    sub_id: int | None = None,
    value_index: int = 2,
) -> tuple[bool, int | None, str]:
    if len(payload) < value_index + value_size:
        return False, None, "Parameter response payload is too short."
    if int(payload[0]) != command_id:
        return False, None, f"Parameter response command is not 0x{command_id:02X}."
    if int(payload[1]) != response_operator:
        return False, None, f"Parameter response operator is not 0x{response_operator:02X}."
    if sub_id is not None:
        if len(payload) < 3:
            return False, None, "Parameter response payload is too short."
        if int(payload[2]) != sub_id:
            return False, None, f"Parameter response sub-id is not 0x{sub_id:02X}."
        value_index = 3
    try:
        value = _decode_big_endian_integer(payload, size=value_size, signed=signed, start_index=value_index)
    except ValueError as exc:
        return False, None, str(exc)
    return True, value, ""


def _build_parameter_write_payload(
    *,
    command_id: int,
    write_operator: int,
    value: int,
    value_size: int,
    signed: bool,
    sub_id: int | None = None,
) -> list[int]:
    return _build_parameter_payload(
        command_id,
        write_operator,
        sub_id=sub_id,
        value_bytes=_encode_big_endian_integer(value, value_size, signed=signed),
    )


def _build_parameter_read_payload(
    *,
    command_id: int,
    read_operator: int,
    sub_id: int | None = None,
) -> list[int]:
    return _build_parameter_payload(command_id, read_operator, sub_id=sub_id)


def build_uuid_read_payload() -> list[int]:
    return [UUID_COMMAND, UUID_READ_PARAM]


def build_uuid_write_payload(uuid_int: int, uuid_hi: int = 0) -> list[int]:
    hi, b3, b2, b1, b0 = split_uuid_to_bytes(uuid_int, uuid_hi)
    return [UUID_COMMAND, UUID_WRITE_PARAM, hi, b3, b2, b1, b0]


def parse_pwm_value(value: object) -> int:
    text = str(value).strip()
    if not text:
        raise ValueError("PWM value is required.")
    try:
        parsed = int(text, 10)
    except ValueError as exc:
        raise ValueError("PWM value must contain digits only.") from exc
    if parsed < -(1 << 15) or parsed > (1 << 15) - 1:
        raise ValueError("PWM value exceeds 16-bit command encoding range.")
    return parsed


def build_pwm_write_payload(pwm_value: int) -> list[int]:
    safe_value = max(-(1 << 15), min((1 << 15) - 1, int(pwm_value)))
    return [PWM_SET_COMMAND, (safe_value >> 8) & 0xFF, safe_value & 0xFF]


def build_pwm_read_payload() -> list[int]:
    return [PWM_GET_COMMAND]


def build_eeprom_save_payload() -> list[int]:
    return [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]


# --- Consolidated motor-control command builders ---
# These helpers were previously introduced in data/binary_cmd_builders.py.
# To keep a single source of truth for payload builders (consistent with
# existing UUID/PWM helpers), we co-locate them here next to other builders.

def build_hunting_timeout(timeout_ms: int) -> list[int]:
    """Build HUNTING timeout payload: C3 21 <hi> <lo>.

    The timeout is clamped to 0..65535 ms.
    """
    value = max(0, min(0xFFFF, int(timeout_ms)))
    return [0xC3, 0x21, (value >> 8) & 0xFF, value & 0xFF]


def build_getpos() -> list[int]:
    """Build GETPOS command: 82."""
    return [0x82]


def build_run(velocity: int) -> list[int]:
    """Build RUN command: 88 <vel_hi> <vel_lo>, signed int16 big-endian."""
    vel = int(velocity)
    if vel < -32768:
        vel = -32768
    if vel > 32767:
        vel = 32767
    vel &= 0xFFFF
    return [0x88, (vel >> 8) & 0xFF, vel & 0xFF]


def build_tpos(position: int) -> list[int]:
    """Build TPOS absolute: 81 <pos_b3> <pos_b2> <pos_b1> <pos_b0> (signed int32 BE)."""
    pos = int(position) & 0xFFFFFFFF
    return [0x81, (pos >> 24) & 0xFF, (pos >> 16) & 0xFF, (pos >> 8) & 0xFF, pos & 0xFF]


def build_stopmotor() -> list[int]:
    """Build STOPMOTOR command: DD."""
    return [0xDD]


def decode_pwm_response(payload: list[int] | tuple[int, ...]) -> tuple[bool, int | None, str]:
    if not payload:
        return False, None, "PWM response payload is empty."
    command = int(payload[0]) & 0xFF
    if command == PWM_SET_COMMAND:
        if len(payload) < 4:
            return False, None, "PWM write response payload is too short."
        if int(payload[1]) & 0xFF != PWM_WRITE_RESPONSE_PARAM:
            return False, None, "PWM write response param is not 0x53."
        pwm_value = int.from_bytes(
            bytes([(int(payload[2]) & 0xFF), (int(payload[3]) & 0xFF)]),
            byteorder="big",
            signed=True,
        )
        return True, pwm_value, ""
    if command == PWM_GET_COMMAND:
        if len(payload) < 3:
            return False, None, "PWM response payload is too short."
        pwm_value = int.from_bytes(bytes([(int(payload[1]) & 0xFF), (int(payload[2]) & 0xFF)]), byteorder="big", signed=True)
        return True, pwm_value, ""
    return False, None, "PWM response command is not 0x84/0x85."


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


def _decode_5byte_parameter_response(
    payload: list[int] | tuple[int, ...],
    *,
    command_id: int,
    response_operator: int,
    sub_id: int,
) -> tuple[bool, int | None, str]:
    if len(payload) < 7:
        return False, None, "Parameter response payload is too short."
    if int(payload[0]) != command_id:
        return False, None, f"Parameter response command is not 0x{command_id:02X}."
    if int(payload[1]) != response_operator:
        return False, None, f"Parameter response operator is not 0x{response_operator:02X}."
    if int(payload[2]) != sub_id:
        return False, None, f"Parameter response sub-id is not 0x{sub_id:02X}."
    value = (
        ((payload[3] & 0xFF) << 24)
        | ((payload[4] & 0xFF) << 16)
        | ((payload[5] & 0xFF) << 8)
        | (payload[6] & 0xFF)
    )
    return True, value, ""


def _format_uuid_actual(actual_value: object, expected_text: str) -> str:
    return format_uuid_like_source(int(actual_value), expected_text)


def _format_decimal_actual(actual_value: object, _expected_text: str) -> str:
    return f"{int(actual_value):d}"


def _format_signed_decimal_actual(actual_value: object, _expected_text: str) -> str:
    return f"{int(actual_value):d}"


def _compare_text_case_aware(_expected_value: object, expected_text: str, _actual_value: object, actual_text: str) -> bool:
    if expected_text.lower().startswith("0x"):
        return actual_text.lower() == expected_text.lower()
    return actual_text == expected_text


def _compare_integer_text(expected_value: object, _expected_text: str, actual_value: object, _actual_text: str) -> bool:
    return parse_pwm_value(expected_value) == parse_pwm_value(actual_value)


def _compare_raw_int(expected_value: object, _expected_text: str, actual_value: object, _actual_text: str) -> bool:
    return int(expected_value) == int(actual_value)


def _compare_scaled_gain(expected_value: object, _expected_text: str, actual_value: object, _actual_text: str) -> bool:
    return int(expected_value) == int(actual_value)


def _make_parameter_definition(
    *,
    name: str,
    display_label: str,
    expected_cell: str,
    actual_cell: str,
    result_cell: str,
    command_id: int,
    write_operator: int | None,
    read_operator: int | None,
    write_response_operator: int | None,
    read_response_operator: int | None,
    value_size: int,
    signed: bool,
    persistent: bool,
    sub_id: int | None,
    parse_expected: Callable[[object], Any],
    format_actual: Callable[[Any, str], str],
    compare: Callable[[Any, str, Any, str], bool],
    scale: int = 1,
) -> ParameterDefinition:
    def _build_write_command(value: Any) -> list[int]:
        if name == "UUID":
            return build_uuid_write_payload(int(value))
        if name == "PWM":
            return build_pwm_write_payload(int(value))
        if write_operator is None:
            return []
        return _build_parameter_write_payload(
            command_id=command_id,
            write_operator=write_operator,
            value=int(value),
            value_size=value_size,
            signed=signed,
            sub_id=sub_id,
        )

    def _build_read_command() -> list[int]:
        if read_operator is None:
            return []
        if name == "UUID":
            return build_uuid_read_payload()
        if name == "PWM":
            return build_pwm_read_payload()
        return _build_parameter_read_payload(command_id=command_id, read_operator=read_operator, sub_id=sub_id)

    def _decode_response(payload: list[int] | tuple[int, ...]) -> tuple[bool, Any | None, str]:
        if name == "UUID":
            return decode_uuid_response(payload)
        if name == "PWM":
            return decode_pwm_response(payload)
        if value_size == 5:
            return _decode_5byte_parameter_response(
                payload,
                command_id=command_id,
                response_operator=read_response_operator if read_response_operator is not None else PARAM_RESPONSE,
                sub_id=sub_id if sub_id is not None else 0,
            )
        if read_response_operator is None:
            return False, None, f"{name} response parser is unavailable."
        decoded_ok, actual_value, error = _decode_parameter_response(
            payload,
            command_id=command_id,
            response_operator=read_response_operator,
            value_size=value_size,
            signed=signed,
            sub_id=sub_id,
        )
        return decoded_ok, actual_value, error

    return ParameterDefinition(
        name=name,
        display_label=display_label,
        expected_cell=expected_cell,
        actual_cell=actual_cell,
        result_cell=result_cell,
        command_id=command_id,
        write_operator=write_operator,
        read_operator=read_operator,
        write_response_operator=write_response_operator,
        read_response_operator=read_response_operator,
        value_size=value_size,
        signed=signed,
        persistent=persistent,
        sub_id=sub_id,
        parse_expected=parse_expected,
        build_write_command=_build_write_command,
        build_read_command=_build_read_command,
        decode_response=_decode_response,
        format_actual=format_actual,
        compare=compare,
        scale=scale,
    )


def default_workbook_parameter_definitions() -> tuple[ParameterDefinition, ...]:
    return (
        _make_parameter_definition(
            name="UUID",
            display_label="S/N",
            expected_cell="B5",
            actual_cell="C5",
            result_cell="D5",
            command_id=UUID_COMMAND,
            write_operator=UUID_WRITE_PARAM,
            read_operator=UUID_READ_PARAM,
            write_response_operator=UUID_RESPONSE_PARAM,
            read_response_operator=UUID_RESPONSE_PARAM,
            value_size=5,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=parse_uuid_value,
            format_actual=_format_uuid_actual,
            compare=_compare_text_case_aware,
        ),
        _make_parameter_definition(
            name="PWM",
            display_label="PWM",
            expected_cell="B6",
            actual_cell="C6",
            result_cell="D6",
            command_id=PWM_SET_COMMAND,
            write_operator=None,
            read_operator=PWM_GET_COMMAND,
            write_response_operator=PWM_SET_COMMAND,
            read_response_operator=PWM_GET_COMMAND,
            value_size=2,
            signed=True,
            persistent=False,
            sub_id=None,
            parse_expected=parse_pwm_value,
            format_actual=_format_signed_decimal_actual,
            compare=_compare_integer_text,
        ),
        _make_parameter_definition(
            name="PID_P",
            display_label="Proportionate (P)",
            expected_cell="B7",
            actual_cell="C7",
            result_cell="D7",
            command_id=PID_P_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=4,
            signed=True,
            persistent=True,
            sub_id=PID_P_SUB_ID,
            parse_expected=_parse_scaled_gain_value,
            format_actual=_format_scaled_gain_actual,
            compare=_compare_scaled_gain,
            scale=GAIN_SCALE,
        ),
        _make_parameter_definition(
            name="PID_I",
            display_label="Integral (I)",
            expected_cell="B8",
            actual_cell="C8",
            result_cell="D8",
            command_id=PID_I_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=4,
            signed=True,
            persistent=True,
            sub_id=PID_I_SUB_ID,
            parse_expected=_parse_scaled_gain_value,
            format_actual=_format_scaled_gain_actual,
            compare=_compare_scaled_gain,
            scale=GAIN_SCALE,
        ),
        _make_parameter_definition(
            name="PID_D",
            display_label="Derivative (D)",
            expected_cell="B9",
            actual_cell="C9",
            result_cell="D9",
            command_id=PID_D_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=4,
            signed=True,
            persistent=True,
            sub_id=PID_D_SUB_ID,
            parse_expected=_parse_scaled_gain_value,
            format_actual=_format_scaled_gain_actual,
            compare=_compare_scaled_gain,
            scale=GAIN_SCALE,
        ),
        _make_parameter_definition(
            name="PID_SlewRate",
            display_label="PID_SlewRate",
            expected_cell="B10",
            actual_cell="C10",
            result_cell="D10",
            command_id=PID_SLEW_RATE_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=2,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=False, minimum=0, maximum=0xFFFF, label="PID_SlewRate"),
            format_actual=_format_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="RampDown_Slope",
            display_label="RampDown_Slope",
            expected_cell="B11",
            actual_cell="C11",
            result_cell="D11",
            command_id=RAMPDOWN_SLOPE_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=2,
            signed=True,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=True, minimum=-(1 << 15), maximum=(1 << 15) - 1, label="RampDown_Slope"),
            format_actual=_format_signed_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="RampDown_Step",
            display_label="RampDown_Step",
            expected_cell="B12",
            actual_cell="C12",
            result_cell="D12",
            command_id=RAMPDOWN_STEP_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=1,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=False, minimum=0, maximum=0xFF, label="RampDown_Step"),
            format_actual=_format_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="RampDown_MinVel",
            display_label="RampDown_MinVel",
            expected_cell="B13",
            actual_cell="C13",
            result_cell="D13",
            command_id=RAMPDOWN_MINVEL_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=1,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=False, minimum=0, maximum=0xFF, label="RampDown_MinVel"),
            format_actual=_format_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="RampDown_TargetOffset",
            display_label="RampDown_TargetOffset",
            expected_cell="B14",
            actual_cell="C14",
            result_cell="D14",
            command_id=RAMPDOWN_TARGET_OFFSET_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=2,
            signed=True,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=True, minimum=-(1 << 15), maximum=(1 << 15) - 1, label="RampDown_TargetOffset"),
            format_actual=_format_signed_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="RampDown_Region",
            display_label="RampDown_Region",
            expected_cell="B15",
            actual_cell="C15",
            result_cell="D15",
            command_id=RAMPDOWN_REGION_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=1,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=False, minimum=0, maximum=100, label="RampDown_Region"),
            format_actual=_format_decimal_actual,
            compare=_compare_raw_int,
        ),
        _make_parameter_definition(
            name="Acceptable_Error",
            display_label="Acceptable_Error",
            expected_cell="B16",
            actual_cell="C16",
            result_cell="D16",
            command_id=ACCEPTABLE_ERROR_COMMAND,
            write_operator=PARAM_WRITE,
            read_operator=PARAM_READ,
            write_response_operator=PARAM_RESPONSE,
            read_response_operator=PARAM_RESPONSE,
            value_size=2,
            signed=False,
            persistent=True,
            sub_id=None,
            parse_expected=lambda value: _parse_integer_text(value, signed=False, minimum=0, maximum=0xFFFF, label="Acceptable_Error"),
            format_actual=_format_decimal_actual,
            compare=_compare_raw_int,
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
    parameter_write_finished = pyqtSignal(bool, str)
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
        self._parameter_operation_mode: str | None = None

        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.timeout.connect(self._handle_verify_timeout)
        self._pwm_verify_timer = QTimer(self)
        self._pwm_verify_timer.setSingleShot(True)
        self._pwm_verify_timer.timeout.connect(self._handle_pwm_verify_timeout)

        self._parameter_timer = QTimer(self)
        self._parameter_timer.setSingleShot(True)
        self._parameter_timer.timeout.connect(self._handle_parameter_timeout)
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

    def reset_workbook_parameter_workflow(self) -> None:
        """Clear any in-flight workbook parameter write/verify state.

        Workbook reloads must start from a clean slate so stale pending
        operations, cached pass/fail values, and settle timers do not block
        the next write or verification attempt.
        """
        self._verify_timer.stop()
        self._pwm_verify_timer.stop()
        self._parameter_timer.stop()
        self._eeprom_save_timer.stop()
        self._eeprom_settle_timer.stop()

        self._verify_rows = []
        self._verify_index = 0
        self._pending_row = None
        self._last_verify_actual_uuid = None
        self._last_verify_actual_uuid_text = ""
        self._last_verify_raw_response_hex = ""
        self._pending_pwm_row = None
        self._last_verify_actual_pwm = None
        self._last_verify_actual_pwm_text = ""
        self._last_verify_pwm_raw_response_hex = ""

        self._parameter_requests = []
        self._parameter_results = []
        self._parameter_verify_index = 0
        self._pending_parameter_request = None
        self._parameter_operation_mode = None

        self._pending_eeprom_save = None
        self._eeprom_settle_active = False

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
        if self._pending_parameter_request is not None or self._parameter_operation_mode is not None:
            return False, "A workbook parameter operation is already in progress."

        self._attach_runtime_window(_runtime_window)
        self._parameter_requests = [request for request in requests if request.definition.build_write_command is not None]
        self._parameter_results = []
        self._parameter_verify_index = 0
        self._pending_parameter_request = None
        self._parameter_operation_mode = "write"
        self._last_verify_actual_uuid = None
        self._last_verify_actual_uuid_text = ""
        self._last_verify_raw_response_hex = ""
        self._last_verify_actual_pwm = None
        self._last_verify_actual_pwm_text = ""
        self._last_verify_pwm_raw_response_hex = ""
        if not self._parameter_requests:
            self._parameter_operation_mode = None
            self.parameter_write_finished.emit(True, "No writable workbook parameters were defined.")
            return True, "No writable workbook parameters were defined."

        self._send_next_parameter_write_request()
        labels = "/".join(request.definition.label for request in self._parameter_requests)
        return True, f"{labels} write started for Node {first.node_id} {first.node_name}."

    def _send_next_parameter_write_request(self) -> None:
        if self._parameter_verify_index >= len(self._parameter_requests):
            self._parameter_timer.stop()
            self._pending_parameter_request = None
            self._parameter_operation_mode = None
            self._parameter_requests = []
            self._parameter_verify_index = 0
            self.parameter_write_finished.emit(True, "Workbook parameter write completed.")
            return

        request = self._parameter_requests[self._parameter_verify_index]
        definition = request.definition
        if definition.build_write_command is None:
            self._parameter_verify_index += 1
            self._send_next_parameter_write_request()
            return

        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is None or not backend_client.is_connected():
            self._finish_parameter_write_failure(
                f"{definition.label} write failed: serial port not connected."
            )
            return

        self._pending_parameter_request = request
        payload = definition.build_write_command(request.expected_value)
        self.log_message.emit(f"[Production] Writing {definition.label} for Node {request.node_id}")
        try:
            backend_client.send_command_bytes(request.node_id, payload)
        except Exception as exc:
            self._finish_parameter_write_failure(
                f"Failed to write {definition.label} for Node {request.node_id} {request.node_name}: {exc}"
            )
            return
        self._parameter_timer.start(self._timeout_ms)
        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] TX[{definition.label} Write] -> Node {request.node_id:02d}: {payload_text}")

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
        if self._pending_parameter_request is not None or self._parameter_operation_mode is not None:
            self.parameter_verification_finished.emit(False, "A workbook parameter operation is already in progress.", [])
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
        self._parameter_operation_mode = "verify"
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
                f"Selected node {node_id} {node_name} is not supported for workbook parameter operations "
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
        if self._pending_parameter_request is not None and self._pending_parameter_packet_matches(cmd):
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

    def _pending_parameter_packet_matches(self, cmd: int) -> bool:
        request = self._pending_parameter_request
        if request is None:
            return False
        definition = request.definition
        if definition.name == "PWM" and self._parameter_operation_mode == "verify":
            expected_command = PWM_GET_COMMAND
        else:
            expected_command = definition.command_id
        if expected_command is None:
            return False
        return int(cmd) == int(expected_command)

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
            # Ignore packet from a different node; do not fail active verify
            raw_cmd = int(packet.get("cmd", -1))
            raw_params = packet.get("params") or []
            raw_hex = " ".join(f"{int(v) & 0xFF:02X}" for v in [raw_cmd, *raw_params])
            self.log_message.emit(
                f"[Production][DEBUG] Ignored PWM packet from Node {sender:02d} (expected {pending_row.node_id:02d}), cmd {raw_cmd:02X}, raw: {raw_hex}"
            )
            return

        cmd = int(packet.get("cmd", -1))
        params = packet.get("params")
        if not isinstance(params, list):
            # Malformed; ignore and do not fail verify
            self.log_message.emit(
                f"[Production][DEBUG] Ignored malformed PWM packet from Node {sender:02d}: missing params"
            )
            return
        decoded_ok, actual_pwm, error = decode_pwm_response([cmd, *params])
        if not decoded_ok:
            # Wrong command or invalid payload; ignore and do not fail verify
            self.log_message.emit(
                f"[Production][DEBUG] Ignored non-PWM packet during PWM verify from Node {sender:02d}: {error or 'decode failed'}"
            )
            return
        if actual_pwm is None:
            # Should not happen if decoded_ok, but guard anyway
            self.log_message.emit(
                f"[Production][DEBUG] Ignored undecodable PWM packet from Node {sender:02d}: actual is None"
            )
            return

        self._last_verify_actual_pwm = actual_pwm
        self._last_verify_actual_pwm_text = f"{actual_pwm:d}"
        self._last_verify_pwm_raw_response_hex = " ".join(f"{value & 0xFF:02X}" for value in [cmd, *params])
        # Include raw RX details for traceability
        self.log_message.emit(
            f"[Production] PWM RX <- Node {pending_row.node_id:02d}, cmd {cmd:02X}, raw: {self._last_verify_pwm_raw_response_hex} -> {actual_pwm}"
        )

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
        # Clear last-actual fields to avoid any reuse after timeout
        self._last_verify_actual_pwm = None  # type: ignore[assignment]
        self._last_verify_actual_pwm_text = None  # type: ignore[assignment]
        self._last_verify_pwm_raw_response_hex = ""
        self._finish_pwm_verify_failure(
            f"Timed out waiting for PWM read-back from Node {row.node_id} {row.node_name}."
        )

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
            self._parameter_timer.stop()
            self._pending_parameter_request = None
            self._parameter_operation_mode = None
            self._parameter_requests = []
            self._parameter_verify_index = 0
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
        if definition.build_read_command is None or definition.decode_response is None or definition.read_response_operator is None:
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
        self._parameter_timer.start(self._timeout_ms)

    def _handle_runtime_packet_parameter(self, packet: dict) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        definition = request.definition
        sender = int(packet.get("sender", -1))
        if sender != request.node_id:
            if definition.name == "PWM" and self._parameter_operation_mode == "verify":
                raw_cmd = int(packet.get("cmd", -1))
                raw_params = packet.get("params") or []
                raw_hex = " ".join(f"{int(v) & 0xFF:02X}" for v in [raw_cmd, *raw_params])
                self.log_message.emit(
                    f"[Production][DEBUG] Ignored {definition.name} packet from Node {sender:02d} (expected {request.node_id:02d}), cmd {raw_cmd:02X}, raw: {raw_hex}"
                )
                return
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
            if definition.name == "PWM" and self._parameter_operation_mode == "verify":
                self.log_message.emit(
                    f"[Production][DEBUG] Ignored non-{definition.name} packet during verify from Node {sender:02d}: {error or 'decode failed'}"
                )
                return
            if self._parameter_operation_mode == "write":
                self._finish_parameter_write_failure(error or f"{definition.label} write response decode failed.")
                return
            self._record_parameter_failure(error or f"{definition.label} response decode failed.")
            return
        if actual_value is None:
            if definition.name == "PWM" and self._parameter_operation_mode == "verify":
                self.log_message.emit(
                    f"[Production][DEBUG] Ignored undecodable {definition.name} packet from Node {sender:02d}: actual is None"
                )
                return
            if self._parameter_operation_mode == "write":
                self._finish_parameter_write_failure(f"{definition.label} write response decode failed.")
                return
            self._record_parameter_failure(f"{definition.label} response decode failed.")
            return

        if self._parameter_operation_mode == "write":
            self._parameter_timer.stop()
            self._pending_parameter_request = None
            self._parameter_verify_index += 1
            self._send_next_parameter_write_request()
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
            # Log raw RX context so we can trace what produced the value
            self.log_message.emit(
                f"[Production] PWM RX <- Node {request.node_id:02d}, cmd {cmd:02X}, raw: {self._last_verify_pwm_raw_response_hex} -> {int(actual_value)}"
            )

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
        self._parameter_timer.stop()
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
        self._handle_parameter_timeout()

    def _handle_parameter_timeout(self) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        if self._parameter_operation_mode == "write":
            self._finish_parameter_write_failure(f"{request.definition.label} write timed out waiting for ACK.")
            return
        self._record_parameter_failure(
            f"{request.definition.label} read-back verification - expected {request.expected_text}, actual timeout"
        )

    def _record_parameter_failure(self, reason: str) -> None:
        request = self._pending_parameter_request
        if request is None:
            return
        self._parameter_timer.stop()
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

    def _finish_parameter_write_failure(self, reason: str) -> None:
        self._parameter_timer.stop()
        self._pending_parameter_request = None
        self._parameter_operation_mode = None
        self._parameter_requests = []
        self._parameter_verify_index = 0
        self.log_message.emit(f"[Production] {reason}")
        self.parameter_write_finished.emit(False, reason)

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
