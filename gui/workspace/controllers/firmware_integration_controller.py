"""Single public workflow owner for Firmware Integration behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic
from typing import TYPE_CHECKING, Callable, Iterable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from data.binary_cmd_builders import (
    build_getpos,
    build_getvel_query_payload,
    build_getver_query_payload,
    build_interrupt_query_payload,
    build_motor_current_query_payload,
    build_nodeconfig_query_payload,
    build_run,
    build_vel,
)
from data.binary_cmd_parser import decode_command
from data.text_cmd_builders import build_text_command_payload, decode_text_command_response, normalize_text_command
from services.firmware_transport_adapter import FirmwareTransportAdapter

from ..models import (
    FirmwareBinaryFitSnapshot,
    FirmwareCommandDefinition,
    FirmwareTestCase,
    FirmwareTestResult,
    FirmwareTextFitSnapshot,
)

if TYPE_CHECKING:
    from ..bridges import WorkspaceRuntimeBridge


DEFAULT_MANUAL_BINARY_TIMEOUT_MS = 1500
DEFAULT_MANUAL_TEXT_TIMEOUT_MS = 1500


@dataclass(frozen=True)
class _PendingManualBinaryRequest:
    command_name: str
    node_id: int
    expected_opcode: int
    sent_payload: list[int]
    sent_frame: bytes
    sent_started_at: float
    timeout_ms: int
    used_raw_hex: bool = False


@dataclass(frozen=True)
class _PendingManualTextRequest:
    command_name: str
    command_text: str
    expected_prefix: str
    sent_frame: bytes
    sent_started_at: float
    timeout_ms: int


@dataclass(frozen=True)
class _PreparedManualBinarySend:
    command_name: str
    expected_opcode: int
    payload: list[int]
    timeout_ms: int
    used_raw_hex: bool = False


@dataclass(frozen=True)
class _PreparedManualTextSend:
    command_name: str
    command_text: str
    expected_prefix: str
    frame: bytes
    timeout_ms: int


@dataclass(frozen=True)
class _PendingBinaryFitCaseRequest:
    case: FirmwareTestCase
    command_definition: FirmwareCommandDefinition
    node_id: int
    expected_opcode: int
    sent_payload: list[int]
    sent_frame: bytes
    sent_started_at: float
    timeout_ms: int


@dataclass(frozen=True)
class _PendingTextFitCaseRequest:
    case: FirmwareTestCase
    command_definition: FirmwareCommandDefinition
    command_text: str
    expected_prefix: str
    sent_frame: bytes
    sent_started_at: float
    timeout_ms: int


@dataclass(frozen=True)
class _BinaryFitVerificationPause:
    request: _PendingBinaryFitCaseRequest
    proposed_result: FirmwareTestResult


@dataclass(frozen=True)
class _TextFitVerificationPause:
    request: _PendingTextFitCaseRequest
    proposed_result: FirmwareTestResult


@dataclass(frozen=True)
class _ActiveFirmwareOperation:
    mode: str
    request: object


def _build_manual_binary_command_definitions() -> tuple[FirmwareCommandDefinition, ...]:
    return (
        FirmwareCommandDefinition(
            name="GETVER",
            mode="binary",
            opcode=0xC8,
            parameter_schema={"kind": "none"},
            expected_response="firmware",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_getver_query_payload",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="GETPOS",
            mode="binary",
            opcode=0x82,
            parameter_schema={"kind": "none"},
            expected_response="getpos",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_getpos",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="GETVEL",
            mode="binary",
            opcode=0x85,
            parameter_schema={"kind": "none"},
            expected_response="getvel",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_getvel_query_payload",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="VEL Write",
            mode="binary",
            opcode=0x84,
            parameter_schema={"kind": "int16", "label": "Velocity", "default": 30, "minimum": -32768, "maximum": 32767},
            expected_response="velocity_ack",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_vel",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="RUN",
            mode="binary",
            opcode=0x88,
            parameter_schema={"kind": "int16", "label": "Velocity", "default": 30, "minimum": -32768, "maximum": 32767},
            expected_response="run_started",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_run",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="NODECONFIG Query",
            mode="binary",
            opcode=0xC4,
            parameter_schema={"kind": "none"},
            expected_response="nodeconfig",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_nodeconfig_query_payload",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="INTERRUPT Query",
            mode="binary",
            opcode=0xD8,
            parameter_schema={"kind": "none"},
            expected_response="interrupt",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_interrupt_query_payload",
            decoder_name="decode_command",
        ),
        FirmwareCommandDefinition(
            name="MOTOR_I Query",
            mode="binary",
            opcode=0xCF,
            parameter_schema={"kind": "none"},
            expected_response="motor_current_mA",
            timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
            builder_name="build_motor_current_query_payload",
            decoder_name="decode_command",
        ),
    )


def _build_manual_text_command_definitions() -> tuple[FirmwareCommandDefinition, ...]:
    return (
        FirmwareCommandDefinition(
            name="Version Query",
            mode="text",
            text_command="ver?",
            parameter_schema={"kind": "none"},
            expected_response="ver:",
            timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
            builder_name="build_text_command_payload",
            decoder_name="decode_text_command_response",
        ),
        FirmwareCommandDefinition(
            name="UART Status Query",
            mode="text",
            text_command="uartstat?",
            parameter_schema={"kind": "none"},
            expected_response="uartstat:",
            timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
            builder_name="build_text_command_payload",
            decoder_name="decode_text_command_response",
        ),
        FirmwareCommandDefinition(
            name="Operating Mode Query",
            mode="text",
            text_command="opmode?",
            parameter_schema={"kind": "none"},
            expected_response="opmode:",
            timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
            builder_name="build_text_command_payload",
            decoder_name="decode_text_command_response",
        ),
        FirmwareCommandDefinition(
            name="Robot Power Query",
            mode="text",
            text_command="onRB?",
            parameter_schema={"kind": "none"},
            expected_response="onRB:",
            timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
            builder_name="build_text_command_payload",
            decoder_name="decode_text_command_response",
        ),
        FirmwareCommandDefinition(
            name="Robot Power Set",
            mode="text",
            text_command="onRB=",
            parameter_schema={"kind": "choice", "choices": ("0", "1"), "default": "1", "label": "Value"},
            expected_response="onRB:",
            timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
            builder_name="build_text_command_payload",
            decoder_name="decode_text_command_response",
        ),
    )


def _build_binary_fit_case_definitions(
    command_definitions: tuple[FirmwareCommandDefinition, ...],
) -> tuple[FirmwareTestCase, ...]:
    definitions_by_name = {definition.name: definition for definition in command_definitions}
    catalog_names = (
        "GETVER",
        "GETPOS",
        "GETVEL",
        "NODECONFIG Query",
        "INTERRUPT Query",
        "MOTOR_I Query",
    )
    cases: list[FirmwareTestCase] = []
    for command_name in catalog_names:
        definition = definitions_by_name[command_name]
        case_id = f"binary-fit-{command_name.lower().replace(' ', '-').replace('_', '-')}"
        cases.append(
            FirmwareTestCase(
                case_id=case_id,
                name=command_name,
                mode="binary",
                command_key=definition.name,
                parameter_value=None,
                expected_response=definition.expected_response,
                timeout_ms=definition.timeout_ms,
                manual_verification=False,
                manual_prompt=None,
                selected_by_default=True,
                category="binary-fit",
                display_group="Manual Binary Proven Subset",
            )
        )
    return tuple(cases)


def _build_text_fit_case_definitions(
    command_definitions: tuple[FirmwareCommandDefinition, ...],
) -> tuple[FirmwareTestCase, ...]:
    definitions_by_name = {definition.name: definition for definition in command_definitions}
    catalog_names = (
        "Version Query",
        "UART Status Query",
        "Operating Mode Query",
        "Robot Power Query",
    )
    cases: list[FirmwareTestCase] = []
    for command_name in catalog_names:
        definition = definitions_by_name[command_name]
        case_id = f"text-fit-{command_name.lower().replace(' ', '-').replace('_', '-')}"
        cases.append(
            FirmwareTestCase(
                case_id=case_id,
                name=command_name,
                mode="text",
                command_key=definition.name,
                parameter_value=None,
                expected_response=definition.expected_response,
                timeout_ms=definition.timeout_ms,
                manual_verification=False,
                manual_prompt=None,
                selected_by_default=True,
                category="text-fit",
                display_group="Manual Text Proven Query Subset",
            )
        )
    return tuple(cases)


class _ManualBinaryWorkflow:
    """Private binary-mode helper for payload prep and response interpretation."""

    def __init__(self) -> None:
        self._definitions = _build_manual_binary_command_definitions()
        self._definitions_by_name = {definition.name: definition for definition in self._definitions}

    def definitions(self) -> tuple[FirmwareCommandDefinition, ...]:
        return self._definitions

    def definition(self, command_name: str | None) -> FirmwareCommandDefinition:
        normalized_name = str(command_name or "").strip()
        definition = self._definitions_by_name.get(normalized_name)
        if definition is None:
            raise ValueError(f"Unsupported manual binary command: {command_name}")
        return definition

    def prepare_send(
        self,
        *,
        command_name: str | None,
        parameter_value: object | None,
        use_raw_hex: bool,
        raw_hex_text: str | None,
    ) -> _PreparedManualBinarySend:
        if use_raw_hex:
            payload = self._parse_raw_hex_payload(raw_hex_text)
            return _PreparedManualBinarySend(
                command_name=f"RAW 0x{payload[0]:02X}",
                expected_opcode=int(payload[0]) & 0xFF,
                payload=payload,
                timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
                used_raw_hex=True,
            )

        definition = self.definition(command_name)
        return _PreparedManualBinarySend(
            command_name=definition.name,
            expected_opcode=int(definition.opcode or 0) & 0xFF,
            payload=self.build_payload(definition, parameter_value),
            timeout_ms=int(definition.timeout_ms or DEFAULT_MANUAL_BINARY_TIMEOUT_MS),
            used_raw_hex=False,
        )

    def build_payload(self, definition: FirmwareCommandDefinition, parameter_value: object | None) -> list[int]:
        builder_name = str(definition.builder_name or "").strip()
        if builder_name == "build_getver_query_payload":
            return build_getver_query_payload()
        if builder_name == "build_getpos":
            return build_getpos()
        if builder_name == "build_getvel_query_payload":
            return build_getvel_query_payload()
        if builder_name == "build_vel":
            default = (definition.parameter_schema or {}).get("default", 0)
            return build_vel(int(parameter_value if parameter_value is not None else default))
        if builder_name == "build_run":
            default = (definition.parameter_schema or {}).get("default", 0)
            return build_run(int(parameter_value if parameter_value is not None else default))
        if builder_name == "build_nodeconfig_query_payload":
            return build_nodeconfig_query_payload()
        if builder_name == "build_interrupt_query_payload":
            return build_interrupt_query_payload()
        if builder_name == "build_motor_current_query_payload":
            return build_motor_current_query_payload()
        raise ValueError(f"Unsupported firmware command builder: {builder_name or '<missing>'}")

    @staticmethod
    def accepts_response(
        request: _PendingManualBinaryRequest | _PendingBinaryFitCaseRequest,
        *,
        sender: int | None,
        cmd: int | None,
    ) -> bool:
        if sender is None or cmd is None:
            return False
        return int(sender) == request.node_id and (int(cmd) & 0xFF) == request.expected_opcode

    def build_pass_result(
        self,
        request: _PendingManualBinaryRequest,
        packet: dict[str, object],
        *,
        received_at: float,
    ) -> dict[str, object]:
        command = int(packet.get("cmd", 0)) & 0xFF
        params = [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)]
        decoded_kind, decoded_value = decode_command(command, params)
        decoded_text = self._format_decoded_response(command, decoded_kind, decoded_value)
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        raw_hex = str(packet.get("raw_hex") or self._format_hex([command, *params]))
        return {
            "status": "PASS",
            "command_name": request.command_name,
            "node_id": request.node_id,
            "payload_hex": self._format_hex(request.sent_payload),
            "frame_hex": self._format_hex(request.sent_frame),
            "response_hex": raw_hex,
            "latency_ms": latency_ms,
            "decoded_text": decoded_text,
            "decoded_kind": decoded_kind,
            "response_cmd": command,
        }

    def build_timeout_result(self, request: _PendingManualBinaryRequest) -> dict[str, object]:
        return {
            "status": "TIMEOUT",
            "command_name": request.command_name,
            "node_id": request.node_id,
            "payload_hex": self._format_hex(request.sent_payload),
            "frame_hex": self._format_hex(request.sent_frame),
            "response_hex": "--",
            "latency_ms": None,
            "decoded_text": "Timed out waiting for matching firmware response.",
            "decoded_kind": None,
            "response_cmd": request.expected_opcode,
        }

    @staticmethod
    def _parse_raw_hex_payload(raw_hex_text: str | None) -> list[int]:
        normalized = str(raw_hex_text or "").strip()
        if not normalized:
            raise ValueError("Raw hex payload is empty.")
        try:
            values = [int(value) & 0xFF for value in bytearray.fromhex(normalized)]
        except ValueError as exc:
            raise ValueError("Invalid raw hex payload.") from exc
        if not values:
            raise ValueError("Raw hex payload is empty.")
        return values

    @staticmethod
    def _format_decoded_response(cmd: int, decoded_kind: str | None, decoded_value: object) -> str:
        if decoded_kind and decoded_value is not None:
            return f"{decoded_kind}: {decoded_value}"
        if decoded_kind:
            return str(decoded_kind)
        return f"Command 0x{int(cmd) & 0xFF:02X} response received."

    @staticmethod
    def _format_hex(values: bytes | bytearray | list[int]) -> str:
        return " ".join(f"{int(value) & 0xFF:02X}" for value in list(values))


class _ManualTextWorkflow:
    """Private text-mode helper for request prep and normalized response validation."""

    def __init__(self) -> None:
        self._definitions = _build_manual_text_command_definitions()
        self._definitions_by_name = {definition.name: definition for definition in self._definitions}

    def definitions(self) -> tuple[FirmwareCommandDefinition, ...]:
        return self._definitions

    def definition(self, command_name: str | None) -> FirmwareCommandDefinition:
        normalized_name = str(command_name or "").strip()
        definition = self._definitions_by_name.get(normalized_name)
        if definition is None:
            raise ValueError(f"Unsupported manual text command: {command_name}")
        return definition

    def prepare_send(self, *, command_name: str | None, value: object | None) -> _PreparedManualTextSend:
        definition = self.definition(command_name)
        normalized_value = self._coerce_text_value(definition, value)
        text_command = str(definition.text_command or "")
        return _PreparedManualTextSend(
            command_name=definition.name,
            command_text=normalize_text_command(text_command, normalized_value),
            expected_prefix=str(definition.expected_response or "").strip(),
            frame=bytes(build_text_command_payload(text_command, normalized_value)),
            timeout_ms=int(definition.timeout_ms or DEFAULT_MANUAL_TEXT_TIMEOUT_MS),
        )

    @staticmethod
    def match_response(
        request: object,
        packet: dict[str, object],
    ) -> tuple[str, str] | None:
        expected_prefix = str(getattr(request, "expected_prefix", "") or "").strip()
        if not expected_prefix:
            return None
        return _ManualTextWorkflow.match_expected_prefix(expected_prefix=expected_prefix, packet=packet)

    @staticmethod
    def match_expected_prefix(
        *,
        expected_prefix: str,
        packet: dict[str, object],
    ) -> tuple[str, str] | None:
        raw_payload = packet.get("raw_payload")
        if not isinstance(raw_payload, list):
            return None
        response_text = decode_text_command_response(raw_payload)
        if response_text is None:
            return None
        if not response_text.startswith(str(expected_prefix).strip()):
            return None
        response_hex = str(packet.get("raw_hex") or _ManualBinaryWorkflow._format_hex(raw_payload))
        return response_text, response_hex

    def build_pass_result(
        self,
        request: _PendingManualTextRequest,
        *,
        response_text: str,
        response_hex: str,
        received_at: float,
    ) -> dict[str, object]:
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        return {
            "status": "PASS",
            "command_name": request.command_name,
            "command_text": request.command_text,
            "expected_prefix": request.expected_prefix,
            "frame_hex": _ManualBinaryWorkflow._format_hex(request.sent_frame),
            "response_hex": response_hex,
            "response_text": response_text,
            "decoded_text": response_text,
            "latency_ms": latency_ms,
        }

    def build_timeout_result(self, request: _PendingManualTextRequest) -> dict[str, object]:
        return {
            "status": "TIMEOUT",
            "command_name": request.command_name,
            "command_text": request.command_text,
            "expected_prefix": request.expected_prefix,
            "frame_hex": _ManualBinaryWorkflow._format_hex(request.sent_frame),
            "response_hex": "--",
            "response_text": None,
            "decoded_text": "Timed out waiting for matching firmware text response.",
            "latency_ms": None,
        }

    def build_cancel_result(self, request: _PendingManualTextRequest) -> dict[str, object]:
        return {
            "status": "CANCELLED",
            "command_name": request.command_name,
            "command_text": request.command_text,
            "expected_prefix": request.expected_prefix,
            "frame_hex": _ManualBinaryWorkflow._format_hex(request.sent_frame),
            "response_hex": "--",
            "response_text": None,
            "decoded_text": "Cancelled before matching firmware text response.",
            "latency_ms": None,
        }

    @staticmethod
    def _coerce_text_value(definition: FirmwareCommandDefinition, value: object | None) -> object | None:
        schema = definition.parameter_schema or {}
        kind = str(schema.get("kind", "none"))
        if kind == "none":
            if value is not None:
                raise ValueError(f"Manual text command {definition.name} does not accept a value.")
            return None

        candidate = value if value is not None else schema.get("default")
        if candidate is None:
            raise ValueError(f"Manual text command {definition.name} requires a value.")

        normalized = str(candidate).strip()
        if not normalized:
            raise ValueError(f"Manual text command {definition.name} requires a value.")

        if kind == "choice":
            choices = [str(item) for item in schema.get("choices", ())]
            if choices and normalized not in choices:
                raise ValueError(f"Manual text command {definition.name} accepts only: {', '.join(choices)}.")
        return normalized


class _BinaryFitWorkflow:
    """Private automated Binary FIT sequencer."""

    def __init__(self, catalog: tuple[FirmwareTestCase, ...]) -> None:
        self._catalog = catalog
        self.reset()

    def reset(self) -> None:
        self._selected_cases: tuple[FirmwareTestCase, ...] = ()
        self._results: list[FirmwareTestResult] = []
        self._node_id: int | None = None
        self._current_index = 0
        self._current_request: _PendingBinaryFitCaseRequest | None = None
        self._awaiting_manual_verification: _BinaryFitVerificationPause | None = None
        self._active = False

    def catalog(self) -> tuple[FirmwareTestCase, ...]:
        return self._catalog

    def start(self, *, node_id: int, selected_cases: Iterable[FirmwareTestCase]) -> None:
        cases = tuple(selected_cases)
        if not cases:
            raise ValueError("No Binary FIT cases selected.")
        self._selected_cases = cases
        self._results = []
        self._node_id = int(node_id)
        self._current_index = 0
        self._current_request = None
        self._awaiting_manual_verification = None
        self._active = True

    def is_active(self) -> bool:
        return self._active

    def is_awaiting_manual_verification(self) -> bool:
        return self._awaiting_manual_verification is not None

    def current_request(self) -> _PendingBinaryFitCaseRequest | None:
        return self._current_request

    def awaiting_manual_verification_request(self) -> _BinaryFitVerificationPause | None:
        return self._awaiting_manual_verification

    def current_index(self) -> int:
        return self._current_index

    def current_case(self) -> FirmwareTestCase | None:
        if not self._active or self._awaiting_manual_verification is not None or self._current_request is not None:
            return None
        if self._current_index >= len(self._selected_cases):
            return None
        return self._selected_cases[self._current_index]

    def display_case(self) -> FirmwareTestCase | None:
        if self._current_request is not None:
            return self._current_request.case
        if self._awaiting_manual_verification is not None:
            return self._awaiting_manual_verification.request.case
        return self.current_case()

    def has_more_cases(self) -> bool:
        return self.current_case() is not None

    def results(self) -> tuple[FirmwareTestResult, ...]:
        return tuple(self._results)

    def total_cases(self) -> int:
        return len(self._selected_cases)

    def completed_count(self) -> int:
        return len(self._results)

    def node_id(self) -> int | None:
        return self._node_id

    def record_case_sent(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        payload: list[int],
        sent_frame: bytes,
        sent_started_at: float,
    ) -> _PendingBinaryFitCaseRequest:
        if self._node_id is None:
            raise ValueError("Binary FIT node is not set.")
        request = _PendingBinaryFitCaseRequest(
            case=case,
            command_definition=command_definition,
            node_id=self._node_id,
            expected_opcode=int(command_definition.opcode or 0) & 0xFF,
            sent_payload=list(payload),
            sent_frame=sent_frame,
            sent_started_at=sent_started_at,
            timeout_ms=int(case.timeout_ms or command_definition.timeout_ms or DEFAULT_MANUAL_BINARY_TIMEOUT_MS),
        )
        self._current_request = request
        return request

    def accepts_response(self, *, sender: int | None, cmd: int | None) -> bool:
        request = self._current_request
        if request is None:
            return False
        return _ManualBinaryWorkflow.accepts_response(request, sender=sender, cmd=cmd)

    def handle_matching_response(self, packet: dict[str, object], *, received_at: float) -> tuple[FirmwareTestResult | None, dict[str, object] | None]:
        request = self._current_request
        if request is None:
            return None, None

        command = int(packet.get("cmd", 0)) & 0xFF
        params = [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)]
        decoded_kind, decoded_value = decode_command(command, params)
        expected = str(request.case.expected_response or request.command_definition.expected_response or "")
        actual = _ManualBinaryWorkflow._format_decoded_response(command, decoded_kind, decoded_value)
        response_hex = str(packet.get("raw_hex") or _ManualBinaryWorkflow._format_hex([command, *params]))
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        status = "PASS" if decoded_kind == expected else "FAIL"
        message = (
            f"Matched expected semantic response {expected}."
            if status == "PASS"
            else f"Expected semantic response {expected}, received {decoded_kind or 'unknown'}."
        )
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status=status,
            expected=expected or None,
            actual=actual,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=bytes(bytearray.fromhex(response_hex)) if response_hex != "--" else None,
            latency_ms=latency_ms,
            message=message,
            manual_verification_outcome=None,
        )
        self._current_request = None
        if request.case.manual_verification:
            self._awaiting_manual_verification = _BinaryFitVerificationPause(request=request, proposed_result=result)
            return None, {
                "case_id": request.case.case_id,
                "name": request.case.name,
                "prompt": request.case.manual_prompt or "Tester verification required.",
                "expected": result.expected,
                "actual": result.actual,
                "latency_ms": result.latency_ms,
            }

        self._results.append(result)
        self._current_index += 1
        return result, None

    def timeout_current_case(self) -> FirmwareTestResult | None:
        request = self._current_request
        if request is None:
            return None
        self._current_request = None
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="TIMEOUT",
            expected=request.case.expected_response or request.command_definition.expected_response,
            actual=None,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=None,
            latency_ms=None,
            message="Timed out waiting for matching firmware response.",
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        return result

    def record_send_failure(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        payload: list[int] | None,
        message: str,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=case.case_id,
            status="ERROR",
            expected=case.expected_response or command_definition.expected_response,
            actual=None,
            tx_bytes=None if payload is None else bytes(payload),
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def submit_manual_verification(self, *, passed: bool, message: str | None = None) -> FirmwareTestResult | None:
        pause = self._awaiting_manual_verification
        if pause is None:
            return None
        self._awaiting_manual_verification = None
        status = "PASS" if pause.proposed_result.status == "PASS" and passed else "FAIL"
        final_message = message or ("Manual verification passed." if passed else "Manual verification failed.")
        result = replace(
            pause.proposed_result,
            status=status,
            message=final_message,
            manual_verification_outcome="passed" if passed else "failed",
        )
        self._results.append(result)
        self._current_index += 1
        return result

    def cancel(self) -> FirmwareTestResult | None:
        if self._current_request is not None:
            request = self._current_request
            self._current_request = None
            result = FirmwareTestResult(
                case_id=request.case.case_id,
                status="CANCELLED",
                expected=request.case.expected_response or request.command_definition.expected_response,
                actual=None,
                tx_bytes=bytes(request.sent_frame),
                rx_bytes=None,
                latency_ms=None,
                message="Cancelled before matching firmware response.",
                manual_verification_outcome=None,
            )
            self._results.append(result)
            self._current_index += 1
            self._active = False
            return result

        if self._awaiting_manual_verification is not None:
            pause = self._awaiting_manual_verification
            self._awaiting_manual_verification = None
            result = replace(
                pause.proposed_result,
                status="CANCELLED",
                message="Cancelled while awaiting manual verification.",
                manual_verification_outcome="cancelled",
            )
            self._results.append(result)
            self._current_index += 1
            self._active = False
            return result

        self._active = False
        return None

    def mark_complete_if_done(self) -> bool:
        if self._active and self._current_index >= len(self._selected_cases) and self._current_request is None and self._awaiting_manual_verification is None:
            self._active = False
            return True
        return False


class _TextFitWorkflow:
    """Private automated Text FIT sequencer."""

    def __init__(self, catalog: tuple[FirmwareTestCase, ...]) -> None:
        self._catalog = catalog
        self.reset()

    def reset(self) -> None:
        self._selected_cases: tuple[FirmwareTestCase, ...] = ()
        self._results: list[FirmwareTestResult] = []
        self._current_index = 0
        self._current_request: _PendingTextFitCaseRequest | None = None
        self._awaiting_manual_verification: _TextFitVerificationPause | None = None
        self._active = False

    def catalog(self) -> tuple[FirmwareTestCase, ...]:
        return self._catalog

    def start(self, *, selected_cases: Iterable[FirmwareTestCase]) -> None:
        cases = tuple(selected_cases)
        if not cases:
            raise ValueError("No Text FIT cases selected.")
        self._selected_cases = cases
        self._results = []
        self._current_index = 0
        self._current_request = None
        self._awaiting_manual_verification = None
        self._active = True

    def is_active(self) -> bool:
        return self._active

    def is_awaiting_manual_verification(self) -> bool:
        return self._awaiting_manual_verification is not None

    def current_request(self) -> _PendingTextFitCaseRequest | None:
        return self._current_request

    def awaiting_manual_verification_request(self) -> _TextFitVerificationPause | None:
        return self._awaiting_manual_verification

    def current_index(self) -> int:
        return self._current_index

    def current_case(self) -> FirmwareTestCase | None:
        if not self._active or self._awaiting_manual_verification is not None or self._current_request is not None:
            return None
        if self._current_index >= len(self._selected_cases):
            return None
        return self._selected_cases[self._current_index]

    def display_case(self) -> FirmwareTestCase | None:
        if self._current_request is not None:
            return self._current_request.case
        if self._awaiting_manual_verification is not None:
            return self._awaiting_manual_verification.request.case
        return self.current_case()

    def results(self) -> tuple[FirmwareTestResult, ...]:
        return tuple(self._results)

    def total_cases(self) -> int:
        return len(self._selected_cases)

    def completed_count(self) -> int:
        return len(self._results)

    def record_case_sent(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        command_text: str,
        expected_prefix: str,
        sent_frame: bytes,
        sent_started_at: float,
    ) -> _PendingTextFitCaseRequest:
        request = _PendingTextFitCaseRequest(
            case=case,
            command_definition=command_definition,
            command_text=command_text,
            expected_prefix=expected_prefix,
            sent_frame=sent_frame,
            sent_started_at=sent_started_at,
            timeout_ms=int(case.timeout_ms or command_definition.timeout_ms or DEFAULT_MANUAL_TEXT_TIMEOUT_MS),
        )
        self._current_request = request
        return request

    def handle_matching_response(
        self,
        packet: dict[str, object],
        *,
        received_at: float,
    ) -> tuple[FirmwareTestResult | None, dict[str, object] | None]:
        request = self._current_request
        if request is None:
            return None, None

        matched = _ManualTextWorkflow.match_expected_prefix(expected_prefix=request.expected_prefix, packet=packet)
        if matched is None:
            return None, None

        response_text, _response_hex = matched
        raw_payload = packet.get("raw_payload")
        rx_bytes = bytes([int(value) & 0xFF for value in list(raw_payload)]) if isinstance(raw_payload, list) else None
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        expected = str(request.case.expected_response or request.command_definition.expected_response or "") or None
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="PASS",
            expected=expected,
            actual=response_text,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=rx_bytes,
            latency_ms=latency_ms,
            message=f"Matched expected text prefix {request.expected_prefix}.",
            manual_verification_outcome=None,
        )
        self._current_request = None
        if request.case.manual_verification:
            self._awaiting_manual_verification = _TextFitVerificationPause(request=request, proposed_result=result)
            return None, {
                "case_id": request.case.case_id,
                "name": request.case.name,
                "prompt": request.case.manual_prompt or "Tester verification required.",
                "expected": result.expected,
                "actual": result.actual,
                "latency_ms": result.latency_ms,
            }

        self._results.append(result)
        self._current_index += 1
        return result, None

    def timeout_current_case(self) -> FirmwareTestResult | None:
        request = self._current_request
        if request is None:
            return None
        self._current_request = None
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="TIMEOUT",
            expected=request.case.expected_response or request.command_definition.expected_response,
            actual=None,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=None,
            latency_ms=None,
            message="Timed out waiting for matching firmware text response.",
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        return result

    def record_send_failure(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        sent_frame: bytes | None,
        message: str,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=case.case_id,
            status="ERROR",
            expected=case.expected_response or command_definition.expected_response,
            actual=None,
            tx_bytes=sent_frame,
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def submit_manual_verification(self, *, passed: bool, message: str | None = None) -> FirmwareTestResult | None:
        pause = self._awaiting_manual_verification
        if pause is None:
            return None
        self._awaiting_manual_verification = None
        status = "PASS" if pause.proposed_result.status == "PASS" and passed else "FAIL"
        final_message = message or ("Manual verification passed." if passed else "Manual verification failed.")
        result = replace(
            pause.proposed_result,
            status=status,
            message=final_message,
            manual_verification_outcome="passed" if passed else "failed",
        )
        self._results.append(result)
        self._current_index += 1
        return result

    def cancel(self) -> FirmwareTestResult | None:
        if self._current_request is not None:
            request = self._current_request
            self._current_request = None
            result = FirmwareTestResult(
                case_id=request.case.case_id,
                status="CANCELLED",
                expected=request.case.expected_response or request.command_definition.expected_response,
                actual=None,
                tx_bytes=bytes(request.sent_frame),
                rx_bytes=None,
                latency_ms=None,
                message="Cancelled before matching firmware text response.",
                manual_verification_outcome=None,
            )
            self._results.append(result)
            self._current_index += 1
            self._active = False
            return result

        if self._awaiting_manual_verification is not None:
            pause = self._awaiting_manual_verification
            self._awaiting_manual_verification = None
            result = replace(
                pause.proposed_result,
                status="CANCELLED",
                message="Cancelled while awaiting manual verification.",
                manual_verification_outcome="cancelled",
            )
            self._results.append(result)
            self._current_index += 1
            self._active = False
            return result

        self._active = False
        return None

    def mark_complete_if_done(self) -> bool:
        if self._active and self._current_index >= len(self._selected_cases) and self._current_request is None and self._awaiting_manual_verification is None:
            self._active = False
            return True
        return False


class FirmwareIntegrationController(QObject):
    """Owns Firmware Integration workflow state for manual binary, manual text, and Binary FIT."""

    status_changed = pyqtSignal(str)
    pending_state_changed = pyqtSignal(bool)
    manual_binary_sent = pyqtSignal(object)
    manual_binary_result = pyqtSignal(object)
    manual_text_sent = pyqtSignal(object)
    manual_text_result = pyqtSignal(object)
    binary_fit_case_started = pyqtSignal(object)
    binary_fit_case_result = pyqtSignal(object)
    binary_fit_manual_verification_requested = pyqtSignal(object)
    binary_fit_completed = pyqtSignal(object)
    text_fit_case_started = pyqtSignal(object)
    text_fit_case_result = pyqtSignal(object)
    text_fit_manual_verification_requested = pyqtSignal(object)
    text_fit_completed = pyqtSignal(object)

    def __init__(
        self,
        bridge: WorkspaceRuntimeBridge | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._transport_adapter = FirmwareTransportAdapter(self)
        self._last_action: str | None = None
        self._clock = clock or monotonic
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self.handle_timeout)
        self._active_operation: _ActiveFirmwareOperation | None = None
        self._manual_binary_workflow = _ManualBinaryWorkflow()
        self._manual_text_workflow = _ManualTextWorkflow()
        self._binary_fit_workflow = _BinaryFitWorkflow(
            _build_binary_fit_case_definitions(self._manual_binary_workflow.definitions())
        )
        self._text_fit_workflow = _TextFitWorkflow(_build_text_fit_case_definitions(self._manual_text_workflow.definitions()))
        self._binary_fit_snapshot = FirmwareBinaryFitSnapshot(
            running=False,
            state="idle",
            current_case=None,
            current_index=0,
            total_cases=0,
            completed_cases=0,
            awaiting_manual_verification=False,
            results=(),
            overall_status=None,
            target_node_id=None,
            manual_verification_case_id=None,
            manual_verification_prompt=None,
        )
        self._text_fit_snapshot = FirmwareTextFitSnapshot(
            running=False,
            state="idle",
            current_case=None,
            current_index=0,
            total_cases=0,
            completed_cases=0,
            awaiting_manual_verification=False,
            results=(),
            overall_status=None,
            manual_verification_case_id=None,
            manual_verification_prompt=None,
        )

    @property
    def transport_adapter(self) -> FirmwareTransportAdapter:
        return self._transport_adapter

    @property
    def last_action(self) -> str | None:
        return self._last_action

    @property
    def pending_manual_binary_request(self) -> object | None:
        operation = self._active_operation
        if operation is None or operation.mode != "binary":
            return None
        return operation.request

    @property
    def pending_manual_text_request(self) -> object | None:
        operation = self._active_operation
        if operation is None or operation.mode != "text":
            return None
        return operation.request

    def has_pending_manual_binary_request(self) -> bool:
        return self.pending_manual_binary_request is not None

    def has_pending_manual_text_request(self) -> bool:
        return self.pending_manual_text_request is not None

    def has_pending_firmware_request(self) -> bool:
        return self._active_operation is not None

    def pending_request_mode(self) -> str | None:
        return None if self._active_operation is None else self._active_operation.mode

    def manual_binary_command_definitions(self) -> tuple[FirmwareCommandDefinition, ...]:
        return self._manual_binary_workflow.definitions()

    def manual_text_command_definitions(self) -> tuple[FirmwareCommandDefinition, ...]:
        return self._manual_text_workflow.definitions()

    def get_manual_text_command_definitions(self) -> tuple[FirmwareCommandDefinition, ...]:
        return self.manual_text_command_definitions()

    def binary_fit_case_definitions(self) -> tuple[FirmwareTestCase, ...]:
        return self._binary_fit_workflow.catalog()

    def binary_fit_status_snapshot(self) -> FirmwareBinaryFitSnapshot:
        return self._binary_fit_snapshot

    def text_fit_case_definitions(self) -> tuple[FirmwareTestCase, ...]:
        return self._text_fit_workflow.catalog()

    def text_fit_status_snapshot(self) -> FirmwareTextFitSnapshot:
        return self._text_fit_snapshot

    def get_manual_binary_node_options(self) -> list[tuple[int, str]]:
        bridge = self._bridge
        if bridge is None:
            return []
        if hasattr(bridge, "get_firmware_node_options"):
            return list(bridge.get_firmware_node_options(create_if_missing=False))
        if hasattr(bridge, "get_plot_node_options"):
            return list(bridge.get_plot_node_options(create_if_missing=False))
        return []

    def open_manual_binary_mode(self) -> str:
        return self._record_status("Manual Binary Command dialog is ready.")

    def open_manual_text_mode(self) -> str:
        return self._record_status("Manual Text Command dialog is ready.")

    def start_binary_fit(
        self,
        *,
        node_id: int | None = None,
        selected_case_ids: Iterable[str] | None = None,
        cases: Iterable[FirmwareTestCase] | None = None,
    ) -> bool | str:
        if node_id is None and cases is None and selected_case_ids is None:
            return self._record_status("Binary FIT UI is not implemented yet.")
        if self.has_pending_firmware_request():
            self._record_status("A firmware command is already pending. Wait for response or cancel it first.")
            return False

        if node_id is None:
            self._record_status("Binary FIT requires a target node.")
            return False

        selected_cases = self._resolve_binary_fit_cases(selected_case_ids=selected_case_ids, cases=cases)
        try:
            self._binary_fit_workflow.start(node_id=int(node_id), selected_cases=selected_cases)
        except Exception as exc:
            self._record_status(str(exc))
            return False

        self._active_operation = _ActiveFirmwareOperation(mode="binary_fit", request=self._binary_fit_workflow)
        self.pending_state_changed.emit(True)
        self._update_binary_fit_snapshot(state="preparing", overall_status="RUNNING")
        self._record_status(
            f"Started Binary FIT with {self._binary_fit_workflow.total_cases()} case(s) on Node {int(node_id):02d}."
        )
        self._send_next_binary_fit_case()
        return True

    def cancel_binary_fit(self) -> bool:
        operation = self._active_operation
        if operation is None or operation.mode != "binary_fit":
            self._record_status("No active Binary FIT run to cancel.")
            return False

        self._timeout_timer.stop()
        self._transport_adapter.detach_runtime_window()
        cancelled_result = self._binary_fit_workflow.cancel()
        self._update_binary_fit_snapshot(state="cancelled", overall_status="CANCELLED")
        if cancelled_result is not None:
            self.binary_fit_case_result.emit(cancelled_result)
        summary = {
            "status": "CANCELLED",
            "results": self._binary_fit_workflow.results(),
            "completed_count": self._binary_fit_workflow.completed_count(),
            "total_count": self._binary_fit_workflow.total_cases(),
        }
        self.binary_fit_completed.emit(summary)
        self._clear_active_operation()
        self._record_status("Cancelled active Binary FIT run.")
        self._binary_fit_workflow.reset()
        return True

    def submit_binary_fit_manual_verification(self, passed: bool, message: str | None = None) -> bool:
        if not self._binary_fit_workflow.is_active() or not self._binary_fit_workflow.is_awaiting_manual_verification():
            self._record_status("Binary FIT is not awaiting manual verification.")
            return False

        result = self._binary_fit_workflow.submit_manual_verification(passed=bool(passed), message=message)
        if result is None:
            self._record_status("Binary FIT is not awaiting manual verification.")
            return False
        self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
        self.binary_fit_case_result.emit(result)
        self._record_status(
            f"Manual verification {'passed' if passed else 'failed'} for Binary FIT case {result.case_id}."
        )
        self._advance_binary_fit_run()
        return True

    def start_text_fit(
        self,
        *,
        selected_case_ids: Iterable[str] | None = None,
        cases: Iterable[FirmwareTestCase] | None = None,
    ) -> bool | str:
        if cases is None and selected_case_ids is None:
            return self._record_status("Text FIT UI is not implemented yet.")
        if self.has_pending_firmware_request():
            self._record_status("A firmware command is already pending. Wait for response or cancel it first.")
            return False

        selected_cases = self._resolve_text_fit_cases(selected_case_ids=selected_case_ids, cases=cases)
        try:
            self._text_fit_workflow.start(selected_cases=selected_cases)
        except Exception as exc:
            self._record_status(str(exc))
            return False

        self._active_operation = _ActiveFirmwareOperation(mode="text_fit", request=self._text_fit_workflow)
        self.pending_state_changed.emit(True)
        self._update_text_fit_snapshot(state="preparing", overall_status="RUNNING")
        self._record_status(f"Started Text FIT with {self._text_fit_workflow.total_cases()} case(s).")
        self._send_next_text_fit_case()
        return True

    def cancel_text_fit(self) -> bool:
        operation = self._active_operation
        if operation is None or operation.mode != "text_fit":
            self._record_status("No active Text FIT run to cancel.")
            return False

        self._timeout_timer.stop()
        self._transport_adapter.detach_runtime_window()
        cancelled_result = self._text_fit_workflow.cancel()
        self._update_text_fit_snapshot(state="cancelled", overall_status="CANCELLED")
        if cancelled_result is not None:
            self.text_fit_case_result.emit(cancelled_result)
        summary = {
            "status": "CANCELLED",
            "results": self._text_fit_workflow.results(),
            "completed_count": self._text_fit_workflow.completed_count(),
            "total_count": self._text_fit_workflow.total_cases(),
        }
        self.text_fit_completed.emit(summary)
        self._clear_active_operation()
        self._record_status("Cancelled active Text FIT run.")
        self._text_fit_workflow.reset()
        return True

    def submit_text_fit_manual_verification(self, passed: bool, message: str | None = None) -> bool:
        if not self._text_fit_workflow.is_active() or not self._text_fit_workflow.is_awaiting_manual_verification():
            self._record_status("Text FIT is not awaiting manual verification.")
            return False

        result = self._text_fit_workflow.submit_manual_verification(passed=bool(passed), message=message)
        if result is None:
            self._record_status("Text FIT is not awaiting manual verification.")
            return False
        self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
        self.text_fit_case_result.emit(result)
        self._record_status(
            f"Manual verification {'passed' if passed else 'failed'} for Text FIT case {result.case_id}."
        )
        self._advance_text_fit_run()
        return True

    def open_reports(self) -> str:
        return self._record_status("Reports / Export is not implemented yet.")

    def cancel_active_operation(self) -> str:
        operation = self._active_operation
        if operation is not None and operation.mode == "binary_fit":
            self.cancel_binary_fit()
            return self._last_action or "Cancelled active Binary FIT run."
        if operation is not None and operation.mode == "text_fit":
            self.cancel_text_fit()
            return self._last_action or "Cancelled active Text FIT run."

        binary_pending = self.pending_manual_binary_request
        if isinstance(binary_pending, _PendingManualBinaryRequest):
            self._timeout_timer.stop()
            self._clear_active_operation()
            return self._record_status(f"Cancelled pending manual binary command {binary_pending.command_name}.")

        text_pending = self.pending_manual_text_request
        if isinstance(text_pending, _PendingManualTextRequest):
            self._timeout_timer.stop()
            self._clear_active_operation()
            self.manual_text_result.emit(self._manual_text_workflow.build_cancel_result(text_pending))
            return self._record_status(f"Cancelled pending manual text command {text_pending.command_name}.")

        return self._record_status("No active Firmware Integration operation to cancel.")

    def send_manual_binary_command(
        self,
        *,
        node_id: int,
        command_name: str | None = None,
        parameter_value: object | None = None,
        use_raw_hex: bool = False,
        raw_hex_text: str | None = None,
    ) -> bool:
        if self.has_pending_firmware_request():
            self._record_status("A firmware command is already pending. Wait for response or cancel it first.")
            return False

        bridge = self._bridge
        if bridge is None:
            self._record_status("Firmware Integration runtime bridge is unavailable.")
            return False

        if hasattr(bridge, "get_runtime_connection_state"):
            serial_connected, _mcu_connected = bridge.get_runtime_connection_state(create_if_missing=False)
            if not serial_connected:
                self._record_status("Serial port not connected.")
                return False

        try:
            prepared = self._manual_binary_workflow.prepare_send(
                command_name=command_name,
                parameter_value=parameter_value,
                use_raw_hex=use_raw_hex,
                raw_hex_text=raw_hex_text,
            )
            runtime_window = bridge.get_runtime_window(create_if_missing=True)
            self._transport_adapter.attach_runtime_window(runtime_window)
            sent_started_at = float(self._clock())
            sent_frame = bytes(bridge.send_firmware_binary_command(int(node_id), prepared.payload))
        except Exception as exc:
            self._transport_adapter.detach_runtime_window()
            self._record_status(str(exc))
            return False

        self._active_operation = _ActiveFirmwareOperation(
            mode="binary",
            request=_PendingManualBinaryRequest(
                command_name=prepared.command_name,
                node_id=int(node_id),
                expected_opcode=prepared.expected_opcode,
                sent_payload=list(prepared.payload),
                sent_frame=sent_frame,
                sent_started_at=sent_started_at,
                timeout_ms=prepared.timeout_ms,
                used_raw_hex=prepared.used_raw_hex,
            ),
        )
        self._timeout_timer.start(prepared.timeout_ms)
        self.pending_state_changed.emit(True)

        tx_event = {
            "status": "TX",
            "command_name": prepared.command_name,
            "node_id": int(node_id),
            "payload_hex": self._format_hex(prepared.payload),
            "frame_hex": self._format_hex(sent_frame),
            "used_raw_hex": prepared.used_raw_hex,
        }
        self.manual_binary_sent.emit(tx_event)
        self._record_status(
            f"Sent {prepared.command_name} to Node {int(node_id):02d}. Waiting for 0x{prepared.expected_opcode:02X} response."
        )
        return True

    def send_manual_text_command(self, command_name: str, value: object | None = None) -> bool:
        if self.has_pending_firmware_request():
            self._record_status("A firmware command is already pending. Wait for response or cancel it first.")
            return False

        bridge = self._bridge
        if bridge is None:
            self._record_status("Firmware Integration runtime bridge is unavailable.")
            return False

        if hasattr(bridge, "get_runtime_connection_state"):
            serial_connected, _mcu_connected = bridge.get_runtime_connection_state(create_if_missing=False)
            if not serial_connected:
                self._record_status("Serial port not connected.")
                return False

        try:
            prepared = self._manual_text_workflow.prepare_send(command_name=command_name, value=value)
            runtime_window = bridge.get_runtime_window(create_if_missing=True)
            self._transport_adapter.attach_runtime_window(runtime_window)
            sent_started_at = float(self._clock())
            sent_frame = bytes(bridge.send_firmware_text_command(bytearray(prepared.frame)))
        except Exception as exc:
            self._transport_adapter.detach_runtime_window()
            self._record_status(str(exc))
            return False

        self._active_operation = _ActiveFirmwareOperation(
            mode="text",
            request=_PendingManualTextRequest(
                command_name=prepared.command_name,
                command_text=prepared.command_text,
                expected_prefix=prepared.expected_prefix,
                sent_frame=sent_frame,
                sent_started_at=sent_started_at,
                timeout_ms=prepared.timeout_ms,
            ),
        )
        self._timeout_timer.start(prepared.timeout_ms)
        self.pending_state_changed.emit(True)

        tx_event = {
            "status": "TX",
            "command_name": prepared.command_name,
            "command_text": prepared.command_text,
            "expected_prefix": prepared.expected_prefix,
            "frame_hex": self._format_hex(sent_frame),
        }
        self.manual_text_sent.emit(tx_event)
        self._record_status(f"Sent text command {prepared.command_text}. Waiting for prefix {prepared.expected_prefix}.")
        return True

    def accepts_manual_binary_packet(self, *, sender: int | None, cmd: int | None, params: list[int] | None = None) -> bool:
        _ = params
        pending = self.pending_manual_binary_request
        if not isinstance(pending, _PendingManualBinaryRequest):
            return False
        return self._manual_binary_workflow.accepts_response(pending, sender=sender, cmd=cmd)

    def accepts_binary_fit_packet(self, *, sender: int | None, cmd: int | None, params: list[int] | None = None) -> bool:
        _ = params
        return self._binary_fit_workflow.accepts_response(sender=sender, cmd=cmd)

    def handle_runtime_packet(self, packet: object) -> None:
        if not isinstance(packet, dict):
            return

        if self.pending_request_mode() == "binary_fit" and self._binary_fit_workflow.is_active():
            sender = packet.get("sender")
            command = packet.get("cmd")
            params = packet.get("params", [])
            if not self.accepts_binary_fit_packet(
                sender=sender if isinstance(sender, int) else None,
                cmd=command if isinstance(command, int) else None,
                params=list(params) if isinstance(params, list) else None,
            ):
                return

            self._timeout_timer.stop()
            self._transport_adapter.detach_runtime_window()
            result, verification_request = self._binary_fit_workflow.handle_matching_response(
                packet,
                received_at=float(self._clock()),
            )
            if result is not None:
                self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
                self.binary_fit_case_result.emit(result)
                self._record_status(f"Completed Binary FIT case {result.case_id} with status {result.status}.")
                self._advance_binary_fit_run()
                return

            if verification_request is not None:
                self._update_binary_fit_snapshot(
                    state="awaiting_manual_verification",
                    overall_status="RUNNING",
                    manual_verification_case_id=str(verification_request["case_id"]),
                    manual_verification_prompt=str(verification_request["prompt"]),
                )
                self.binary_fit_manual_verification_requested.emit(verification_request)
                self._record_status(
                    f"Binary FIT case {verification_request['case_id']} is awaiting manual verification."
                )
            return

        pending = self.pending_manual_binary_request
        if not isinstance(pending, _PendingManualBinaryRequest):
            return

        sender = packet.get("sender")
        command = packet.get("cmd")
        params = packet.get("params", [])
        if not self.accepts_manual_binary_packet(
            sender=sender if isinstance(sender, int) else None,
            cmd=command if isinstance(command, int) else None,
            params=list(params) if isinstance(params, list) else None,
        ):
            return

        self._timeout_timer.stop()
        self._clear_active_operation()
        result = self._manual_binary_workflow.build_pass_result(pending, packet, received_at=float(self._clock()))
        self.manual_binary_result.emit(result)
        self._record_status(
            f"Received {pending.command_name} response from Node {pending.node_id:02d} in {float(result['latency_ms']):.1f} ms."
        )

    def handle_manual_text_packet(self, packet: object) -> None:
        if self.pending_request_mode() == "text_fit" and self._text_fit_workflow.is_active():
            self.handle_text_fit_packet(packet)
            return

        pending = self.pending_manual_text_request
        if not isinstance(pending, _PendingManualTextRequest):
            return
        if not isinstance(packet, dict):
            return

        matched = self._manual_text_workflow.match_response(pending, packet)
        if matched is None:
            return

        response_text, response_hex = matched
        self._timeout_timer.stop()
        self._clear_active_operation()
        result = self._manual_text_workflow.build_pass_result(
            pending,
            response_text=response_text,
            response_hex=response_hex,
            received_at=float(self._clock()),
        )
        self.manual_text_result.emit(result)
        self._record_status(f"Received text response for {pending.command_name} in {float(result['latency_ms']):.1f} ms.")

    def handle_text_fit_packet(self, packet: object) -> None:
        if not isinstance(packet, dict):
            return

        result, verification_request = self._text_fit_workflow.handle_matching_response(packet, received_at=float(self._clock()))
        if result is None and verification_request is None:
            return

        self._timeout_timer.stop()
        self._transport_adapter.detach_runtime_window()
        if result is not None:
            self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
            self.text_fit_case_result.emit(result)
            self._record_status(f"Completed Text FIT case {result.case_id} with status {result.status}.")
            self._advance_text_fit_run()
            return

        self._update_text_fit_snapshot(
            state="awaiting_manual_verification",
            overall_status="RUNNING",
            manual_verification_case_id=str(verification_request["case_id"]),
            manual_verification_prompt=str(verification_request["prompt"]),
        )
        self.text_fit_manual_verification_requested.emit(verification_request)
        self._record_status(f"Text FIT case {verification_request['case_id']} is awaiting manual verification.")

    def handle_timeout(self) -> None:
        operation = self._active_operation
        if operation is None:
            return

        if operation.mode == "binary_fit":
            self._transport_adapter.detach_runtime_window()
            result = self._binary_fit_workflow.timeout_current_case()
            if result is not None:
                self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
                self.binary_fit_case_result.emit(result)
                self._record_status(f"Timed out waiting for Binary FIT case {result.case_id}.")
                self._advance_binary_fit_run()
            return

        if operation.mode == "text_fit":
            self._transport_adapter.detach_runtime_window()
            result = self._text_fit_workflow.timeout_current_case()
            if result is not None:
                self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
                self.text_fit_case_result.emit(result)
                self._record_status(f"Timed out waiting for Text FIT case {result.case_id}.")
                self._advance_text_fit_run()
            return

        if operation.mode == "text":
            text_pending = operation.request
            if not isinstance(text_pending, _PendingManualTextRequest):
                return
            self._clear_active_operation()
            self.manual_text_result.emit(self._manual_text_workflow.build_timeout_result(text_pending))
            self._record_status(f"Timed out waiting for prefix {text_pending.expected_prefix} for {text_pending.command_name}.")
            return

        if operation.mode != "binary":
            return
        binary_pending = operation.request
        if not isinstance(binary_pending, _PendingManualBinaryRequest):
            return
        self._clear_active_operation()
        self.manual_binary_result.emit(self._manual_binary_workflow.build_timeout_result(binary_pending))
        self._record_status(
            f"Timed out waiting for 0x{binary_pending.expected_opcode:02X} from Node {binary_pending.node_id:02d} "
            f"for {binary_pending.command_name}."
        )

    def _build_binary_payload(self, definition: FirmwareCommandDefinition, parameter_value: object | None) -> list[int]:
        return self._manual_binary_workflow.build_payload(definition, parameter_value)

    @staticmethod
    def _format_hex(values: bytes | bytearray | list[int]) -> str:
        return " ".join(f"{int(value) & 0xFF:02X}" for value in list(values))

    def _resolve_binary_fit_cases(
        self,
        *,
        selected_case_ids: Iterable[str] | None,
        cases: Iterable[FirmwareTestCase] | None,
    ) -> tuple[FirmwareTestCase, ...]:
        if cases is not None:
            return tuple(cases)

        catalog = self._binary_fit_workflow.catalog()
        if selected_case_ids is None:
            return tuple(case for case in catalog if case.selected_by_default)

        wanted = {str(case_id) for case_id in selected_case_ids}
        return tuple(case for case in catalog if case.case_id in wanted)

    def _resolve_text_fit_cases(
        self,
        *,
        selected_case_ids: Iterable[str] | None,
        cases: Iterable[FirmwareTestCase] | None,
    ) -> tuple[FirmwareTestCase, ...]:
        if cases is not None:
            return tuple(cases)

        catalog = self._text_fit_workflow.catalog()
        if selected_case_ids is None:
            return tuple(case for case in catalog if case.selected_by_default)

        wanted = {str(case_id) for case_id in selected_case_ids}
        return tuple(case for case in catalog if case.case_id in wanted)

    def _send_next_binary_fit_case(self) -> None:
        while self._binary_fit_workflow.is_active() and not self._binary_fit_workflow.is_awaiting_manual_verification():
            case = self._binary_fit_workflow.current_case()
            if case is None:
                self._complete_binary_fit_run(status="COMPLETED")
                return

            payload: list[int] | None = None
            try:
                definition = self._manual_binary_workflow.definition(case.command_key)
                payload = self._manual_binary_workflow.build_payload(definition, case.parameter_value)
                bridge = self._bridge
                if bridge is None:
                    raise ValueError("Firmware Integration runtime bridge is unavailable.")
                if hasattr(bridge, "get_runtime_connection_state"):
                    serial_connected, _mcu_connected = bridge.get_runtime_connection_state(create_if_missing=False)
                    if not serial_connected:
                        raise ValueError("Serial port not connected.")
                runtime_window = bridge.get_runtime_window(create_if_missing=True)
                self._transport_adapter.attach_runtime_window(runtime_window)
                sent_started_at = float(self._clock())
                sent_frame = bytes(bridge.send_firmware_binary_command(self._binary_fit_workflow.node_id() or 0, payload))
                request = self._binary_fit_workflow.record_case_sent(
                    case=case,
                    command_definition=definition,
                    payload=payload,
                    sent_frame=sent_frame,
                    sent_started_at=sent_started_at,
                )
                self._timeout_timer.start(request.timeout_ms)
                self._update_binary_fit_snapshot(state="waiting_response", overall_status="RUNNING")
                self.binary_fit_case_started.emit(
                    {
                        "case_id": case.case_id,
                        "name": case.name,
                        "command_key": case.command_key,
                        "node_id": request.node_id,
                        "expected_opcode": request.expected_opcode,
                        "timeout_ms": request.timeout_ms,
                        "tx_hex": self._format_hex(sent_frame),
                    }
                )
                self._record_status(f"Started Binary FIT case {case.case_id} on Node {request.node_id:02d}.")
                return
            except Exception as exc:
                self._transport_adapter.detach_runtime_window()
                failure_result = self._binary_fit_workflow.record_send_failure(
                    case=case,
                    command_definition=self._manual_binary_workflow.definition(case.command_key),
                    payload=payload,
                    message=str(exc),
                )
                self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
                self.binary_fit_case_result.emit(failure_result)
                self._record_status(f"Binary FIT send failed for {case.case_id}: {exc}")

        if self._binary_fit_workflow.mark_complete_if_done():
            self._complete_binary_fit_run(status="COMPLETED")

    def _send_next_text_fit_case(self) -> None:
        while self._text_fit_workflow.is_active() and not self._text_fit_workflow.is_awaiting_manual_verification():
            case = self._text_fit_workflow.current_case()
            if case is None:
                self._complete_text_fit_run(status="COMPLETED")
                return

            sent_frame: bytes | None = None
            try:
                definition = self._manual_text_workflow.definition(case.command_key)
                prepared = self._manual_text_workflow.prepare_send(command_name=definition.name, value=case.parameter_value)
                bridge = self._bridge
                if bridge is None:
                    raise ValueError("Firmware Integration runtime bridge is unavailable.")
                if hasattr(bridge, "get_runtime_connection_state"):
                    serial_connected, _mcu_connected = bridge.get_runtime_connection_state(create_if_missing=False)
                    if not serial_connected:
                        raise ValueError("Serial port not connected.")
                runtime_window = bridge.get_runtime_window(create_if_missing=True)
                self._transport_adapter.attach_runtime_window(runtime_window)
                sent_started_at = float(self._clock())
                sent_frame = bytes(bridge.send_firmware_text_command(bytearray(prepared.frame)))
                request = self._text_fit_workflow.record_case_sent(
                    case=case,
                    command_definition=definition,
                    command_text=prepared.command_text,
                    expected_prefix=prepared.expected_prefix,
                    sent_frame=sent_frame,
                    sent_started_at=sent_started_at,
                )
                self._timeout_timer.start(request.timeout_ms)
                self._update_text_fit_snapshot(state="waiting_response", overall_status="RUNNING")
                self.text_fit_case_started.emit(
                    {
                        "case_id": case.case_id,
                        "name": case.name,
                        "command_key": case.command_key,
                        "expected_prefix": request.expected_prefix,
                        "timeout_ms": request.timeout_ms,
                        "tx_hex": self._format_hex(sent_frame),
                    }
                )
                self._record_status(f"Started Text FIT case {case.case_id}.")
                return
            except Exception as exc:
                self._transport_adapter.detach_runtime_window()
                failure_result = self._text_fit_workflow.record_send_failure(
                    case=case,
                    command_definition=self._manual_text_workflow.definition(case.command_key),
                    sent_frame=sent_frame,
                    message=str(exc),
                )
                self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
                self.text_fit_case_result.emit(failure_result)
                self._record_status(f"Text FIT send failed for {case.case_id}: {exc}")

        if self._text_fit_workflow.mark_complete_if_done():
            self._complete_text_fit_run(status="COMPLETED")

    def _advance_binary_fit_run(self) -> None:
        if self._binary_fit_workflow.mark_complete_if_done():
            self._complete_binary_fit_run(status="COMPLETED")
            return
        if not self._binary_fit_workflow.is_active():
            self._complete_binary_fit_run(status="CANCELLED")
            return
        self._send_next_binary_fit_case()

    def _advance_text_fit_run(self) -> None:
        if self._text_fit_workflow.mark_complete_if_done():
            self._complete_text_fit_run(status="COMPLETED")
            return
        if not self._text_fit_workflow.is_active():
            self._complete_text_fit_run(status="CANCELLED")
            return
        self._send_next_text_fit_case()

    def _complete_binary_fit_run(self, *, status: str) -> None:
        summary = {
            "status": status,
            "results": self._binary_fit_workflow.results(),
            "completed_count": self._binary_fit_workflow.completed_count(),
            "total_count": self._binary_fit_workflow.total_cases(),
        }
        self._update_binary_fit_snapshot(state=status.lower(), overall_status=status)
        self.binary_fit_completed.emit(summary)
        self._clear_active_operation()
        if status == "COMPLETED":
            self._record_status(
                f"Binary FIT completed with {summary['completed_count']} result(s) across {summary['total_count']} case(s)."
            )
        self._binary_fit_workflow.reset()

    def _complete_text_fit_run(self, *, status: str) -> None:
        summary = {
            "status": status,
            "results": self._text_fit_workflow.results(),
            "completed_count": self._text_fit_workflow.completed_count(),
            "total_count": self._text_fit_workflow.total_cases(),
        }
        self._update_text_fit_snapshot(state=status.lower(), overall_status=status)
        self.text_fit_completed.emit(summary)
        self._clear_active_operation()
        if status == "COMPLETED":
            self._record_status(
                f"Text FIT completed with {summary['completed_count']} result(s) across {summary['total_count']} case(s)."
            )
        self._text_fit_workflow.reset()

    def _update_binary_fit_snapshot(
        self,
        *,
        state: str,
        overall_status: str | None,
        manual_verification_case_id: str | None = None,
        manual_verification_prompt: str | None = None,
    ) -> None:
        self._binary_fit_snapshot = FirmwareBinaryFitSnapshot(
            running=self._binary_fit_workflow.is_active(),
            state=state,
            current_case=self._binary_fit_workflow.display_case(),
            current_index=self._binary_fit_workflow.current_index(),
            total_cases=self._binary_fit_workflow.total_cases(),
            completed_cases=self._binary_fit_workflow.completed_count(),
            awaiting_manual_verification=self._binary_fit_workflow.is_awaiting_manual_verification(),
            results=self._binary_fit_workflow.results(),
            overall_status=overall_status,
            target_node_id=self._binary_fit_workflow.node_id(),
            manual_verification_case_id=manual_verification_case_id,
            manual_verification_prompt=manual_verification_prompt,
        )

    def _update_text_fit_snapshot(
        self,
        *,
        state: str,
        overall_status: str | None,
        manual_verification_case_id: str | None = None,
        manual_verification_prompt: str | None = None,
    ) -> None:
        self._text_fit_snapshot = FirmwareTextFitSnapshot(
            running=self._text_fit_workflow.is_active(),
            state=state,
            current_case=self._text_fit_workflow.display_case(),
            current_index=self._text_fit_workflow.current_index(),
            total_cases=self._text_fit_workflow.total_cases(),
            completed_cases=self._text_fit_workflow.completed_count(),
            awaiting_manual_verification=self._text_fit_workflow.is_awaiting_manual_verification(),
            results=self._text_fit_workflow.results(),
            overall_status=overall_status,
            manual_verification_case_id=manual_verification_case_id,
            manual_verification_prompt=manual_verification_prompt,
        )

    def _record_status(self, message: str) -> str:
        self._last_action = str(message)
        self.status_changed.emit(self._last_action)
        return self._last_action

    def _clear_active_operation(self) -> None:
        self._active_operation = None
        self._transport_adapter.detach_runtime_window()
        self.pending_state_changed.emit(False)
