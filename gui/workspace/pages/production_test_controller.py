"""Profile-driven Production test controller for runtime-backed ML 2.0 node checks."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from ..bridges import WorkspaceRuntimeBridge
from .production_parameter_controller import decode_uuid_response
from .production_test_models import FinalNodeResult, StepResult, TestProfile, TestStep, Tolerance, evaluate_tolerance

PRODUCTION_TEST_TIMEOUT_MS = 3000

CMD_ECHOTEST = 0xCB
CMD_GETVER = 0xC8
CMD_GETPOS = 0x82
CMD_INTERRUPT = 0xD8
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
    if len(params) < 4:
        return False, None, "GETPOS response payload is too short."
    value = ((int(params[0]) & 0xFF) << 24) | ((int(params[1]) & 0xFF) << 16) | ((int(params[2]) & 0xFF) << 8) | (
        int(params[3]) & 0xFF
    )
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
        self._active_profile: TestProfile | None = None
        self._active_step_index = 0
        self._active_step: TestStep | None = None
        self._step_results: list[StepResult] = []
        self._last_actual_value: str = ""
        self._last_raw_response_hex: str = ""
        self._last_final_result: FinalNodeResult | None = None

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

    def run_test(self, node_id: int, node_name: str, *, expected_uuid: int | None = None) -> bool:
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
        profile = build_basic_test_profile(node_id, node_name, timeout_ms=profile_timeout, expected_uuid=expected_uuid)

        self._attach_runtime_window(runtime_window)
        self._active_profile = profile
        self._active_step_index = 0
        self._active_step = None
        self._step_results = []
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

        if self._runtime_window is not None and hasattr(self._runtime_window, "packet_received"):
            try:
                self._runtime_window.packet_received.disconnect(self._handle_runtime_packet)
            except (TypeError, RuntimeError):
                pass

        runtime_window.packet_received.connect(self._handle_runtime_packet)
        self._runtime_window = runtime_window

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
        try:
            backend_client.send_command_bytes(profile.node_id, list(step.payload))
        except Exception as exc:
            self._emit_step_result("FAIL", actual_value="", failure_reason=f"Failed to send step command: {exc}")
            self._handle_step_terminal_result("FAIL", f"Failed to send step command: {exc}")
            return

        payload_text = " ".join(f"{byte:02X}" for byte in step.payload)
        self.log_message.emit(f"[Production] TX[{step.command_name}] -> Node {profile.node_id:02d}: {payload_text}")
        self._timeout_timer.start(int(step.timeout_ms))

    def _handle_runtime_packet(self, packet: object) -> None:
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
        self._finalize_profile("FAIL", reason)

    def _decode_step_response(self, step: TestStep, command: int, params: list[int]) -> tuple[bool, Any, str]:
        if step.step_type == "ECHOTEST":
            expected_echo = [int(value) & 0xFF for value in (step.expected_value or [])]
            return decode_echotest_response(params, expected_echo)
        if step.step_type == "GETVER":
            return decode_getver_response(params)
        if step.step_type == "GETPOS":
            return decode_getpos_response(params)
        if step.step_type == "INTERRUPT":
            return decode_interrupt_response(params)
        if step.step_type == "UUID_VERIFY":
            decoded_ok, actual_uuid, error = decode_uuid_response([command, *params])
            return decoded_ok, actual_uuid, error
        return True, params, ""

    def _compare_step_result(self, step: TestStep, actual_value: Any) -> tuple[bool, str]:
        if step.expected_value is None and step.tolerance is None:
            return True, ""
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

    def _extract_raw_response_hex(self, command: int, params: list[int]) -> str:
        values = [command & 0xFF, *[(int(value) & 0xFF) for value in params]]
        return " ".join(f"{value:02X}" for value in values)
