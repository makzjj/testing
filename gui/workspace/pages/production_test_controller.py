"""Profile-driven Production test controller for runtime-backed ML 2.0 node checks."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from services.production_test_transport_adapter import ProductionTestTransportAdapter
from ..bridges import WorkspaceRuntimeBridge
from .production_parameter_controller import decode_uuid_response
from .production_test_models import FinalNodeResult, StepResult, TestProfile, TestStep, Tolerance, evaluate_tolerance

PRODUCTION_TEST_TIMEOUT_MS = 3000

CMD_ECHOTEST = 0xCB
CMD_GETVER = 0xC8
CMD_GETPOS = 0x82
CMD_VEL = 0x84
CMD_RUN = 0x88
CMD_INTERRUPT = 0xD8
CMD_STOPMOTOR = 0xDD
CMD_BRAKEMOTOR = 0xDC
CMD_POSITION = 0xEA
CMD_TPOSREL = 0xEB
CMD_TPOS = 0x81
CMD_STARTMOVE = 0xDB
CMD_UUID = 0xE0

PRODUCTION_NODE_TEST_PROFILES: dict[int, dict[str, object]] = {
    3: {"name": "X", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    4: {"name": "Y", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    5: {"name": "V", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    6: {"name": "H", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    7: {"name": "NZ", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    8: {"name": "RZ", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    9: {"name": "PZ", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    10: {"name": "HMI", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    11: {"name": "NGActuator", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
    12: {"name": "Z", "timeout_ms": PRODUCTION_TEST_TIMEOUT_MS},
}


def decode_getver_response(params: list[int]) -> tuple[bool, str | None, str]:
    if len(params) < 4:
        return False, None, "GETVER response payload is too short."
    if int(params[0]) != 0x3A:
        return False, None, "GETVER response param is not 0x3A."
    return True, f"{int(params[1])}.{int(params[2])}.{int(params[3])}", ""


def decode_getpos_response(params: list[int]) -> tuple[bool, int | None, str]:
    if len(params) >= 5 and int(params[0]) == 0x3A:
        params = params[1:5]
    if len(params) < 4:
        return False, None, "GETPOS response payload is too short."
    value = int.from_bytes(bytes([(int(params[0]) & 0xFF), (int(params[1]) & 0xFF), (int(params[2]) & 0xFF), (int(params[3]) & 0xFF)]), byteorder="big", signed=True)
    return True, value, ""


def decode_interrupt_response(params: list[int]) -> tuple[bool, dict[str, int] | None, str]:
    if len(params) < 2:
        return False, None, "INTERRUPT response payload is too short."
    return True, {"int0_status": int(params[0]) & 0xFF, "int1_status": int(params[1]) & 0xFF}, ""


def decode_echotest_response(params: list[int], expected_echo: list[int]) -> tuple[bool, list[int] | None, str]:
    if not params:
        return False, None, "ECHOTEST response payload is empty."
    if params == expected_echo or params[-len(expected_echo) :] == expected_echo:
        return True, list(params), ""
    return False, list(params), "ECHOTEST response does not echo expected payload."


def decode_tpos_state_response(params: list[int]) -> tuple[bool, dict[str, Any] | None, str]:
    if len(params) < 5:
        return False, None, "TPOS response payload is too short."
    state = chr(int(params[0]) & 0xFF)
    position = int.from_bytes(
        bytes([(int(params[1]) & 0xFF), (int(params[2]) & 0xFF), (int(params[3]) & 0xFF), (int(params[4]) & 0xFF)]),
        byteorder="big",
        signed=True,
    )
    if state not in {"S", "E", "N", "L", "R", "Z", "I"}:
        return False, None, f"Unsupported TPOS state '{state}'."
    return True, {"state": state, "position": position}, ""


def build_basic_test_profile(
    node_id: int,
    node_name: str,
    *,
    timeout_ms: int,
    expected_uuid: int | None = None,
) -> TestProfile:
    echo_payload = [0xA5, 0x5A]
    steps: list[TestStep] = [
        TestStep(
            step_id="echo",
            step_name="Communication Echo Test",
            step_type="ECHOTEST",
            command_id=CMD_ECHOTEST,
            command_name="bcmd_ECHOTEST",
            payload=[CMD_ECHOTEST, *echo_payload],
            expected_value=echo_payload,
            tolerance=Tolerance(exact_match=echo_payload),
            timeout_ms=timeout_ms,
            stop_on_fail=True,
            expected_response_command_id=CMD_ECHOTEST,
        ),
        TestStep(
            step_id="getver",
            step_name="Firmware Version Read",
            step_type="GETVER",
            command_id=CMD_GETVER,
            command_name="bcmd_GETVER",
            payload=[CMD_GETVER, 0x3F],
            expected_value=None,
            timeout_ms=timeout_ms,
            stop_on_fail=True,
            expected_response_command_id=CMD_GETVER,
        ),
        TestStep(
            step_id="getpos",
            step_name="Position Read",
            step_type="GETPOS",
            command_id=CMD_GETPOS,
            command_name="bcmd_GETPOS",
            payload=[CMD_GETPOS],
            expected_value=None,
            timeout_ms=timeout_ms,
            stop_on_fail=True,
            expected_response_command_id=CMD_GETPOS,
        ),
        TestStep(
            step_id="interrupt",
            step_name="Interrupt/Sensor Status Read",
            step_type="INTERRUPT",
            command_id=CMD_INTERRUPT,
            command_name="bcmd_INTERRUPT",
            payload=[CMD_INTERRUPT],
            expected_value=None,
            timeout_ms=timeout_ms,
            stop_on_fail=True,
            expected_response_command_id=CMD_INTERRUPT,
        ),
    ]

    if expected_uuid is not None:
        # TODO: The command table marking UUID 0xE0 unsupported for ML2.0 is outdated for current firmware.
        steps.append(
            TestStep(
                step_id="uuid_verify",
                step_name="UUID Verify",
                step_type="UUID_VERIFY",
                command_id=CMD_UUID,
                command_name="bcmd_UUID",
                payload=[CMD_UUID, 0x3F],
                expected_value=expected_uuid,
                tolerance=Tolerance(exact_match=expected_uuid),
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_UUID,
            )
        )

    return TestProfile(
        profile_id=f"basic_ml20_node_{node_id}",
        profile_name="Basic Safe Read Profile",
        node_id=node_id,
        node_name=node_name,
        steps=steps,
    )


def build_safe_movement_profile(
    node_id: int,
    node_name: str,
    *,
    timeout_ms: int,
    move_delta: int = 16,
    safe_velocity: int = 20,
    delta_abs_margin: int = 8,
) -> TestProfile:
    echo_payload = [0xA5, 0x5A]
    safe_velocity = max(1, min(255, int(safe_velocity)))
    vel_hi = (safe_velocity >> 8) & 0xFF
    vel_lo = safe_velocity & 0xFF
    return TestProfile(
        profile_id=f"movement_ml20_node_{node_id}",
        profile_name="Safe Movement Profile",
        node_id=node_id,
        node_name=node_name,
        steps=[
            TestStep(
                step_id="echo",
                step_name="Communication Echo Test",
                step_type="ECHOTEST",
                command_id=CMD_ECHOTEST,
                command_name="bcmd_ECHOTEST",
                payload=[CMD_ECHOTEST, *echo_payload],
                expected_value=echo_payload,
                tolerance=Tolerance(exact_match=echo_payload),
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_ECHOTEST,
            ),
            TestStep(
                step_id="getver",
                step_name="Firmware Version Read",
                step_type="GETVER",
                command_id=CMD_GETVER,
                command_name="bcmd_GETVER",
                payload=[CMD_GETVER, 0x3F],
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_GETVER,
            ),
            TestStep(
                step_id="read_initial_position",
                step_name="Read Initial Position",
                step_type="READ_INITIAL_POSITION",
                command_id=CMD_GETPOS,
                command_name="bcmd_GETPOS",
                payload=[CMD_GETPOS],
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_GETPOS,
            ),
            TestStep(
                step_id="interrupt_initial",
                step_name="Read Initial Interrupt/Sensor Status",
                step_type="INTERRUPT",
                command_id=CMD_INTERRUPT,
                command_name="bcmd_INTERRUPT",
                payload=[CMD_INTERRUPT],
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_INTERRUPT,
            ),
            TestStep(
                step_id="set_safe_velocity",
                step_name="Set Safe Velocity",
                step_type="SET_SAFE_VELOCITY",
                command_id=CMD_VEL,
                command_name="bcmd_VEL",
                payload=[CMD_VEL, vel_hi, vel_lo],
                expected_value=safe_velocity,
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=None,
                send_command=True,
                wait_for_response=False,
            ),
            TestStep(
                step_id="move_to_position",
                step_name="Movement Started",
                step_type="MOVE_TO_POSITION",
                command_id=CMD_TPOS,
                command_name="bcmd_TPOS",
                payload=[CMD_TPOS, 0x00, 0x00, 0x00, 0x00],
                expected_value=move_delta,
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=None,
                send_command=True,
                wait_for_response=False,
            ),
            TestStep(
                step_id="wait_move_end",
                step_name="Movement Ended",
                step_type="WAIT_FOR_MOVE_END",
                command_id=None,
                command_name="WAIT_FOR_MOVE_END",
                payload=[],
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_TPOS,
                send_command=False,
                wait_for_response=True,
            ),
            TestStep(
                step_id="read_final_position",
                step_name="Read Final Position",
                step_type="READ_FINAL_POSITION",
                command_id=CMD_GETPOS,
                command_name="bcmd_GETPOS",
                payload=[CMD_GETPOS],
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=CMD_GETPOS,
            ),
            TestStep(
                step_id="verify_position_delta",
                step_name="Position Verification",
                step_type="VERIFY_POSITION_DELTA",
                command_id=None,
                command_name="VERIFY_POSITION_DELTA",
                payload=[],
                expected_value=move_delta,
                tolerance=Tolerance(abs_margin=float(delta_abs_margin)),
                timeout_ms=timeout_ms,
                stop_on_fail=True,
                expected_response_command_id=None,
                send_command=False,
                wait_for_response=False,
            ),
        ],
    )


class ProductionTestController(QObject):
    """Runs one Production-side profile-driven node test at a time."""

    log_message = pyqtSignal(str)
    test_started = pyqtSignal(int, str)
    test_passed = pyqtSignal(int, str, str)
    test_failed = pyqtSignal(int, str, str)
    test_unsupported = pyqtSignal(int, str, str)
    test_aborted = pyqtSignal(int, str, str)
    profile_started = pyqtSignal(int, str, object)
    step_finished = pyqtSignal(int, str, object)
    profile_finished = pyqtSignal(object)

    def __init__(self, bridge: WorkspaceRuntimeBridge, timeout_ms: int | None = None) -> None:
        super().__init__()
        self._bridge = bridge
        self._timeout_override_ms = timeout_ms
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._handle_timeout)
        self._runtime_window = None
        self._transport_adapter = ProductionTestTransportAdapter(self)
        self._active_profile: TestProfile | None = None
        self._active_step_index = 0
        self._active_step: TestStep | None = None
        self._step_results: list[StepResult] = []
        self._last_actual_value: str = ""
        self._last_raw_response_hex: str = ""
        self._last_final_result: FinalNodeResult | None = None
        self._step_actual_by_id: dict[str, Any] = {}

    def is_active(self) -> bool:
        return self._active_profile is not None

    @property
    def last_actual_value(self) -> str:
        return self._last_actual_value

    @property
    def last_raw_response_hex(self) -> str:
        return self._last_raw_response_hex

    @property
    def last_final_result(self) -> FinalNodeResult | None:
        return self._last_final_result

    def run_test(
        self,
        node_id: int,
        node_name: str,
        *,
        expected_uuid: int | None = None,
        profile_mode: str = "basic",
    ) -> bool:
        self.abort_test(emit_signal=False)
        self._last_actual_value = ""
        self._last_raw_response_hex = ""
        self._last_final_result = None

        runtime_window = self._bridge.get_runtime_window(create_if_missing=True)
        if runtime_window is None:
            reason = "Runtime backend is unavailable for Production testing."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            reason = "Serial port not connected."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        if not hasattr(runtime_window, "packet_received"):
            reason = "Runtime packet listener is unavailable."
            self.log_message.emit(f"[Production] {reason}")
            self.test_failed.emit(node_id, node_name, reason)
            return False

        profile_entry = PRODUCTION_NODE_TEST_PROFILES.get(node_id)
        if profile_entry is None:
            reason = "No safe Production test profile is available for this node yet."
            self.log_message.emit(f"[Production] {reason}")
            self.test_unsupported.emit(node_id, node_name, reason)
            return False

        profile_timeout = int(profile_entry.get("timeout_ms", PRODUCTION_TEST_TIMEOUT_MS))
        if self._timeout_override_ms is not None:
            profile_timeout = self._timeout_override_ms
        if profile_mode == "movement":
            profile = build_safe_movement_profile(node_id, node_name, timeout_ms=profile_timeout)
        else:
            profile = build_basic_test_profile(node_id, node_name, timeout_ms=profile_timeout, expected_uuid=expected_uuid)

        self._attach_runtime_window(runtime_window)
        self._active_profile = profile
        self._active_step_index = 0
        self._active_step = None
        self._step_results = []
        self._step_actual_by_id = {}
        self.test_started.emit(node_id, node_name)
        self.profile_started.emit(node_id, node_name, [step.step_name for step in profile.steps])
        self.log_message.emit(f"[Production] Started profile {profile.profile_name} for Node {node_id} {node_name}")
        self._run_next_step()
        return True

    def abort_test(self, *, emit_signal: bool = True) -> bool:
        profile = self._active_profile
        if profile is None:
            if emit_signal:
                self.log_message.emit("[Production] No active test to abort")
            return False

        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is not None and backend_client.is_connected():
            try:
                backend_client.send_stop_motor(profile.node_id)
                self.log_message.emit(f"[Production] Sent stop command to Node {profile.node_id} {profile.node_name}")
            except Exception as exc:
                self.log_message.emit(
                    f"[Production] Failed to send stop command to Node {profile.node_id} {profile.node_name}: {exc}"
                )

        if self._active_step is not None:
            self._emit_step_result("ABORTED", actual_value="", failure_reason="Operator stopped the Production test.")
        self._finalize_profile("ABORTED", "Operator stopped the Production test.", emit_terminal_signal=emit_signal)
        return True

    def _attach_runtime_window(self, runtime_window) -> None:
        if runtime_window is self._runtime_window:
            return

        self._transport_adapter.detach_runtime_window()
        self._transport_adapter.attach_runtime_window(runtime_window)
        self._runtime_window = runtime_window

    def accepts_workflow_packet(
        self,
        decoded_kind: str | None,
        decoded_value: object,
        *,
        sender: int | None,
        cmd: int,
        params: list[int],
    ) -> bool:
        profile = self._active_profile
        step = self._active_step
        if profile is None or step is None:
            return False
        if sender is None or int(sender) != profile.node_id:
            return False
        expected_command = step.expected_response_command_id
        if expected_command is None:
            return False
        if int(cmd) != int(expected_command):
            return False

        # Relevance filtering stays deliberately narrow here. The adapter owns
        # only step-family filtering; semantic validation and pass/fail remain
        # controller-owned so invalid expected responses still fail locally.
        _ = decoded_kind, decoded_value, params
        return True

    def _run_next_step(self) -> None:
        profile = self._active_profile
        if profile is None:
            return
        if self._active_step_index >= len(profile.steps):
            self._finalize_profile("PASS", f"All profile steps passed for Node {profile.node_id} {profile.node_name}.")
            return

        step = profile.steps[self._active_step_index]
        self._active_step = step
        runtime_window = self._runtime_window
        backend_client = getattr(runtime_window, "backend_client", None) if runtime_window is not None else None
        if backend_client is None or not backend_client.is_connected():
            self._emit_step_result("FAIL", actual_value="", failure_reason="Serial port not connected.")
            self._finalize_profile("FAIL", "Serial port not connected.")
            return

        self.log_message.emit(f"[Production] Running step {self._active_step_index + 1}/{len(profile.steps)}: {step.step_name}")
        payload = self._resolve_step_payload(step)
        if payload is None:
            self._emit_step_result("FAIL", actual_value="", failure_reason="Failed to resolve dynamic step payload.")
            self._handle_step_terminal_result("FAIL", "Failed to resolve dynamic step payload.")
            return
        if not step.send_command:
            if not step.wait_for_response:
                self._finalize_no_response_step(step, payload)
                return
            self._timeout_timer.start(int(step.timeout_ms))
            return
        try:
            backend_client.send_command_bytes(profile.node_id, payload)
        except Exception as exc:
            self._emit_step_result("FAIL", actual_value="", failure_reason=f"Failed to send step command: {exc}")
            self._handle_step_terminal_result("FAIL", f"Failed to send step command: {exc}")
            return

        payload_text = " ".join(f"{byte:02X}" for byte in payload)
        self.log_message.emit(f"[Production] TX[{step.command_name}] -> Node {profile.node_id:02d}: {payload_text}")
        if not step.wait_for_response:
            self._finalize_no_response_step(step, payload)
            return
        self._timeout_timer.start(int(step.timeout_ms))

    def handle_runtime_packet(self, packet: object) -> None:
        profile = self._active_profile
        step = self._active_step
        if profile is None or step is None:
            return
        if not isinstance(packet, dict):
            return
        if packet.get("status") != "ok" or packet.get("type") != "can_over_uart":
            return
        sender = int(packet.get("sender", -1))
        if sender != profile.node_id:
            return

        command = int(packet.get("cmd", -1))
        if step.expected_response_command_id is not None and command != int(step.expected_response_command_id):
            return
        params = [int(value) & 0xFF for value in list(packet.get("params", [])) if isinstance(value, int)]
        raw_response_hex = self._extract_raw_response_hex(command, params)

        decoded_ok, actual_value, decode_error = self._decode_step_response(step, command, params)
        if not decoded_ok:
            self._timeout_timer.stop()
            self._emit_step_result("FAIL", actual_value=actual_value, failure_reason=decode_error, raw_response_hex=raw_response_hex)
            self._handle_step_terminal_result("FAIL", decode_error)
            return

        if step.step_type == "WAIT_FOR_MOVE_END":
            state = actual_value.get("state") if isinstance(actual_value, dict) else None
            if state in {"S", "I"}:
                return
            if state in {"L", "R"}:
                self._timeout_timer.stop()
                reason = f"Unexpected sensor-hit state '{state}' during movement."
                self._emit_step_result("FAIL", actual_value=actual_value, failure_reason=reason, raw_response_hex=raw_response_hex)
                self._handle_step_terminal_result("FAIL", reason)
                return
        compare_ok, compare_error = self._compare_step_result(step, actual_value)
        self._timeout_timer.stop()
        if compare_ok:
            self._emit_step_result("PASS", actual_value=actual_value, failure_reason="", raw_response_hex=raw_response_hex)
            self._active_step_index += 1
            self._active_step = None
            self._run_next_step()
            return

        self._emit_step_result("FAIL", actual_value=actual_value, failure_reason=compare_error, raw_response_hex=raw_response_hex)
        self._handle_step_terminal_result("FAIL", compare_error)

    def _handle_timeout(self) -> None:
        step = self._active_step
        if step is None:
            return
        reason = f"Timed out waiting for step response: {step.step_name}."
        self._emit_step_result("TIMEOUT", actual_value="", failure_reason=reason)
        if self._is_movement_profile():
            self._send_safe_stop_motor()
        self._handle_step_terminal_result("TIMEOUT", reason)

    def _handle_step_terminal_result(self, result: str, reason: str) -> None:
        step = self._active_step
        if step is None:
            return
        stop_on_fail = bool(step.stop_on_fail)
        self._active_step_index += 1
        self._active_step = None
        if result == "PASS":
            self._run_next_step()
            return
        if not stop_on_fail:
            self._run_next_step()
            return
        if result == "TIMEOUT":
            self._finalize_profile("TIMEOUT", reason)
            return
        if self._is_movement_profile():
            self._send_safe_stop_motor()
        self._finalize_profile("FAIL", reason)

    def _decode_step_response(self, step: TestStep, command: int, params: list[int]) -> tuple[bool, Any, str]:
        if step.step_type == "ECHOTEST":
            expected_echo = [int(value) & 0xFF for value in (step.expected_value or [])]
            return decode_echotest_response(params, expected_echo)
        if step.step_type == "GETVER":
            return decode_getver_response(params)
        if step.step_type == "GETPOS":
            return decode_getpos_response(params)
        if step.step_type == "READ_INITIAL_POSITION":
            return decode_getpos_response(params)
        if step.step_type == "READ_FINAL_POSITION":
            return decode_getpos_response(params)
        if step.step_type == "INTERRUPT":
            return decode_interrupt_response(params)
        if step.step_type == "UUID_VERIFY":
            decoded_ok, actual_uuid, error = decode_uuid_response([command, *params])
            return decoded_ok, actual_uuid, error
        if step.step_type == "WAIT_FOR_MOVE_END":
            return decode_tpos_state_response(params)
        return True, params, ""

    def _compare_step_result(self, step: TestStep, actual_value: Any) -> tuple[bool, str]:
        if step.expected_value is None and step.tolerance is None:
            return True, ""
        if step.step_type == "VERIFY_POSITION_DELTA":
            initial = self._step_actual_by_id.get("read_initial_position")
            final = self._step_actual_by_id.get("read_final_position")
            if initial is None or final is None:
                return False, "Missing initial/final position required for delta verification."
            actual_delta = int(final) - int(initial)
            compare_ok, compare_error = evaluate_tolerance(step.expected_value, actual_delta, step.tolerance)
            if compare_ok:
                return True, ""
            return False, f"{compare_error} (delta={actual_delta}, initial={initial}, final={final})"
        return evaluate_tolerance(step.expected_value, actual_value, step.tolerance)

    def _emit_step_result(
        self,
        result: str,
        *,
        actual_value: Any,
        failure_reason: str,
        raw_response_hex: str = "",
    ) -> None:
        profile = self._active_profile
        step = self._active_step
        if profile is None or step is None:
            return
        step_result = StepResult(
            step_id=step.step_id,
            step_name=step.step_name,
            expected_value=step.expected_value,
            actual_value=actual_value,
            result=result,
            failure_reason=failure_reason,
            raw_response_hex=raw_response_hex,
        )
        self._step_results.append(step_result)
        self._step_actual_by_id[step.step_id] = actual_value
        self._last_actual_value = "" if actual_value is None else str(actual_value)
        self._last_raw_response_hex = raw_response_hex
        self.step_finished.emit(profile.node_id, profile.node_name, step_result)
        if failure_reason:
            self.log_message.emit(f"[Production] {step.step_name}: {result} ({failure_reason})")
        else:
            self.log_message.emit(f"[Production] {step.step_name}: {result}")

    def _finalize_profile(self, final_result: str, failure_reason: str, *, emit_terminal_signal: bool = True) -> None:
        profile = self._active_profile
        if profile is None:
            return
        self._timeout_timer.stop()
        final_node_result = FinalNodeResult(
            node_id=profile.node_id,
            node_name=profile.node_name,
            profile_id=profile.profile_id,
            final_result=final_result,
            failure_reason=failure_reason,
            step_results=list(self._step_results),
        )
        self._last_final_result = final_node_result
        self.profile_finished.emit(final_node_result)
        self._clear_active_state()
        if not emit_terminal_signal:
            return
        if final_result == "PASS":
            self.test_passed.emit(profile.node_id, profile.node_name, failure_reason)
            return
        if final_result == "ABORTED":
            self.test_aborted.emit(profile.node_id, profile.node_name, failure_reason)
            self.log_message.emit("[Production] Test aborted")
            return
        self.test_failed.emit(profile.node_id, profile.node_name, failure_reason)

    def _clear_active_state(self) -> None:
        self._active_profile = None
        self._active_step_index = 0
        self._active_step = None
        self._step_results = []
        self._step_actual_by_id = {}

    def _extract_raw_response_hex(self, command: int, params: list[int]) -> str:
        values = [command & 0xFF, *[(int(value) & 0xFF) for value in params]]
        return " ".join(f"{value:02X}" for value in values)

    def _resolve_step_payload(self, step: TestStep) -> list[int] | None:
        if step.step_type != "MOVE_TO_POSITION":
            return list(step.payload)
        initial_position = self._step_actual_by_id.get("read_initial_position")
        if initial_position is None:
            return None
        target = int(initial_position) + int(step.expected_value or 0)
        target_bytes = int(target).to_bytes(4, byteorder="big", signed=True)
        return [CMD_TPOS, *list(target_bytes)]

    def _finalize_no_response_step(self, step: TestStep, payload: list[int]) -> None:
        if step.step_type == "VERIFY_POSITION_DELTA":
            initial = self._step_actual_by_id.get("read_initial_position")
            final = self._step_actual_by_id.get("read_final_position")
            if initial is None or final is None:
                self._emit_step_result("FAIL", actual_value="", failure_reason="Missing initial/final position for verification.")
                self._handle_step_terminal_result("FAIL", "Missing initial/final position for verification.")
                return
            actual_delta = int(final) - int(initial)
            compare_ok, compare_error = self._compare_step_result(step, actual_delta)
            self._emit_step_result(
                "PASS" if compare_ok else "FAIL",
                actual_value=f"delta={actual_delta}; initial={initial}; final={final}",
                failure_reason="" if compare_ok else compare_error,
                raw_response_hex=" ".join(f"{byte:02X}" for byte in payload),
            )
            if compare_ok:
                self._active_step_index += 1
                self._active_step = None
                self._run_next_step()
                return
            self._handle_step_terminal_result("FAIL", compare_error)
            return

        actual_value: Any = ""
        if step.step_type == "SET_SAFE_VELOCITY":
            actual_value = step.expected_value
        if step.step_type == "MOVE_TO_POSITION":
            initial = self._step_actual_by_id.get("read_initial_position")
            delta = int(step.expected_value or 0)
            target = int(initial) + delta if initial is not None else None
            actual_value = {"initial_position": initial, "target_position": target, "delta": delta}
        if step.step_type == "STOP_MOTOR":
            actual_value = "STOP_SENT"
        self._emit_step_result(
            "PASS",
            actual_value=actual_value,
            failure_reason="",
            raw_response_hex=" ".join(f"{byte:02X}" for byte in payload),
        )
        self._active_step_index += 1
        self._active_step = None
        self._run_next_step()

    def _send_safe_stop_motor(self) -> None:
        profile = self._active_profile
        runtime_window = self._runtime_window
        if profile is None or runtime_window is None:
            return
        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not backend_client.is_connected():
            return
        try:
            backend_client.send_stop_motor(profile.node_id)
            self.log_message.emit(f"[Production] Sent stop command to Node {profile.node_id} {profile.node_name}")
        except Exception as exc:
            self.log_message.emit(f"[Production] Failed to send stop command to Node {profile.node_id} {profile.node_name}: {exc}")

    def _is_movement_profile(self) -> bool:
        profile = self._active_profile
        if profile is None:
            return False
        return profile.profile_id.startswith("movement_")
