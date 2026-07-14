"""Single public workflow owner for Firmware Integration behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import monotonic
from typing import TYPE_CHECKING, Callable, Iterable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from data.binary_cmd_builders import (
    build_legacy_no_arg_payload,
    build_legacy_query_3f_payload,
    build_legacy_raw_payload,
    build_legacy_set_3d_payload,
    build_getpos,
    build_getvel_query_payload,
    build_getver_query_payload,
    build_interrupt_query_payload,
    build_motor_current_query_payload,
    build_motor_current_log_rate_payload,
    build_nodeconfig_query_payload,
    build_position_log_rate_payload,
    build_run,
    build_stopmotor,
    build_tpos,
    build_vel,
)
from data.binary_cmd_parser import decode_command
from data.text_cmd_builders import build_text_command_payload, decode_text_command_response, normalize_text_command
from services.firmware_report_builder import derive_fit_overall_status
from services.firmware_transport_adapter import FirmwareTransportAdapter

from ..models import (
    FirmwareBinaryFitSnapshot,
    FirmwareCommandDefinition,
    FirmwareFitReport,
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
    execution_policy: str = "QUERY_RESPONSE"
    cleanup_value: object | None = None
    cleanup_pending: bool = False
    primary_actual: str | None = None
    primary_rx_bytes: bytes | None = None
    primary_latency_ms: float | None = None


@dataclass(frozen=True)
class _PendingTextFitCaseRequest:
    case: FirmwareTestCase
    command_definition: FirmwareCommandDefinition
    command_text: str
    expected_prefix: str
    sent_frame: bytes
    sent_started_at: float
    timeout_ms: int
    execution_policy: str = "QUERY_RESPONSE"
    cleanup_value: object | None = None
    cleanup_pending: bool = False
    primary_response_text: str | None = None
    primary_rx_bytes: bytes | None = None
    primary_latency_ms: float | None = None


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


_BINARY_COMMAND_ROWS: tuple[dict[str, object], ...] = (
    {"cmd": 0x81, "name": "bcmd_TPOS (Move Motor Position)", "params_type": "int32", "default": "0", "manual": True, "prompt": "Did you observe motor axis rotating to target position?", "expected_format": "Multiple response states: 'S' = Start moving [0x81]['S'][pos_byte3]..., 'E' = End reached [0x81]['E']..."},
    {"cmd": 0x82, "name": "bcmd_GETPOS (Get Position)", "params_type": "int32", "default": "0", "expected_format": "[0x82][pos_byte3][pos_byte2][pos_byte1][pos_byte0]"},
    {"cmd": 0x83, "name": "bcmd_GETRPS (Get Speed)", "params_type": "none", "default": "", "expected_format": "[0x83][rps_b3][rps_b2][rps_b1][rps_b0]"},
    {"cmd": 0x84, "name": "bcmd_VEL (Set Velocity)", "params_type": "int16", "default": "30", "expected_format": "[0x84]['S'][code_hi][code_lo]"},
    {"cmd": 0x85, "name": "bcmd_GETVEL (Get Velocity)", "params_type": "none", "default": "", "expected_format": "[0x85][vel_hi][vel_lo]"},
    {"cmd": 0x86, "name": "bcmd_NODEIDref (Get ID Reference)", "params_type": "query_3f", "default": "", "expected_format": "[0x86][0x3A][node_id]"},
    {"cmd": 0x86, "name": "bcmd_NODEIDref (Set ID Reference)", "params_type": "set_3d", "default": "01", "expected_format": "[0x86][0x3A][node_id]"},
    {"cmd": 0x88, "name": "bcmd_RUN (Run Motor)", "params_type": "int16", "default": "30", "manual": True, "prompt": "Did you observe the motor running?", "expected_format": "[0x88]['S'][velocity_hi][velocity_lo]"},
    {"cmd": 0x89, "name": "bcmd_RD_SLOPE (Ramp Down Slope)", "params_type": "set_3d", "default": "00 1E", "expected_format": "[0x89][0x3A][value_hi][value_lo]"},
    {"cmd": 0x8B, "name": "bcmd_RD_STEP (Ramp Down Step)", "params_type": "set_3d", "default": "01", "expected_format": "[0x8B][0x3A][value]"},
    {"cmd": 0x8C, "name": "bcmd_RD_MINVEL (Ramp Down Min Velocity)", "params_type": "set_3d", "default": "0A", "expected_format": "[0x8C][0x3A][value]"},
    {"cmd": 0x8D, "name": "bcmd_BITRATE (CAN Bit Rate)", "params_type": "query_3f", "default": "", "expected_format": "[0x8D][0x3A][bitrate_code]"},
    {"cmd": 0x8E, "name": "bcmd_FWDSIZE (Forward Size Parameter)", "params_type": "set_3d", "default": "05", "expected_format": "[0x8E][0x3A][value]"},
    {"cmd": 0x8F, "name": "bcmd_OUTDIAGLED (Diagnostic LED Output)", "params_type": "set_3d", "default": "02", "expected_format": "[0x8F][0x3A][value]"},
    {"cmd": 0x90, "name": "bcmd_SJW (CAN SJW Parameter)", "params_type": "set_3d", "default": "01", "expected_format": "[0x90][0x3A][value]"},
    {"cmd": 0x91, "name": "bcmd_PRSEG (CAN PRSEG Parameter)", "params_type": "set_3d", "default": "02", "expected_format": "[0x91][0x3A][value]"},
    {"cmd": 0x92, "name": "bcmd_SEG1PH (CAN SEG1PH Parameter)", "params_type": "set_3d", "default": "03", "expected_format": "[0x92][0x3A][value]"},
    {"cmd": 0x93, "name": "bcmd_SEG2PH (CAN SEG2PH Parameter)", "params_type": "set_3d", "default": "03", "expected_format": "[0x93][0x3A][value]"},
    {"cmd": 0x94, "name": "bcmd_BAUDRATE (CAN Baud Rate)", "params_type": "set_3d", "default": "04", "expected_format": "[0x94][0x3A][value]"},
    {"cmd": 0x96, "name": "bcmd_EXTINT (Get EXT Interrupt)", "params_type": "query_3f", "default": "", "expected_format": "[0x96][0x3A][0x00][value_hi][value_lo]"},
    {"cmd": 0x96, "name": "bcmd_EXTINT (Set EXT Interrupt)", "params_type": "set_3d", "default": "01", "expected_format": "[0x96][0x3A][0x00][value_hi][value_lo]"},
    {"cmd": 0x97, "name": "bcmd_FACTORYDEF (Restore Factory Defaults)", "params_type": "none", "default": "", "expected_format": "[0x97]['A']"},
    {"cmd": 0x98, "name": "bcmd_MSTPEVNT (Motor stop event delay)", "params_type": "set_3d", "default": "0F", "expected_format": "[0x98][0x3A][value_hi][value_lo]"},
    {"cmd": 0x99, "name": "bcmd_ZPOSEVNT (Zero Position Event)", "params_type": "set_3d", "default": "0A", "expected_format": "[0x99][0x3A][value_hi][value_lo]"},
    {"cmd": 0x9A, "name": "bcmd_FIFOSTAT (FIFO Statistics)", "params_type": "query_3f", "default": "", "expected_format": "[0x9A][0x3A][stat_bytes]"},
    {"cmd": 0x9B, "name": "bcmd_AMXPSTAT (AMX Packet Statistic)", "params_type": "query_3f", "default": "", "expected_format": "[0x9B][0x3A][stat_bytes]"},
    {"cmd": 0x9C, "name": "bcmd_HOSTNODENO (Host Node Number)", "params_type": "query_3f", "default": "", "expected_format": "[0x9C][0x3A][value]"},
    {"cmd": 0x9D, "name": "bcmd_FLASHLED (Flash Heart Beat LED)", "params_type": "none", "default": "", "manual": True, "prompt": "Did the node LED flash?", "expected_format": "[0x9D]['A']"},
    {"cmd": 0x9E, "name": "bcmd_LOGFLAGS (Log INT0/INT1 Flags)", "params_type": "set_3d", "default": "01", "expected_format": "[0x9E][0x3A][value_hi][value_lo]"},
    {"cmd": 0x9F, "name": "bcmd_LOG_NGSW (Log Needle Guide Switch)", "params_type": "set_3d", "default": "01", "expected_format": "[0x9F][0x3A][value_hi][value_lo]"},
    {"cmd": 0xA0, "name": "bcmd_QEIENCODER (QEI Encoder ISR Counts)", "params_type": "none", "default": "", "expected_format": "[0xA0][count_byte3][count_byte2][count_byte1][count_byte0]"},
    {"cmd": 0xA1, "name": "bcmd_FFmsg (Free Form Message)", "params_type": "hex", "default": "AA BB CC", "expected_format": "[0xA1][length][message_bytes]"},
    {"cmd": 0xA2, "name": "bcmd_CHARVALUE (Minimum forward/rev PWM)", "params_type": "set_3d", "default": "01 0F", "expected_format": "[0xA2][0x3A][datatype][value]"},
    {"cmd": 0xA4, "name": "bcmd_RETRY (Retries count)", "params_type": "set_3d", "default": "03", "expected_format": "[0xA4][0x3A][value]"},
    {"cmd": 0xA5, "name": "bcmd_SWABPARAM (Configure swab parameters)", "params_type": "set_3d", "default": "01 02", "expected_format": "[0xA5][0x3A][maxRotarySwabOperationTime]"},
    {"cmd": 0xA6, "name": "bcmd_ACCPPARAM (Acceptable error/parameter)", "params_type": "set_3d", "default": "05", "expected_format": "No active response handler found in source"},
    {"cmd": 0xA7, "name": "bcmd_RESTARTDLY (Restart delay config)", "params_type": "set_3d", "default": "0A 00", "expected_format": "[0xA7][0x3A][value_hi][value_lo]"},
    {"cmd": 0xA8, "name": "bcmd_ENABLEOPT (Enable operational options)", "params_type": "set_3d", "default": "01", "expected_format": "[0xA8][0x3A][value_hi][value_lo]"},
    {"cmd": 0xA9, "name": "bcmd_MINMOVINGPWM (Min PWM during motion)", "params_type": "set_3d", "default": "1E", "expected_format": "[0xA9][0x3A]['v'][value_b3][value_b2][value_b1][value_b0]"},
    {"cmd": 0xAA, "name": "bcmd_UCHARVALUE (Optional datatype)", "params_type": "set_3d", "default": "02 55", "expected_format": "[0xAA][0x3A][datatype][value]"},
    {"cmd": 0xC3, "name": "bcmd_HUNTING (Enable hunting/dithering)", "params_type": "set_3d", "default": "01", "expected_format": "[0xC3]['A'/'N'][nodeconfig]"},
    {"cmd": 0xC4, "name": "bcmd_NODECONFIG (Configure node operating mode)", "params_type": "set_3d", "default": "01", "expected_format": "[0xC4][0x3A][operation_mode]"},
    {"cmd": 0xC5, "name": "bcmd_SAVEEEPROM (Save settings)", "params_type": "none", "default": "", "expected_format": "[0xC5]['A']"},
    {"cmd": 0xC6, "name": "bcmd_TOGGLELED (Toggle LED1/LED2)", "params_type": "hex", "default": "01", "manual": True, "prompt": "Did you see LED 1 toggle?", "expected_format": "LED toggles"},
    {"cmd": 0xC7, "name": "bcmd_RESET (Reset microcontroller)", "params_type": "hex", "default": "21", "expected_format": "[0xC7][0x3A][node_id]"},
    {"cmd": 0xC8, "name": "bcmd_GETVER (Query firmware version)", "params_type": "query_3f", "default": "", "expected_format": "[0xC8][0x3A][V1][V2][V3] V1 = (verMaj<<4)..."},
    {"cmd": 0xC9, "name": "bcmd_LFLAG (Left sensor flag behavior)", "params_type": "set_3d", "default": "01", "expected_format": "[0xC9][0x3A][value]"},
    {"cmd": 0xCA, "name": "bcmd_RFLAG (Right sensor flag behavior)", "params_type": "set_3d", "default": "01", "expected_format": "[0xCA][0x3A][value]"},
    {"cmd": 0xCB, "name": "bcmd_ECHOTEST (Test comm link)", "params_type": "hex", "default": "AA 55", "expected_format": "Echo: [0xCB][test_data]"},
    {"cmd": 0xCC, "name": "bcmd_BTNP (Push button input)", "params_type": "hex", "default": "01", "expected_format": "[0xCC]['0'/'1']"},
    {"cmd": 0xCD, "name": "bcmd_NODETYPE (Get node type)", "params_type": "query_3f", "default": "", "expected_format": "[0xCD][0x3A][node_type]"},
    {"cmd": 0xCD, "name": "bcmd_NODETYPE (Set node type)", "params_type": "set_3d", "default": "09", "expected_format": "[0xCD][0x3A][node_type]"},
    {"cmd": 0xCE, "name": "bcmd_STT_FAULT (Motor driver fault status)", "params_type": "none", "default": "", "expected_format": "[0xCE][status][fault_flags]"},
    {"cmd": 0xCF, "name": "bcmd_MOTOR_I (Motor current reading)", "params_type": "hex", "default": "00 00", "expected_format": "[0xCF][adc_hi][adc_lo]"},
    {"cmd": 0xD0, "name": "bcmd_FSR1 (FSR1 force sensor reading)", "params_type": "hex", "default": "00 00 01", "expected_format": "[0xD0][adc_hi][adc_lo][state]"},
    {"cmd": 0xD1, "name": "bcmd_FSR2 (FSR2 force sensor reading)", "params_type": "hex", "default": "00 00 01", "expected_format": "[0xD1][adc_hi][adc_lo][state]"},
    {"cmd": 0xD2, "name": "bcmd_INFOR1 (Send node info)", "params_type": "hex", "default": "01 10 00", "expected_format": "[0xD2][0x3A][N][port_1]...[port_N]"},
    {"cmd": 0xD3, "name": "bcmd_LOGMOTOR_I (Motor current logging rate)", "params_type": "set_3d", "default": "03 E8", "expected_format": "[0xD3][0x3A][value_hi][value_lo]"},
    {"cmd": 0xD4, "name": "bcmd_LOGFSR1 (FSR1 logging rate)", "params_type": "set_3d", "default": "03 E8", "expected_format": "[0xD4][0x3A][value_hi][value_lo]"},
    {"cmd": 0xD5, "name": "bcmd_LOGFSR2 (FSR2 logging rate)", "params_type": "set_3d", "default": "03 E8", "expected_format": "[0xD5][0x3A][value_hi][value_lo]"},
    {"cmd": 0xD6, "name": "bcmd_HMILED (Set RGB for HMI LED)", "params_type": "set_3d", "default": "01", "expected_format": "[0xD6][0x3A][red][green][blue]"},
    {"cmd": 0xD7, "name": "bcmd_HMILEDRATE (Set RGB LED update rate)", "params_type": "set_3d", "default": "00 64", "expected_format": "[0xD7][0x3A][red_hi][red_lo][green_hi][green_lo][blue_hi][blue_lo]"},
    {"cmd": 0xD8, "name": "bcmd_INTERRUPT (Get INT0/INT1 switch status)", "params_type": "none", "default": "", "expected_format": "[0xD8][int0_status][int1_status]"},
    {"cmd": 0xDB, "name": "bcmd_STARTMOVE (Initiate motor movement)", "params_type": "none", "default": "", "expected_format": "[0xDB][isSpeedControl]"},
    {"cmd": 0xDC, "name": "bcmd_BRAKEMOTOR (Apply motor braking)", "params_type": "none", "default": "", "expected_format": "Motor brakes"},
    {"cmd": 0xDD, "name": "bcmd_STOPMOTOR (Stop motor immediately)", "params_type": "none", "default": "", "expected_format": "Motor stops"},
    {"cmd": 0xDE, "name": "bcmd_NGSWSTATE (Get needle guide force sensor)", "params_type": "none", "default": "", "expected_format": "[0xDE][fsr_value_hi][fsr_value_lo]"},
    {"cmd": 0xDF, "name": "bcmd_NGSW_SET (Set upper/lower FSR limits)", "params_type": "hex", "default": "01 00 64 03 E8", "expected_format": "[0xDF][sw_id][0x3A][lower_hi][lower_lo][upper_hi][upper_lo]"},
    {"cmd": 0xE1, "name": "bcmd_RD_OFFSET (Target offset for ramp down)", "params_type": "set_3d", "default": "00 64", "expected_format": "[0xE1][0x3A][value_hi][value_lo]"},
    {"cmd": 0xE2, "name": "bcmd_RD_REGION (Ramp down region %)", "params_type": "set_3d", "default": "0A", "expected_format": "[0xE2][0x3A][value]"},
    {"cmd": 0xE3, "name": "bcmd_POSCHANGE (Log position change count)", "params_type": "set_3d", "default": "0A", "expected_format": "[0xE3][0x3A][value_hi][value_lo]"},
    {"cmd": 0xE4, "name": "bcmd_LOGPOS (Set position logging rate)", "params_type": "set_3d", "default": "00 64", "expected_format": "[0xE4][0x3A][value_hi][value_lo]"},
    {"cmd": 0xE6, "name": "bcmd_LOGDATA (Configure general logging rate)", "params_type": "set_3d", "default": "03 E8", "expected_format": "[0xE6][0x3A][datatype][value_hi][value_lo]"},
    {"cmd": 0xE7, "name": "bcmd_PID_Gain (Set PID P/I/D gains)", "params_type": "set_3d", "default": "01 00 A0", "expected_format": "[0xE7][0x3A][gain_type][value_b3][value_b2][value_b1][value_b0]"},
    {"cmd": 0xEA, "name": "bcmd_POSITION (Get current position)", "params_type": "query_3f", "default": "", "expected_format": "[0xEA][0x3A][pos_b3][pos_b2][pos_b1][pos_b0]"},
    {"cmd": 0xEA, "name": "bcmd_POSITION (Set current position)", "params_type": "set_3d", "default": "00 00 00 00", "expected_format": "[0xEA][0x3A][pos_b3][pos_b2][pos_b1][pos_b0]"},
    {"cmd": 0xEB, "name": "bcmd_TPOSREL (Move relative to position)", "params_type": "set_3d", "default": "00 00 27 10", "expected_format": "[0xEB]['S'][pos_b3][pos_b2][pos_b1][pos_b0]"},
    {"cmd": 0xEC, "name": "bcmd_ACCERROR (Set tracking error limit)", "params_type": "set_3d", "default": "00 0F", "expected_format": "[0xEC][0x3A][value_hi][value_lo]"},
    {"cmd": 0xED, "name": "bcmd_PID_RATE (PID slew rate/delay)", "params_type": "set_3d", "default": "00 0A", "expected_format": "[0xED][0x3A][value_hi][value_lo]"},
    {"cmd": 0xFA, "name": "bcmd_NVDATASELECT (Select NVRAM data block)", "params_type": "set_3d", "default": "01", "expected_format": "[0xFA][0x3A][block_id]"},
)


_BINARY_EXPECTED_KIND_OVERRIDES = {
    0x81: "tpos_status",
    0x82: "getpos",
    0x84: "velocity_ack",
    0x85: "getvel",
    0x88: "run_started",
    0xC3: "hunting",
    0xC4: "nodeconfig",
    0xC8: "firmware",
    0xC9: "lflag",
    0xCA: "rflag",
    0xCD: "type",
    0xCF: "motor_current_mA",
    0xD3: "log_motor_current_rate",
    0xD8: "interrupt",
    0xE4: "position_log_rate",
}

_BINARY_STABLE_NAMES = {
    (0xC8, "query_3f"): "GETVER",
    (0x82, "int32"): "GETPOS",
    (0x85, "none"): "GETVEL",
    (0x84, "int16"): "VEL Write",
    (0x88, "int16"): "RUN",
    (0xC4, "query_3f"): "NODECONFIG Query",
    (0xD8, "query_3f"): "INTERRUPT Query",
    (0xCF, "query_3f"): "MOTOR_I Query",
}

_BINARY_EXTRA_QUERY_ROWS: tuple[dict[str, object], ...] = (
    {"cmd": 0xC4, "name": "bcmd_NODECONFIG (Query Node Configuration)", "params_type": "query_3f", "default": "", "expected_format": "[0xC4][0x3A][operation_mode]"},
    {"cmd": 0xD8, "name": "bcmd_INTERRUPT (Query Interrupt State)", "params_type": "query_3f", "default": "", "expected_format": "[0xD8][0x3A][int0_status][int1_status]"},
    {"cmd": 0xCF, "name": "bcmd_MOTOR_I (Query Motor Current)", "params_type": "query_3f", "default": "", "expected_format": "[0xCF][0x3A][adc_hi][adc_lo]"},
)

_BINARY_EXTRA_QUERY_DISPLAY_NAMES = {
    "bcmd_NODECONFIG (Query Node Configuration)",
    "bcmd_INTERRUPT (Query Interrupt State)",
    "bcmd_MOTOR_I (Query Motor Current)",
}


def _build_manual_binary_command_definitions() -> tuple[FirmwareCommandDefinition, ...]:
    rows = sorted(
        list(_BINARY_COMMAND_ROWS) + list(_BINARY_EXTRA_QUERY_ROWS),
        key=_binary_catalog_sort_key,
    )
    definitions: list[FirmwareCommandDefinition] = []
    for order, row in enumerate(rows, start=1):
        opcode = int(row["cmd"]) & 0xFF
        params_type = str(row.get("params_type") or "none")
        name = _binary_command_key(row)
        policy = _binary_policy_for(row)
        schema = _binary_parameter_schema(row)
        definitions.append(
            FirmwareCommandDefinition(
                name=name,
                display_name=_binary_display_name(row, name),
                mode="binary",
                opcode=opcode,
                parameter_schema=schema,
                expected_response=_binary_expected_kind(row),
                expected_response_description=str(row.get("expected_format") or ""),
                timeout_ms=DEFAULT_MANUAL_BINARY_TIMEOUT_MS,
                manual_verification=bool(row.get("manual")) or policy == "MANUAL_VERIFICATION",
                manual_prompt=None if row.get("prompt") is None else str(row.get("prompt")),
                builder_name=_binary_builder_name(row),
                decoder_name="decode_command",
                execution_policy=policy,
                category=_binary_category_for(row),
                selected_by_default=_binary_selected_by_default(row),
                sort_order=order,
                cleanup_value=_binary_cleanup_value(row),
                unsupported_reason=None,
                validation={"params_type": params_type, "legacy_name": str(row.get("name") or "")},
                command_form=_binary_command_form(row),
                support_status=_binary_support_status(row),
                execution_capability=policy,
                node_applicability=_binary_node_applicability(row),
            )
        )
    return tuple(definitions)


def _binary_command_key(row: dict[str, object]) -> str:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    stable = _BINARY_STABLE_NAMES.get((opcode, params_type))
    if stable:
        return stable
    raw_name = str(row.get("name") or f"0x{opcode:02X}")
    clean = raw_name
    if clean.startswith("bcmd_"):
        clean = clean[5:]
    clean = clean.replace("bcmd_", "")
    clean = clean.replace("(", " - ").replace(")", "")
    clean = " ".join(clean.split())
    if params_type == "query_3f" and "Query" not in clean and "Get" not in clean:
        clean = f"{clean} Query"
    if params_type == "set_3d" and "Set" not in clean and "Configure" not in clean:
        clean = f"{clean} Set"
    return clean


def _binary_display_name(row: dict[str, object], command_key: str) -> str:
    raw_name = str(row.get("name") or "").strip()
    if raw_name in _BINARY_EXTRA_QUERY_DISPLAY_NAMES:
        return raw_name
    return command_key


def _binary_command_form(row: dict[str, object]) -> str:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    if (opcode, params_type) in {(0x82, "int32"), (0x85, "none")}:
        return "query"
    if params_type == "query_3f":
        return "query"
    if params_type in {"set_3d", "int16", "int32"}:
        return "set"
    name = str(row.get("name") or "").lower()
    if "get " in name or "query" in name or "reading" in name or "status" in name:
        return "query"
    if "reset" in name or "save" in name or "factory" in name:
        return "action"
    return "action" if params_type == "none" else "raw"


def _binary_parameter_schema(row: dict[str, object]) -> dict[str, object]:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    default = row.get("default")
    if opcode == 0x82 and params_type == "int32":
        return {"kind": "none"}
    if params_type == "query_3f":
        return {"kind": "query_3f"}
    if params_type == "int16":
        return {"kind": "int16", "label": "Value", "default": int(str(default or "0")), "minimum": -32768, "maximum": 32767}
    if params_type == "int32":
        return {"kind": "int32", "label": "Value", "default": int(str(default or "0")), "minimum": -2147483648, "maximum": 2147483647}
    if params_type == "set_3d":
        byte_count = len(str(default or "").split()) if str(default or "").strip() else None
        schema: dict[str, object] = {"kind": "set_3d", "label": "Value bytes", "default": str(default or "")}
        if byte_count is not None:
            schema["byte_count"] = byte_count
        return schema
    if params_type == "hex":
        byte_count = len(str(default or "").split()) if str(default or "").strip() else None
        schema = {"kind": "bytes", "label": "Payload bytes", "default": str(default or "")}
        if byte_count is not None:
            schema["byte_count"] = byte_count
        return schema
    return {"kind": "none"}


def _binary_builder_name(row: dict[str, object]) -> str:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    if opcode == 0x81:
        return "build_tpos"
    if opcode == 0xC8 and params_type == "query_3f":
        return "build_getver_query_payload"
    if opcode == 0x82:
        return "build_getpos"
    if opcode == 0x85:
        return "build_getvel_query_payload"
    if opcode == 0x84:
        return "build_vel"
    if opcode == 0x88:
        return "build_run"
    if opcode == 0xC4 and params_type == "query_3f":
        return "build_nodeconfig_query_payload"
    if opcode == 0xD8 and params_type == "query_3f":
        return "build_interrupt_query_payload"
    if opcode == 0xCF and params_type == "query_3f":
        return "build_motor_current_query_payload"
    if opcode == 0xD3 and params_type == "set_3d":
        return "build_motor_current_log_rate_payload"
    if opcode == 0xE4 and params_type == "set_3d":
        return "build_position_log_rate_payload"
    if opcode == 0xDD:
        return "build_stopmotor"
    if params_type == "query_3f":
        return "build_legacy_query_3f_payload"
    if params_type == "set_3d":
        return "build_legacy_set_3d_payload"
    if params_type == "hex":
        return "build_legacy_raw_payload"
    if params_type == "none":
        return "build_legacy_no_arg_payload"
    return "unsupported"


def _binary_has_semantic_decode(row: dict[str, object]) -> bool:
    opcode = int(row["cmd"]) & 0xFF
    return opcode in _BINARY_EXPECTED_KIND_OVERRIDES


def _binary_expected_kind(row: dict[str, object]) -> str | None:
    opcode = int(row["cmd"]) & 0xFF
    if opcode in _BINARY_EXPECTED_KIND_OVERRIDES:
        return _BINARY_EXPECTED_KIND_OVERRIDES[opcode]
    if _binary_builder_name(row) == "unsupported":
        return None
    return f"opcode_0x{opcode:02X}_match"


def _binary_policy_for(row: dict[str, object]) -> str:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    if (opcode, params_type) in {(0x82, "int32"), (0x85, "none")}:
        return "RESPONSE_DECODE"
    if opcode in {0xC7}:
        return "REBOOT_RECOVERY"
    if opcode in {0x81, 0x88, 0xDB, 0xDC, 0xEB}:
        return "MANUAL_VERIFICATION"
    if opcode == 0xDD:
        return "NO_RESPONSE"
    if opcode in {0x9E, 0x9F, 0xD3, 0xD4, 0xD5, 0xE3, 0xE4, 0xE6}:
        return "LOGGING_STREAM"
    if bool(row.get("manual")):
        return "MANUAL_VERIFICATION"
    if _binary_builder_name(row) == "unsupported":
        return "CONTRACT_UNKNOWN"
    if _binary_has_semantic_decode(row):
        return "RESPONSE_DECODE"
    return "RESPONSE_MATCH"


def _binary_category_for(row: dict[str, object]) -> str:
    opcode = int(row["cmd"]) & 0xFF
    name = str(row.get("name") or "").upper()
    if opcode in {0x81, 0x84, 0x88, 0xDB, 0xDC, 0xDD, 0xEB}:
        return "Motion"
    if opcode in {0x97, 0xC7}:
        return "Destructive"
    if opcode in {0xC5, 0x8D, 0x90, 0x91, 0x92, 0x93, 0x94, 0xC4, 0xCD, 0xE7, 0xFA}:
        return "Configuration"
    if opcode in {0x9E, 0x9F, 0xD3, 0xD4, 0xD5, 0xE3, 0xE4, 0xE6}:
        return "Logging"
    if opcode in {0xD0, 0xD1, 0xDE, 0xDF, 0xC9, 0xCA, 0xD8, 0x96}:
        return "Sensors"
    if "GET" in name or "STAT" in name or "INFO" in name or "VER" in name:
        return "Information"
    return "Engineering"


def _binary_selected_by_default(row: dict[str, object]) -> bool:
    opcode = int(row["cmd"]) & 0xFF
    params_type = str(row.get("params_type") or "none")
    return (opcode, params_type) in {
        (0x82, "int32"),
        (0x83, "none"),
        (0x85, "none"),
        (0x97, "none"),
        (0x9D, "none"),
        (0xA0, "none"),
        (0xC5, "none"),
        (0xC8, "query_3f"),
        (0xCB, "hex"),
        (0xCD, "query_3f"),
        (0xCD, "set_3d"),
        (0xCE, "none"),
        (0xD8, "none"),
        (0xDB, "none"),
        (0xDC, "none"),
        (0xDD, "none"),
        (0xDE, "none"),
    }


def _binary_cleanup_value(row: dict[str, object]) -> object | None:
    if _binary_policy_for(row) == "LOGGING_STREAM":
        return "00 00" if len(str(row.get("default") or "").split()) > 1 else "00"
    return None


def _binary_support_status(row: dict[str, object]) -> str:
    policy = _binary_policy_for(row)
    if policy == "CONTRACT_UNKNOWN":
        return "UNSUPPORTED"
    if policy in {"MANUAL_VERIFICATION", "LOGGING_STREAM", "REBOOT_RECOVERY"}:
        return "HARDWARE_VALIDATION_REQUIRED"
    return "SUPPORTED"


def _binary_node_applicability(row: dict[str, object]) -> tuple[str, ...] | None:
    category = _binary_category_for(row)
    if category == "Motion":
        return ("motor",)
    if category == "Sensors":
        return ("sensor", "motor", "ng")
    return None


def _binary_unsupported_reason(row: dict[str, object]) -> str | None:
    policy = _binary_policy_for(row)
    builder_name = _binary_builder_name(row)
    if policy == "CONTRACT_UNKNOWN" or builder_name == "unsupported":
        return "No explicit canonical binary request contract is available for automated execution."
    return None


def _binary_catalog_sort_key(row: dict[str, object]) -> tuple[int, int, str]:
    opcode = int(row["cmd"]) & 0xFF
    form_priority = {"query": 0, "set": 1}.get(_binary_command_form(row), 2)
    return opcode, form_priority, _binary_command_key(row)


_TEXT_COMMAND_ROWS: tuple[dict[str, object], ...] = (
    {"cmd": "uartstat?", "type": "query", "expected": "uartstat:", "default": "", "format": "uartstat:ok,err,empty,end", "category": "Diagnostics"},
    {"cmd": "opmode?", "type": "query", "expected": "opmode:", "default": "", "format": "opmode:<number> (operating mode)", "category": "Diagnostics"},
    {"cmd": "opmode=", "type": "set", "expected": "opmode:", "default": "1", "format": "opmode:<number> (operating mode)", "category": "Configuration", "validation": {"kind": "int", "minimum": 0, "maximum": 7}},
    {"cmd": "spimem?", "type": "query", "expected": "spimem:", "default": "", "format": "spimem:<errStat(0=OK)>,<nvStatus(1=READ|2=SAVE|4=FACTORYDEF)>", "category": "Diagnostics"},
    {"cmd": "serialno?", "type": "query", "expected": "serialno:", "default": "", "format": "serialno:<text>", "category": "Information"},
    {"cmd": "serialno=", "type": "set", "expected": "serialno:", "default": "SN1002", "format": "serialno:<text>", "category": "Configuration", "policy": "PERSISTENT_CHANGE", "validation": {"kind": "text", "max_length": 32}},
    {"cmd": "product?", "type": "query", "expected": "product:", "default": "", "format": "product:<text>", "category": "Information"},
    {"cmd": "product=", "type": "set", "expected": "product:", "default": "MonaLisa2.0", "format": "product:<text>", "category": "Configuration", "policy": "PERSISTENT_CHANGE", "validation": {"kind": "text", "max_length": 48}},
    {"cmd": "mfgdate?", "type": "query", "expected": "mfgdate:", "default": "", "format": "mfgdate:<text>", "category": "Information"},
    {"cmd": "mfgdate=", "type": "set", "expected": "mfgdate:", "default": "20260520", "format": "mfgdate:<text>", "category": "Configuration", "policy": "PERSISTENT_CHANGE", "validation": {"kind": "date_yyyymmdd"}},
    {"cmd": "HWI?", "type": "query", "expected": "HWI:", "default": "", "format": "HWI:<text>", "category": "Information"},
    {"cmd": "HWI=", "type": "set", "expected": "HWI:", "default": "HW01", "format": "HWI:<text>", "category": "Configuration", "policy": "PERSISTENT_CHANGE", "validation": {"kind": "text", "max_length": 32}},
    {"cmd": "factorydef!", "type": "action", "expected": "factorydef", "default": "", "format": "factorydef", "category": "Actions", "policy": "UNSUPPORTED", "unsupported_reason": "Factory-default action requires dedicated hardware recovery validation."},
    {"cmd": "save", "type": "action", "expected": "save:ACK", "default": "", "format": "save:ACK", "category": "Actions", "policy": "ACTION_ACK"},
    {"cmd": "dltxfifo=", "type": "set", "expected": "dltxfifo", "default": "3", "format": "dltxfifo<fifo_index>:nodeID,overrun,maxused,size", "category": "Diagnostics", "validation": {"kind": "int", "minimum": 0, "maximum": 15}},
    {"cmd": "dlrxfifo=", "type": "set", "expected": "dlrxfifo", "default": "3", "format": "dlrxfifo<fifo_index>:nodeID,overrun,maxused,size", "category": "Diagnostics", "validation": {"kind": "int", "minimum": 0, "maximum": 15}},
    {"cmd": "utxfifo?", "type": "query", "expected": "utxfifo", "default": "", "format": "utxfifo<fifo_index>:overrun,maxused,size", "category": "Diagnostics"},
    {"cmd": "urxfifo?", "type": "query", "expected": "urxfifo", "default": "", "format": "urxfifo<fifo_index>:overrun,maxused,size", "category": "Diagnostics"},
    {"cmd": "cmdparser?", "type": "query", "expected": "cmdparser", "default": "", "format": "cmdparser<fifo_index>:overrun,maxused,size", "category": "Diagnostics"},
    {"cmd": "m_amx?", "type": "query", "expected": "m_amx:", "default": "", "format": "m_amx:pktSizeMax,dataSize", "category": "Diagnostics"},
    {"cmd": "ver?", "type": "query", "expected": "ver:", "default": "", "format": "ver:Maj.Min.Sub_<build_number>", "category": "Information"},
    {"cmd": "i2cPC?", "type": "query", "expected": "i2cPC:", "default": "", "format": "i2cPC:<status> (0=OK)", "category": "Diagnostics"},
    {"cmd": "i2cMOT?", "type": "query", "expected": "i2cMOT:", "default": "", "format": "i2cMOT:<status> (0=OK)", "category": "Diagnostics"},
    {"cmd": "i2cUSB?", "type": "query", "expected": "i2cUSB:", "default": "", "format": "i2cUSB:<status> (0=OK)", "category": "Diagnostics"},
    {"cmd": "i2cMON?", "type": "query", "expected": "i2cMON:", "default": "", "format": "i2cMON:<status> (0=OK)", "category": "Diagnostics"},
    {"cmd": "viPC?", "type": "query", "expected": "viPC:", "default": "", "format": "viPC:voltage_mV,current_mA", "category": "Diagnostics"},
    {"cmd": "viMON?", "type": "query", "expected": "viMON:", "default": "", "format": "viMON:voltage_mV,current_mA", "category": "Diagnostics"},
    {"cmd": "viMOT?", "type": "query", "expected": "viMOT:", "default": "", "format": "viMOT:voltage_mV,current_mA", "category": "Diagnostics"},
    {"cmd": "viUSB?", "type": "query", "expected": "viUSB:", "default": "", "format": "viUSB:voltage_mV,current_mA", "category": "Diagnostics"},
    {"cmd": "onRB?", "type": "query", "expected": "onRB:", "default": "", "format": "onRB:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onRB=", "type": "set", "expected": "onRB:", "default": "1", "format": "onRB:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "onMON?", "type": "query", "expected": "onMON:", "default": "", "format": "onMON:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onMON=", "type": "set", "expected": "onMON:", "default": "1", "format": "onMON:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "onUSB?", "type": "query", "expected": "onUSB:", "default": "", "format": "onUSB:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onUSB=", "type": "set", "expected": "onUSB:", "default": "1", "format": "onUSB:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "onPC?", "type": "query", "expected": "onPC:", "default": "", "format": "onPC:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onPC=", "type": "set", "expected": "onPC:", "default": "1", "format": "onPC:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "onExtUSB?", "type": "query", "expected": "onExtUSB:", "default": "", "format": "onExtUSB:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onExtUSB=", "type": "set", "expected": "onExtUSB:", "default": "1", "format": "onExtUSB:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "onSLPWR?", "type": "query", "expected": "onSLPWR:", "default": "", "format": "onSLPWR:<0|1> (0=OFF, 1=ON)", "category": "Power"},
    {"cmd": "onSLPWR=", "type": "set", "expected": "onSLPWR:", "default": "1", "format": "onSLPWR:<0|1>", "category": "Power", "policy": "POWER_CONTROL", "validation": {"kind": "choice", "choices": ("0", "1")}},
    {"cmd": "sysbtn?", "type": "query", "expected": "sysbtn:", "default": "", "format": "sysbtn:0", "category": "Diagnostics"},
    {"cmd": "keybtn?", "type": "query", "expected": "keybtn:", "default": "", "format": "keybtn:0", "category": "Diagnostics"},
    {"cmd": "emobtn?", "type": "query", "expected": "emobtn:", "default": "", "format": "emobtn:<number> (button state)", "category": "Diagnostics"},
    {"cmd": "ONbtndc?", "type": "query", "expected": "ONbtndc:", "default": "", "format": "ONbtndc:<0-100> (duty cycle %)", "category": "Power"},
    {"cmd": "ONbtndc=", "type": "set", "expected": "ONbtndc:", "default": "50", "format": "ONbtndc:<number>", "category": "Power", "validation": {"kind": "int", "minimum": 0, "maximum": 100}},
    {"cmd": "SWReady?", "type": "query", "expected": "SWReady:", "default": "", "format": "SWReady:<0|1|2> (0=NotReady, 1=Ready, 2=Active)", "category": "Power"},
    {"cmd": "SWReady=", "type": "set", "expected": "SWReady:", "default": "2", "format": "SWReady:<number>", "category": "Power", "validation": {"kind": "choice", "choices": ("0", "1", "2")}},
    {"cmd": "commandshutdown=", "type": "set", "expected": "commandshutdown:", "default": "0", "format": "commandshutdown:<number>", "category": "Actions", "policy": "UNSUPPORTED", "unsupported_reason": "Shutdown behavior requires dedicated recovery validation."},
    {"cmd": "shdnthreshold?", "type": "query", "expected": "shdnthreshold:", "default": "", "format": "shdnthreshold:<number> (milliamps)", "category": "Configuration"},
    {"cmd": "shdnthreshold=", "type": "set", "expected": "shdnthreshold:", "default": "200", "format": "shdnthreshold:<number>", "category": "Configuration", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "shdnsampleperiod?", "type": "query", "expected": "shdnsampleperiod:", "default": "", "format": "shdnsampleperiod:<number> (milliseconds)", "category": "Configuration"},
    {"cmd": "shdnsampleperiod=", "type": "set", "expected": "shdnsampleperiod:", "default": "4000", "format": "shdnsampleperiod:<number>", "category": "Configuration", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "ONbtnrt?", "type": "query", "expected": "ONbtnrt:", "default": "", "format": "ONbtnrt:<number> (milliseconds)", "category": "Configuration"},
    {"cmd": "ONbtnrt=", "type": "set", "expected": "ONbtnrt:", "default": "100", "format": "ONbtnrt:<number>", "category": "Configuration", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "autoSWReady?", "type": "query", "expected": "autoSWReady:", "default": "", "format": "autoSWReady:<number> (seconds)", "category": "Configuration"},
    {"cmd": "autoSWReady=", "type": "set", "expected": "autoSWReady:", "default": "0", "format": "autoSWReady:<number>", "category": "Configuration", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "logEMObtn?", "type": "query", "expected": "logEMObtn:", "default": "", "format": "logEMObtn:<number> (milliseconds)", "category": "Logging"},
    {"cmd": "logEMObtn=", "type": "set", "expected": "logEMObtn:", "default": "500", "format": "logEMObtn:<number>", "category": "Logging", "policy": "LOGGING_STREAM", "cleanup_value": "0", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "logPC?", "type": "query", "expected": "logPC:", "default": "", "format": "logPC:<number> (log rate ms)", "category": "Logging"},
    {"cmd": "logPC=", "type": "set", "expected": "logPC:", "default": "1000", "format": "logPC:<number>", "category": "Logging", "policy": "LOGGING_STREAM", "cleanup_value": "0", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "logUSB?", "type": "query", "expected": "logUSB:", "default": "", "format": "logUSB:<number> (log rate ms)", "category": "Logging"},
    {"cmd": "logUSB=", "type": "set", "expected": "logUSB:", "default": "1000", "format": "logUSB:<number>", "category": "Logging", "policy": "LOGGING_STREAM", "cleanup_value": "0", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "logMOT?", "type": "query", "expected": "logMOT:", "default": "", "format": "logMOT:<number> (log rate ms)", "category": "Logging"},
    {"cmd": "logMOT=", "type": "set", "expected": "logMOT:", "default": "1000", "format": "logMOT:<number>", "category": "Logging", "policy": "LOGGING_STREAM", "cleanup_value": "0", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "logMON?", "type": "query", "expected": "logMON:", "default": "", "format": "logMON:<number> (log rate ms)", "category": "Logging"},
    {"cmd": "logMON=", "type": "set", "expected": "logMON:", "default": "1000", "format": "logMON:<number>", "category": "Logging", "policy": "LOGGING_STREAM", "cleanup_value": "0", "validation": {"kind": "int", "minimum": 0, "maximum": 65535}},
    {"cmd": "diagLED?", "type": "query", "expected": "diagLED:", "default": "", "format": "diagLED:<number> (LED state)", "category": "Diagnostics"},
    {"cmd": "diagLED=", "type": "set", "expected": "diagLED:", "default": "2", "format": "diagLED:<number>", "category": "Diagnostics", "policy": "MANUAL_VERIFICATION", "manual_prompt": "Confirm the diagnostic LED state changed as expected.", "validation": {"kind": "int", "minimum": 0, "maximum": 255}},
    {"cmd": "reset!", "type": "action", "expected": "reset", "default": "", "format": "(no response - MCU reboots)", "category": "Actions", "policy": "REBOOT", "unsupported_reason": "MCU reset/reboot requires hardware recovery validation before automated execution."},
)

_TEXT_DISPLAY_NAMES = {
    "ver?": "Version Query",
    "uartstat?": "UART Status Query",
    "opmode?": "Operating Mode Query",
    "onRB?": "Robot Power Query",
    "onRB=": "Robot Power Set",
}


def _text_policy_for(row: dict[str, object]) -> str:
    explicit = str(row.get("policy") or "").strip()
    if explicit:
        return explicit
    command_type = str(row.get("type") or "").strip()
    if command_type == "query":
        return "QUERY_RESPONSE"
    if command_type == "action":
        return "ACTION_ACK"
    return "SET_RESPONSE"


def _text_parameter_schema(row: dict[str, object]) -> dict[str, object]:
    command_type = str(row.get("type") or "").strip()
    default = str(row.get("default") or "")
    validation = dict(row.get("validation") or {})
    if command_type != "set":
        return {"kind": "none"}
    if not validation:
        validation = {"kind": "text", "max_length": 64}
    schema = {"label": "Value", "default": default, **validation}
    return schema


def _text_catalog_sort_key(item: tuple[int, dict[str, object]]) -> tuple[int, int]:
    legacy_order, row = item
    command = str(row.get("cmd") or "")
    command_type = str(row.get("type") or "")
    policy = _text_policy_for(row)
    priority_commands = {
        "ver?": 0,
        "uartstat?": 1,
        "opmode?": 2,
        "onRB?": 3,
    }
    if command in priority_commands:
        return priority_commands[command], legacy_order
    if command_type == "query":
        return 10, legacy_order
    if policy == "SET_RESPONSE":
        return 40, legacy_order
    if policy in {"POWER_CONTROL", "PERSISTENT_CHANGE"}:
        return 50, legacy_order
    if policy == "MANUAL_VERIFICATION":
        return 60, legacy_order
    if policy == "LOGGING_STREAM":
        return 70, legacy_order
    if policy == "ACTION_ACK":
        return 80, legacy_order
    if policy == "UNSUPPORTED":
        return 90, legacy_order
    return 75, legacy_order


def _build_manual_text_command_definitions() -> tuple[FirmwareCommandDefinition, ...]:
    definitions: list[FirmwareCommandDefinition] = []
    ordered_rows = sorted(enumerate(_TEXT_COMMAND_ROWS, start=1), key=_text_catalog_sort_key)
    for order, (_legacy_order, row) in enumerate(ordered_rows, start=1):
        command_text = str(row["cmd"])
        command_type = str(row.get("type") or "")
        policy = _text_policy_for(row)
        manual_verification = bool(row.get("manual_verification")) or policy == "MANUAL_VERIFICATION"
        definitions.append(
            FirmwareCommandDefinition(
                name=_TEXT_DISPLAY_NAMES.get(command_text, command_text),
                display_name=_TEXT_DISPLAY_NAMES.get(command_text, command_text),
                mode="text",
                text_command=command_text,
                parameter_schema=_text_parameter_schema(row),
                expected_response=str(row.get("expected") or ""),
                expected_response_description=str(row.get("format") or row.get("expected") or ""),
                timeout_ms=DEFAULT_MANUAL_TEXT_TIMEOUT_MS,
                manual_verification=manual_verification,
                manual_prompt=None if row.get("manual_prompt") is None else str(row.get("manual_prompt")),
                builder_name="build_text_command_payload",
                decoder_name="decode_text_command_response",
                execution_policy=policy,
                category=str(row.get("category") or "Engineering"),
                selected_by_default=command_type == "query",
                sort_order=order,
                cleanup_value=row.get("cleanup_value"),
                unsupported_reason=None if row.get("unsupported_reason") is None else str(row.get("unsupported_reason")),
                validation=dict(row.get("validation") or {}),
            )
        )
    return tuple(definitions)


def _build_binary_fit_case_definitions(
    command_definitions: tuple[FirmwareCommandDefinition, ...],
) -> tuple[FirmwareTestCase, ...]:
    legacy_case_ids = {
        "GETVER": "binary-fit-getver",
        "GETPOS": "binary-fit-getpos",
        "GETVEL": "binary-fit-getvel",
        "NODECONFIG Query": "binary-fit-nodeconfig-query",
        "INTERRUPT Query": "binary-fit-interrupt-query",
        "MOTOR_I Query": "binary-fit-motor-i-query",
    }
    cases: list[FirmwareTestCase] = []
    for definition in command_definitions:
        schema = definition.parameter_schema or {}
        kind = str(schema.get("kind", "none"))
        default_value = schema.get("default") if kind not in {"none", "query_3f"} else None
        case_id = legacy_case_ids.get(
            definition.name,
            f"binary-fit-{_slugify_text_key(definition.name)}-{int(definition.opcode or 0):02x}-{definition.command_form or 'command'}",
        )
        unsupported_reason = _binary_unsupported_reason(
            {
                "cmd": int(definition.opcode or 0),
                "name": str((definition.validation or {}).get("legacy_name") or definition.name),
                "params_type": str((definition.validation or {}).get("params_type") or kind),
                "expected_format": definition.expected_response_description or "",
            }
        )
        cases.append(
            FirmwareTestCase(
                case_id=case_id,
                name=str(definition.display_name or definition.name),
                mode="binary",
                command_key=definition.name,
                parameter_value=default_value,
                expected_response=definition.expected_response,
                timeout_ms=definition.timeout_ms,
                manual_verification=definition.manual_verification,
                manual_prompt=definition.manual_prompt,
                selected_by_default=bool(definition.selected_by_default),
                category=definition.category,
                display_group=definition.category,
                execution_policy=definition.execution_policy,
                expected_response_description=definition.expected_response_description,
                cleanup_value=definition.cleanup_value,
                unsupported_reason=unsupported_reason,
                support_status=definition.support_status,
                execution_capability=definition.execution_capability or definition.execution_policy,
                node_applicability=definition.node_applicability,
            )
        )
    return tuple(cases)


def _build_text_fit_case_definitions(
    command_definitions: tuple[FirmwareCommandDefinition, ...],
) -> tuple[FirmwareTestCase, ...]:
    legacy_case_ids = {
        "Version Query": "text-fit-version-query",
        "UART Status Query": "text-fit-uart-status-query",
        "Operating Mode Query": "text-fit-operating-mode-query",
        "Robot Power Query": "text-fit-robot-power-query",
    }
    cases: list[FirmwareTestCase] = []
    for definition in command_definitions:
        schema = definition.parameter_schema or {}
        case_id = legacy_case_ids.get(
            definition.name,
            f"text-fit-{_slugify_text_key(definition.name)}-{_slugify_text_command_form(definition.text_command)}",
        )
        default_value = schema.get("default") if str(schema.get("kind", "none")) != "none" else None
        cases.append(
            FirmwareTestCase(
                case_id=case_id,
                name=str(definition.display_name or definition.name),
                mode="text",
                command_key=definition.name,
                parameter_value=default_value,
                expected_response=definition.expected_response,
                timeout_ms=definition.timeout_ms,
                manual_verification=definition.manual_verification,
                manual_prompt=(
                    definition.manual_prompt or "Operator verification required."
                    if definition.manual_verification and definition.unsupported_reason is None
                    else None
                ),
                selected_by_default=bool(definition.selected_by_default),
                category=definition.category,
                display_group=definition.category,
                execution_policy=definition.execution_policy,
                expected_response_description=definition.expected_response_description,
                cleanup_value=definition.cleanup_value,
                unsupported_reason=definition.unsupported_reason,
            )
        )
    return tuple(cases)


def _slugify_text_key(value: str) -> str:
    chars: list[str] = []
    for char in str(value).lower():
        if char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    slug = "-".join(part for part in "".join(chars).split("-") if part)
    return slug or "command"


def _slugify_text_command_form(value: str | None) -> str:
    command = str(value or "")
    if command.endswith("?"):
        suffix = "query"
        command = command[:-1]
    elif command.endswith("="):
        suffix = "set"
        command = command[:-1]
    elif command.endswith("!"):
        suffix = "action"
        command = command[:-1]
    else:
        suffix = "command"
    base = _slugify_text_key(command)
    return f"{base}-{suffix}"


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
        if builder_name == "build_tpos":
            default = (definition.parameter_schema or {}).get("default", 0)
            return build_tpos(int(parameter_value if parameter_value is not None else default))
        if builder_name == "build_nodeconfig_query_payload":
            return build_nodeconfig_query_payload()
        if builder_name == "build_interrupt_query_payload":
            return build_interrupt_query_payload()
        if builder_name == "build_motor_current_query_payload":
            return build_motor_current_query_payload()
        if builder_name == "build_motor_current_log_rate_payload":
            default = (definition.parameter_schema or {}).get("default", 0)
            raw_value = parameter_value if parameter_value is not None else default
            if isinstance(raw_value, str):
                raw_value = int(raw_value.replace(" ", ""), 16)
            return build_motor_current_log_rate_payload(int(raw_value))
        if builder_name == "build_position_log_rate_payload":
            default = (definition.parameter_schema or {}).get("default", 0)
            raw_value = parameter_value if parameter_value is not None else default
            if isinstance(raw_value, str):
                raw_value = int(raw_value.replace(" ", ""), 16)
            return build_position_log_rate_payload(int(raw_value))
        if builder_name == "build_stopmotor":
            return build_stopmotor()
        if builder_name == "build_legacy_query_3f_payload":
            return build_legacy_query_3f_payload(int(definition.opcode or 0))
        if builder_name == "build_legacy_set_3d_payload":
            schema = definition.parameter_schema or {}
            default = schema.get("default", "")
            byte_count = schema.get("byte_count")
            return build_legacy_set_3d_payload(
                int(definition.opcode or 0),
                parameter_value if parameter_value is not None else default,
                int(byte_count) if byte_count is not None else None,
            )
        if builder_name == "build_legacy_raw_payload":
            schema = definition.parameter_schema or {}
            default = schema.get("default", "")
            byte_count = schema.get("byte_count")
            return build_legacy_raw_payload(
                int(definition.opcode or 0),
                parameter_value if parameter_value is not None else default,
                int(byte_count) if byte_count is not None else None,
            )
        if builder_name == "build_legacy_no_arg_payload":
            return build_legacy_no_arg_payload(int(definition.opcode or 0))
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
        if definition.unsupported_reason:
            raise ValueError(f"{definition.name} is not supported for sending yet: {definition.unsupported_reason}")
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

        if kind == "int":
            try:
                integer_value = int(normalized, 10)
            except ValueError as exc:
                raise ValueError(f"Manual text command {definition.name} requires an integer value.") from exc
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and integer_value < int(minimum):
                raise ValueError(f"Manual text command {definition.name} must be at least {int(minimum)}.")
            if maximum is not None and integer_value > int(maximum):
                raise ValueError(f"Manual text command {definition.name} must be at most {int(maximum)}.")
            return str(integer_value)

        if kind == "date_yyyymmdd":
            if len(normalized) != 8 or not normalized.isdigit():
                raise ValueError(f"Manual text command {definition.name} requires YYYYMMDD format.")
            return normalized

        if kind == "text":
            max_length = schema.get("max_length")
            if max_length is not None and len(normalized) > int(max_length):
                raise ValueError(f"Manual text command {definition.name} must be {int(max_length)} characters or fewer.")
            try:
                normalized.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError(f"Manual text command {definition.name} requires ASCII text.") from exc
            return normalized
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

    @staticmethod
    def _command_display(command_definition: FirmwareCommandDefinition) -> str:
        if command_definition.opcode is None:
            return command_definition.name
        return f"{command_definition.name} (0x{int(command_definition.opcode) & 0xFF:02X})"

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
            execution_policy=str(case.execution_policy or command_definition.execution_policy or "QUERY_RESPONSE"),
            cleanup_value=case.cleanup_value if case.cleanup_value is not None else command_definition.cleanup_value,
        )
        self._current_request = request
        return request

    def accepts_response(self, *, sender: int | None, cmd: int | None) -> bool:
        request = self._current_request
        if request is None:
            return False
        return _ManualBinaryWorkflow.accepts_response(request, sender=sender, cmd=cmd)

    def handle_matching_response(self, packet: dict[str, object], *, received_at: float) -> tuple[FirmwareTestResult | None, dict[str, object] | None, dict[str, object] | None]:
        request = self._current_request
        if request is None:
            return None, None, None

        command = int(packet.get("cmd", 0)) & 0xFF
        params = [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)]
        decoded_kind, decoded_value = decode_command(command, params)
        expected = str(request.case.expected_response or request.command_definition.expected_response or "")
        actual = _ManualBinaryWorkflow._format_decoded_response(command, decoded_kind, decoded_value)
        response_hex = str(packet.get("raw_hex") or _ManualBinaryWorkflow._format_hex([command, *params]))
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        semantic_decode_available = decoded_kind is not None
        if request.execution_policy == "RESPONSE_DECODE":
            status = "PASS" if decoded_kind == expected else "FAIL"
            message = (
                f"Matched expected semantic response {expected}."
                if status == "PASS"
                else f"Expected semantic response {expected}, received {decoded_kind or 'unknown'}."
            )
        else:
            status = "PASS"
            if semantic_decode_available:
                message = f"Matched response opcode 0x{command:02X}; semantic decode available as {decoded_kind}."
            else:
                message = f"Matched response opcode 0x{command:02X}; semantic decode unavailable."
        if request.execution_policy == "LOGGING_STREAM" and not request.cleanup_pending and request.cleanup_value is not None:
            cleanup_request = {
                "case": request.case,
                "command_definition": request.command_definition,
                "cleanup_value": request.cleanup_value,
                "primary_actual": actual,
                "primary_rx_bytes": bytes(bytearray.fromhex(response_hex)) if response_hex != "--" else None,
                "primary_latency_ms": latency_ms,
                "semantic_decode_available": semantic_decode_available,
            }
            return None, None, cleanup_request

        if request.cleanup_pending:
            actual = request.primary_actual or actual
            latency_ms = request.primary_latency_ms if request.primary_latency_ms is not None else latency_ms
            message = f"{message} Cleanup command completed."
            cleanup = "completed"
        else:
            cleanup = None

        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status=status,
            mode=request.case.mode,
            case_name=request.case.name,
            command_key=request.case.command_key,
            command_display=self._command_display(request.command_definition),
            target_node_id=request.node_id,
            expected=expected or None,
            actual=actual,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=bytes(bytearray.fromhex(response_hex)) if response_hex != "--" else None,
            latency_ms=latency_ms,
            message=message,
            manual_verification_outcome=None,
            cleanup=cleanup,
            semantic_decode_available=semantic_decode_available,
            execution_capability=request.execution_policy,
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
            }, None

        self._results.append(result)
        self._current_index += 1
        return result, None, None

    def timeout_current_case(self) -> FirmwareTestResult | None:
        request = self._current_request
        if request is None:
            return None
        self._current_request = None
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="TIMEOUT",
            mode=request.case.mode,
            case_name=request.case.name,
            command_key=request.case.command_key,
            command_display=self._command_display(request.command_definition),
            target_node_id=request.node_id,
            expected=request.case.expected_response or request.command_definition.expected_response,
            actual=None,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=None,
            latency_ms=None,
            message="Timed out waiting for matching firmware response.",
            manual_verification_outcome=None,
            cleanup="pending" if request.execution_policy == "LOGGING_STREAM" else None,
            semantic_decode_available=None,
            execution_capability=request.execution_policy,
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
            mode=case.mode,
            case_name=case.name,
            command_key=case.command_key,
            command_display=self._command_display(command_definition),
            target_node_id=self._node_id,
            expected=case.expected_response or command_definition.expected_response,
            actual=None,
            tx_bytes=None if payload is None else bytes(payload),
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
            cleanup=None,
            semantic_decode_available=None,
            execution_capability=case.execution_capability or case.execution_policy or command_definition.execution_capability,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def record_unsupported_case(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        message: str,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=case.case_id,
            status="UNSUPPORTED",
            mode=case.mode,
            case_name=case.name,
            command_key=case.command_key,
            command_display=self._command_display(command_definition),
            target_node_id=self._node_id,
            expected=case.expected_response or command_definition.expected_response,
            actual=None,
            tx_bytes=None,
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
            cleanup=None,
            semantic_decode_available=None,
            execution_capability=case.execution_capability or case.execution_policy or command_definition.execution_capability,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def record_no_response_completion(
        self,
        *,
        request: _PendingBinaryFitCaseRequest,
        message: str,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="PASS",
            mode=request.case.mode,
            case_name=request.case.name,
            command_key=request.case.command_key,
            command_display=self._command_display(request.command_definition),
            target_node_id=request.node_id,
            expected=request.case.expected_response or request.command_definition.expected_response,
            actual="No response expected.",
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
            cleanup=None,
            semantic_decode_available=False,
            execution_capability=request.execution_policy,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def record_cleanup_sent(
        self,
        *,
        cleanup_request: dict[str, object],
        payload: list[int],
        sent_frame: bytes,
        sent_started_at: float,
    ) -> _PendingBinaryFitCaseRequest:
        case = cleanup_request["case"]
        command_definition = cleanup_request["command_definition"]
        if not isinstance(case, FirmwareTestCase) or not isinstance(command_definition, FirmwareCommandDefinition):
            raise ValueError("Invalid Binary FIT cleanup request.")
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
            execution_policy=str(case.execution_policy or command_definition.execution_policy or "LOGGING_STREAM"),
            cleanup_value=case.cleanup_value if case.cleanup_value is not None else command_definition.cleanup_value,
            cleanup_pending=True,
            primary_actual=None if cleanup_request.get("primary_actual") is None else str(cleanup_request.get("primary_actual")),
            primary_rx_bytes=cleanup_request.get("primary_rx_bytes") if isinstance(cleanup_request.get("primary_rx_bytes"), bytes) else None,
            primary_latency_ms=cleanup_request.get("primary_latency_ms") if isinstance(cleanup_request.get("primary_latency_ms"), float) else None,
        )
        self._current_request = request
        return request

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
                mode=request.case.mode,
                case_name=request.case.name,
                command_key=request.case.command_key,
                command_display=self._command_display(request.command_definition),
                target_node_id=request.node_id,
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

    @staticmethod
    def _command_display(command_definition: FirmwareCommandDefinition, command_text: str | None = None) -> str:
        return str(command_text or command_definition.text_command or command_definition.name)

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
            execution_policy=str(case.execution_policy or command_definition.execution_policy or "QUERY_RESPONSE"),
            cleanup_value=case.cleanup_value if case.cleanup_value is not None else command_definition.cleanup_value,
        )
        self._current_request = request
        return request

    def record_no_response_completion(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        command_text: str,
        sent_frame: bytes,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=case.case_id,
            status="PASS",
            mode=case.mode,
            case_name=case.name,
            command_key=case.command_key,
            command_display=self._command_display(command_definition, command_text),
            target_node_id=None,
            expected=case.expected_response or command_definition.expected_response,
            actual="No response expected.",
            tx_bytes=bytes(sent_frame),
            rx_bytes=None,
            latency_ms=None,
            message="Command sent; policy marks this command complete without waiting for a response.",
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def record_unsupported_case(
        self,
        *,
        case: FirmwareTestCase,
        command_definition: FirmwareCommandDefinition,
        message: str,
    ) -> FirmwareTestResult:
        result = FirmwareTestResult(
            case_id=case.case_id,
            status="UNSUPPORTED",
            mode=case.mode,
            case_name=case.name,
            command_key=case.command_key,
            command_display=self._command_display(command_definition),
            target_node_id=None,
            expected=case.expected_response or command_definition.expected_response,
            actual=None,
            tx_bytes=None,
            rx_bytes=None,
            latency_ms=None,
            message=message,
            manual_verification_outcome=None,
        )
        self._results.append(result)
        self._current_index += 1
        self._current_request = None
        return result

    def record_cleanup_sent(self, *, sent_frame: bytes, sent_started_at: float) -> _PendingTextFitCaseRequest:
        request = self._current_request
        if request is None:
            raise ValueError("Text FIT cleanup requested without an active case.")
        updated = replace(
            request,
            sent_frame=bytes(sent_frame),
            sent_started_at=sent_started_at,
            cleanup_pending=True,
        )
        self._current_request = updated
        return updated

    def handle_matching_response(
        self,
        packet: dict[str, object],
        *,
        received_at: float,
    ) -> tuple[FirmwareTestResult | None, dict[str, object] | None, dict[str, object] | None]:
        request = self._current_request
        if request is None:
            return None, None, None

        matched = _ManualTextWorkflow.match_expected_prefix(expected_prefix=request.expected_prefix, packet=packet)
        if matched is None:
            return None, None, None

        response_text, _response_hex = matched
        raw_payload = packet.get("raw_payload")
        rx_bytes = bytes([int(value) & 0xFF for value in list(raw_payload)]) if isinstance(raw_payload, list) else None
        latency_ms = max(0.0, (received_at - request.sent_started_at) * 1000.0)
        expected = str(request.case.expected_response or request.command_definition.expected_response or "") or None

        if request.execution_policy == "LOGGING_STREAM" and not request.cleanup_pending:
            self._current_request = replace(
                request,
                primary_response_text=response_text,
                primary_rx_bytes=rx_bytes,
                primary_latency_ms=latency_ms,
            )
            return None, None, {
                "case_id": request.case.case_id,
                "name": request.case.name,
                "command_name": request.command_definition.name,
                "cleanup_value": request.cleanup_value if request.cleanup_value is not None else "0",
                "expected_prefix": request.expected_prefix,
                "timeout_ms": request.timeout_ms,
                "primary_response": response_text,
            }

        actual_text = response_text
        message = f"Matched expected text prefix {request.expected_prefix}."
        result_rx_bytes = rx_bytes
        result_latency = latency_ms
        if request.execution_policy == "LOGGING_STREAM" and request.cleanup_pending:
            actual_text = f"{request.primary_response_text or ''} | cleanup: {response_text}".strip()
            message = f"Matched logging response and confirmed cleanup stop value {request.cleanup_value or '0'}."
            result_rx_bytes = rx_bytes
            result_latency = request.primary_latency_ms

        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="PASS",
            mode=request.case.mode,
            case_name=request.case.name,
            command_key=request.case.command_key,
            command_display=self._command_display(request.command_definition, request.command_text),
            target_node_id=None,
            expected=expected,
            actual=actual_text,
            tx_bytes=bytes(request.sent_frame),
            rx_bytes=result_rx_bytes,
            latency_ms=result_latency,
            message=message,
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
            }, None

        self._results.append(result)
        self._current_index += 1
        return result, None, None

    def timeout_current_case(self) -> FirmwareTestResult | None:
        request = self._current_request
        if request is None:
            return None
        self._current_request = None
        result = FirmwareTestResult(
            case_id=request.case.case_id,
            status="TIMEOUT",
            mode=request.case.mode,
            case_name=request.case.name,
            command_key=request.case.command_key,
            command_display=self._command_display(request.command_definition, request.command_text),
            target_node_id=None,
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
            mode=case.mode,
            case_name=case.name,
            command_key=case.command_key,
            command_display=self._command_display(command_definition),
            target_node_id=None,
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
                mode=request.case.mode,
                case_name=request.case.name,
                command_key=request.case.command_key,
                command_display=self._command_display(request.command_definition, request.command_text),
                target_node_id=None,
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
        self._binary_fit_started_at: float | None = None
        self._text_fit_started_at: float | None = None
        self._latest_binary_fit_report: FirmwareFitReport | None = None
        self._latest_text_fit_report: FirmwareFitReport | None = None
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

    def latest_binary_fit_report(self) -> FirmwareFitReport | None:
        return self._latest_binary_fit_report

    def text_fit_case_definitions(self) -> tuple[FirmwareTestCase, ...]:
        return self._text_fit_workflow.catalog()

    def text_fit_status_snapshot(self) -> FirmwareTextFitSnapshot:
        return self._text_fit_snapshot

    def latest_text_fit_report(self) -> FirmwareFitReport | None:
        return self._latest_text_fit_report

    def latest_fit_report(self, mode: str) -> FirmwareFitReport | None:
        normalized = str(mode).strip().lower()
        if normalized == "binary":
            return self.latest_binary_fit_report()
        if normalized == "text":
            return self.latest_text_fit_report()
        return None

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

        self._binary_fit_started_at = float(self._clock())
        self._latest_binary_fit_report = None
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
        self._send_active_binary_logging_cleanup_once()
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
        self._latest_binary_fit_report = self._assemble_binary_fit_report(status="CANCELLED")
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

        self._text_fit_started_at = float(self._clock())
        self._latest_text_fit_report = None
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
        self._latest_text_fit_report = self._assemble_text_fit_report(status="CANCELLED")
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
            result, verification_request, cleanup_request = self._binary_fit_workflow.handle_matching_response(
                packet,
                received_at=float(self._clock()),
            )
            if cleanup_request is not None:
                self._send_binary_fit_cleanup(cleanup_request)
                return
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

        result, verification_request, cleanup_request = self._text_fit_workflow.handle_matching_response(packet, received_at=float(self._clock()))
        if result is None and verification_request is None and cleanup_request is None:
            return

        self._timeout_timer.stop()
        if cleanup_request is not None:
            self._send_text_fit_cleanup(cleanup_request)
            return

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
            if self._send_active_binary_logging_cleanup_once():
                return
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
                if case.unsupported_reason:
                    unsupported_result = self._binary_fit_workflow.record_unsupported_case(
                        case=case,
                        command_definition=definition,
                        message=str(case.unsupported_reason),
                    )
                    self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
                    self.binary_fit_case_result.emit(unsupported_result)
                    self._record_status(f"Binary FIT case {case.case_id} is unsupported: {unsupported_result.message}")
                    continue
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
                        "execution_policy": case.execution_policy or definition.execution_policy,
                        "support_status": case.support_status or definition.support_status,
                    }
                )
                self._record_status(f"Started Binary FIT case {case.case_id} on Node {request.node_id:02d}.")
                if request.execution_policy in {"NO_RESPONSE", "REBOOT_RECOVERY"}:
                    self._timeout_timer.stop()
                    self._transport_adapter.detach_runtime_window()
                    result = self._binary_fit_workflow.record_no_response_completion(
                        request=request,
                        message=(
                            f"Binary FIT case {case.case_id} completed with reboot recovery policy."
                            if request.execution_policy == "REBOOT_RECOVERY"
                            else f"Binary FIT case {case.case_id} completed with explicit no-response policy."
                        ),
                    )
                    self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
                    self.binary_fit_case_result.emit(result)
                    self._record_status(f"Completed Binary FIT case {result.case_id} with status {result.status}.")
                    continue
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
                if definition.unsupported_reason or case.unsupported_reason:
                    failure_result = self._text_fit_workflow.record_unsupported_case(
                        case=case,
                        command_definition=definition,
                        message=str(case.unsupported_reason or definition.unsupported_reason),
                    )
                    self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
                    self.text_fit_case_result.emit(failure_result)
                    self._record_status(f"Text FIT case {case.case_id} is unsupported: {failure_result.message}")
                    continue
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
                        "command_text": request.command_text,
                        "execution_policy": request.execution_policy,
                        "expected_prefix": request.expected_prefix,
                        "timeout_ms": request.timeout_ms,
                        "tx_hex": self._format_hex(sent_frame),
                    }
                )
                if request.execution_policy == "NO_RESPONSE":
                    self._timeout_timer.stop()
                    self._transport_adapter.detach_runtime_window()
                    result = self._text_fit_workflow.record_no_response_completion(
                        case=case,
                        command_definition=definition,
                        command_text=request.command_text,
                        sent_frame=sent_frame,
                    )
                    self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
                    self.text_fit_case_result.emit(result)
                    self._record_status(f"Completed no-response Text FIT case {case.case_id}.")
                    continue
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

    def _send_text_fit_cleanup(self, cleanup_request: dict[str, object]) -> None:
        try:
            command_name = str(cleanup_request["command_name"])
            cleanup_value = cleanup_request.get("cleanup_value", "0")
            prepared = self._manual_text_workflow.prepare_send(command_name=command_name, value=cleanup_value)
            bridge = self._bridge
            if bridge is None:
                raise ValueError("Firmware Integration runtime bridge is unavailable.")
            sent_started_at = float(self._clock())
            sent_frame = bytes(bridge.send_firmware_text_command(bytearray(prepared.frame)))
            request = self._text_fit_workflow.record_cleanup_sent(sent_frame=sent_frame, sent_started_at=sent_started_at)
            self._timeout_timer.start(request.timeout_ms)
            self._update_text_fit_snapshot(state="waiting_cleanup", overall_status="RUNNING")
            self._record_status(f"Sent Text FIT cleanup for {cleanup_request['case_id']}.")
        except Exception as exc:
            self._transport_adapter.detach_runtime_window()
            current = self._text_fit_workflow.current_request()
            if current is None:
                self._record_status(f"Text FIT cleanup failed: {exc}")
                return
            failure_result = self._text_fit_workflow.record_send_failure(
                case=current.case,
                command_definition=current.command_definition,
                sent_frame=current.sent_frame,
                message=f"Cleanup failed: {exc}",
            )
            self._update_text_fit_snapshot(state="running", overall_status="RUNNING")
            self.text_fit_case_result.emit(failure_result)
            self._record_status(f"Text FIT cleanup failed for {current.case.case_id}: {exc}")
            self._advance_text_fit_run()

    def _send_binary_fit_cleanup(self, cleanup_request: dict[str, object]) -> None:
        try:
            case = cleanup_request["case"]
            definition = cleanup_request["command_definition"]
            if not isinstance(case, FirmwareTestCase) or not isinstance(definition, FirmwareCommandDefinition):
                raise ValueError("Invalid Binary FIT cleanup request.")
            cleanup_value = cleanup_request.get("cleanup_value")
            payload = self._manual_binary_workflow.build_payload(definition, cleanup_value)
            bridge = self._bridge
            if bridge is None:
                raise ValueError("Firmware Integration runtime bridge is unavailable.")
            runtime_window = bridge.get_runtime_window(create_if_missing=True)
            self._transport_adapter.attach_runtime_window(runtime_window)
            sent_started_at = float(self._clock())
            sent_frame = bytes(bridge.send_firmware_binary_command(self._binary_fit_workflow.node_id() or 0, payload))
            request = self._binary_fit_workflow.record_cleanup_sent(
                cleanup_request=cleanup_request,
                payload=payload,
                sent_frame=sent_frame,
                sent_started_at=sent_started_at,
            )
            self._timeout_timer.start(request.timeout_ms)
            self._update_binary_fit_snapshot(state="waiting_cleanup", overall_status="RUNNING")
            self._record_status(f"Sent Binary FIT cleanup for {case.case_id}.")
        except Exception as exc:
            self._transport_adapter.detach_runtime_window()
            current = self._binary_fit_workflow.current_request()
            if current is None:
                self._record_status(f"Binary FIT cleanup failed: {exc}")
                return
            failure_result = self._binary_fit_workflow.record_send_failure(
                case=current.case,
                command_definition=current.command_definition,
                payload=current.sent_payload,
                message=f"Cleanup failed: {exc}",
            )
            self._update_binary_fit_snapshot(state="running", overall_status="RUNNING")
            self.binary_fit_case_result.emit(failure_result)
            self._record_status(f"Binary FIT cleanup failed for {current.case.case_id}: {exc}")
            self._advance_binary_fit_run()

    def _send_active_binary_logging_cleanup_once(self) -> bool:
        request = self._binary_fit_workflow.current_request()
        if request is None:
            return False
        if request.execution_policy != "LOGGING_STREAM" or request.cleanup_pending or request.cleanup_value is None:
            return False
        cleanup_request = {
            "case": request.case,
            "command_definition": request.command_definition,
            "cleanup_value": request.cleanup_value,
            "primary_actual": request.primary_actual,
            "primary_rx_bytes": request.primary_rx_bytes,
            "primary_latency_ms": request.primary_latency_ms,
        }
        self._send_binary_fit_cleanup(cleanup_request)
        return True

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
        self._latest_binary_fit_report = self._assemble_binary_fit_report(status=status)
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
        self._latest_text_fit_report = self._assemble_text_fit_report(status=status)
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

    def _assemble_binary_fit_report(self, *, status: str) -> FirmwareFitReport:
        return self._assemble_fit_report(
            mode="binary",
            started_at=self._binary_fit_started_at,
            completed_at=float(self._clock()),
            status=status,
            selected_case_count=self._binary_fit_workflow.total_cases(),
            completed_case_count=self._binary_fit_workflow.completed_count(),
            target_node_id=self._binary_fit_workflow.node_id(),
            results=self._binary_fit_workflow.results(),
        )

    def _assemble_text_fit_report(self, *, status: str) -> FirmwareFitReport:
        return self._assemble_fit_report(
            mode="text",
            started_at=self._text_fit_started_at,
            completed_at=float(self._clock()),
            status=status,
            selected_case_count=self._text_fit_workflow.total_cases(),
            completed_case_count=self._text_fit_workflow.completed_count(),
            target_node_id=None,
            results=self._text_fit_workflow.results(),
        )

    @classmethod
    def _assemble_fit_report(
        cls,
        *,
        mode: str,
        started_at: float | None,
        completed_at: float,
        status: str,
        selected_case_count: int,
        completed_case_count: int,
        target_node_id: int | None,
        results: tuple[FirmwareTestResult, ...],
    ) -> FirmwareFitReport:
        started_for_id = completed_at if started_at is None else started_at
        duration_ms = None if started_at is None else max(0.0, (completed_at - started_at) * 1000.0)
        cancelled = str(status).upper() == "CANCELLED"
        return FirmwareFitReport(
            run_id=f"{mode}-fit-{started_for_id:.3f}",
            mode=mode,
            started_at=cls._format_report_timestamp(started_at),
            completed_at=cls._format_report_timestamp(completed_at),
            duration_ms=duration_ms,
            overall_status=derive_fit_overall_status(results, cancelled=cancelled),
            selected_case_count=int(selected_case_count),
            completed_case_count=int(completed_case_count),
            target_node_id=target_node_id,
            results=tuple(results),
            passed_count=cls._count_results(results, "PASS"),
            failed_count=cls._count_results(results, "FAIL", "FAILED"),
            timeout_count=cls._count_results(results, "TIMEOUT"),
            error_count=cls._count_results(results, "ERROR"),
            cancelled_count=cls._count_results(results, "CANCELLED"),
        )

    @staticmethod
    def _format_report_timestamp(value: float | None) -> str | None:
        if value is None:
            return None
        return f"{float(value):.3f}"

    @staticmethod
    def _count_results(results: tuple[FirmwareTestResult, ...], *statuses: str) -> int:
        wanted = {status.upper() for status in statuses}
        return sum(1 for result in results if str(result.status).upper() in wanted)

    def _record_status(self, message: str) -> str:
        self._last_action = str(message)
        self.status_changed.emit(self._last_action)
        return self._last_action

    def _clear_active_operation(self) -> None:
        self._active_operation = None
        self._transport_adapter.detach_runtime_window()
        self.pending_state_changed.emit(False)
