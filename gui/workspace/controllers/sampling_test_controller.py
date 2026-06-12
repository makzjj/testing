"""Sampling Test controller/state machine for IPQC workbook capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import time

from data.binary_cmd_builders import build_getpos, build_run, build_stopmotor, build_tpos, build_vel
from data.binary_cmd_parser import decode_command
from services.ipqc_excel_adapter import IpqcExcelAdapter, SamplingWorkbookLayout


@dataclass(frozen=True)
class SamplingTestConfig:
    home_velocity: int = -190
    pwm_values: tuple[int, ...] = (100, 90, 80, 70, 60)
    samples_per_direction: int = 32


@dataclass(frozen=True)
class SamplingMeasurementResult:
    pwm: int
    sample_index: int
    direction: str
    range_value: int
    elapsed_seconds: float
    speed: float
    start_l_pos: int
    r_pos: int | None = None
    l_pos: int | None = None
    return_error: int | None = None
    workbook_cells: dict[str, str] = field(default_factory=dict)


class SamplingTestController:
    """State machine that drives sampling motion and writes workbook results."""

    S_IDLE = "IDLE"
    S_HOME_WAIT_VEL_ACK = "HOME_WAIT_VEL_ACK"
    S_HOME_WAIT_TPOS = "HOME_WAIT_TPOS"
    S_HOME_WAIT_SENSOR = "HOME_WAIT_L_SENSOR"
    S_HOME_WAIT_GETPOS = "HOME_WAIT_GETPOS"
    S_SAMPLE_WAIT_ACK = "SAMPLE_WAIT_RUN_ACK"
    S_SAMPLE_WAIT_SENSOR = "SAMPLE_WAIT_SENSOR"
    S_SAMPLE_WAIT_GETPOS = "SAMPLE_WAIT_GETPOS"
    S_WAIT_MIDDLE_TPOS = "WAIT_FOR_MIDDLE_TPOS"
    S_FAILED = "FAILED"
    S_ABORTED = "ABORTED"
    S_COMPLETED = "COMPLETED"

    def __init__(
        self,
        workbook_adapter: IpqcExcelAdapter,
        config: SamplingTestConfig | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._adapter = workbook_adapter
        self._config = config or SamplingTestConfig()
        self._clock = clock or time.monotonic
        self._node_id: int | None = None
        self._node_name: str | None = None
        self._base_group: str | None = None
        self._layout: SamplingWorkbookLayout | None = None
        self._running = False
        self._state = self.S_IDLE
        self._wait_for: str | None = None
        self._expected_response_description = ""
        self._run_pwm_values: tuple[int, ...] = tuple(self._config.pwm_values)
        self._run_samples_per_pwm = int(self._config.samples_per_direction)
        self._current_pwm_index = -1
        self._current_pwm = 0
        self._current_sample_index = 0
        self._current_direction = ""
        self._completed_measurements = 0
        self._total_measurements = len(self._run_pwm_values) * self._run_samples_per_pwm * 2
        self._start_l_pos: int | None = None
        self._current_r_pos: int | None = None
        self._current_l_pos: int | None = None
        self._pending_ack_velocity: int | None = None
        self._pending_ack_time: float | None = None
        self._pending_sensor_time: float | None = None
        self._middle_target: int | None = None
        self._latest_result: SamplingMeasurementResult | None = None
        self._stop_command_sent = False

    @property
    def last_result(self) -> SamplingMeasurementResult | None:
        return self._latest_result

    def is_active(self) -> bool:
        return self._running

    @property
    def node_id(self) -> int | None:
        return self._node_id

    @property
    def node_name(self) -> str | None:
        return self._node_name

    @property
    def base_group(self) -> str | None:
        return self._base_group

    @property
    def sheet_name(self) -> str | None:
        return self._layout.sheet_name if self._layout is not None else None

    @property
    def state(self) -> str:
        return self._state

    @property
    def current_pwm(self) -> int:
        return self._current_pwm

    @property
    def current_direction(self) -> str:
        return self._current_direction

    @property
    def current_sample_index(self) -> int:
        return self._current_sample_index

    @property
    def completed_measurements(self) -> int:
        return self._completed_measurements

    @property
    def total_measurements(self) -> int:
        return self._total_measurements

    @property
    def samples_per_direction(self) -> int:
        return int(self._run_samples_per_pwm)

    @property
    def pwm_values(self) -> tuple[int, ...]:
        return tuple(self._run_pwm_values)

    @property
    def samples_per_pwm(self) -> int:
        return int(self._run_samples_per_pwm)

    # Signal-like hooks
    def command_requested(self, payload: list[int]) -> None:  # pragma: no cover - overridden in tests
        pass

    def log_message(self, text: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def packet_message(self, text: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def state_changed(self, text: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def status_changed(self, text: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def current_pwm_changed(self, pwm: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def current_direction_changed(self, direction: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def current_sample_changed(self, sample_index: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def samples_completed_changed(self, completed: int, total: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def latest_measurement_changed(self, range_value: int, elapsed_seconds: float, speed: float) -> None:  # pragma: no cover - overridden in tests
        pass

    def latest_workbook_cell_written(self, cell_ref: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def measurement_completed(self, result: SamplingMeasurementResult) -> None:  # pragma: no cover - overridden in tests
        pass

    def sampling_completed(self) -> None:  # pragma: no cover - overridden in tests
        pass

    def sampling_failed(self, reason: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def sampling_aborted(self, reason: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def start(
        self,
        node_id: int,
        node_name: str | None = None,
        *,
        single_axis_passed: bool = True,
        base_group: str | None = None,
        pwm_values: list[int] | tuple[int, ...] | None = None,
        samples_per_pwm: int | None = None,
    ) -> bool:
        if self._running:
            self.log_message("[Sampling] Sampling is already active.")
            return False
        if not single_axis_passed:
            reason = "Sampling requires the Single Axis Functional Test to pass first."
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False
        if not self._adapter.has_loaded_workbook():
            reason = "No IPQC workbook is loaded."
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False

        self._node_id = int(node_id)
        self._node_name = node_name
        self._base_group = base_group or self._adapter.active_sheet_group
        if not self._base_group:
            reason = "No active IPQC workbook sheet group is selected."
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False

        try:
            self._layout = self._adapter.discover_sampling_layout(self._base_group)
        except Exception as exc:
            reason = f"Sampling workbook layout is invalid: {exc}"
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False

        run_pwm_values = tuple(int(value) for value in (pwm_values if pwm_values is not None else self._config.pwm_values))
        if not run_pwm_values:
            reason = "No PWM values are configured for Sampling."
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False

        run_samples_per_pwm = int(samples_per_pwm if samples_per_pwm is not None else self._config.samples_per_direction)
        if run_samples_per_pwm <= 0:
            reason = "Sampling requires at least one sample per PWM."
            self.log_message(f"[Sampling] {reason}")
            self.sampling_failed(reason)
            return False

        self._run_pwm_values = run_pwm_values
        self._run_samples_per_pwm = run_samples_per_pwm

        self._reset_runtime_state()
        self._running = True
        self._state = self.S_HOME_WAIT_VEL_ACK
        self.state_changed(self._state)
        self.status_changed("Sampling started")
        self.log_message(
            f"Sampling started: pwm_values={list(self._run_pwm_values)}, samples_per_pwm={self._run_samples_per_pwm}"
        )
        self._current_direction = "HOME"
        self.current_direction_changed(self._current_direction)
        self._expected_response_description = "VEL ACK for home startup"
        self._wait_for = "vel_ack"
        self.status_changed("Setting home velocity")
        self.command_requested(build_vel(80))
        return True

    def stop(self) -> bool:
        return self.abort_by_user()

    def abort_by_user(self) -> bool:
        if not self._running:
            return False
        reason = "Sampling aborted by user."
        self._send_stopmotor()
        self._running = False
        self._wait_for = None
        self._state = self.S_ABORTED
        self.state_changed(self._state)
        self.status_changed(reason)
        self.log_message("Sampling aborted")
        self.sampling_aborted(reason)
        return True

    def on_timeout(self) -> None:
        if not self._running:
            return
        reason = f"Timed out waiting for {self._expected_response_description or 'sampling response'}."
        self._fail_with_stop(reason)

    def handle_runtime_packet(self, packet: list[int] | bytes | bytearray | dict[str, Any]) -> None:
        if not self._running or self._state in (self.S_FAILED, self.S_ABORTED, self.S_COMPLETED):
            return

        packet_data = self._coerce_packet(packet)
        if packet_data is None:
            return

        sender = packet_data["sender"]
        if self._node_id is not None and sender is not None and int(sender) != int(self._node_id):
            return

        packet_node = sender if sender is not None else self._node_id
        self.packet_message(f"[RX] Node {packet_node if packet_node is not None else '?'}: {packet_data['raw_hex']}")

        cmd = packet_data["cmd"]
        params = packet_data["params"]
        decoded_kind, decoded_value = decode_command(cmd, params)

        if decoded_kind is None:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    packet_data["raw_hex"], self._expected_response_description or "sampling response"
                )
            )
            return

        if decoded_kind == "velocity_ack":
            self._handle_velocity_ack(decoded_value)
            return
        if decoded_kind == "run_started":
            self._handle_run_started(decoded_value)
            return
        if decoded_kind == "tpos_status":
            self._handle_tpos_status(decoded_value)
            return
        if decoded_kind == "getpos":
            self._handle_getpos(decoded_value)
            return

        self._fail_with_stop(
            self._build_unexpected_packet_reason(
                packet_data["raw_hex"], self._expected_response_description or "sampling response"
            )
        )

    def _reset_runtime_state(self) -> None:
        self._wait_for = None
        self._expected_response_description = ""
        self._current_pwm_index = -1
        self._current_pwm = 0
        self._current_sample_index = 0
        self._current_direction = ""
        self._completed_measurements = 0
        self._start_l_pos = None
        self._current_r_pos = None
        self._current_l_pos = None
        self._pending_ack_velocity = None
        self._pending_ack_time = None
        self._pending_sensor_time = None
        self._middle_target = None
        self._latest_result = None
        self._total_measurements = len(self._run_pwm_values) * self._run_samples_per_pwm * 2
        self._stop_command_sent = False

    def _send_stopmotor(self) -> None:
        if self._stop_command_sent:
            return
        try:
            self.command_requested(build_stopmotor())
            self._stop_command_sent = True
        except Exception as exc:  # pragma: no cover - defensive
            self.log_message(f"[Sampling] Failed to send stop motor command: {exc}")

    def _set_state(self, state: str) -> None:
        self._state = state
        self.state_changed(state)

    def _next_pwm(self) -> bool:
        self._current_pwm_index += 1
        if self._current_pwm_index >= len(self._run_pwm_values):
            return False
        self._current_pwm = int(self._run_pwm_values[self._current_pwm_index])
        self._current_sample_index = 1
        self.current_pwm_changed(self._current_pwm)
        self.current_sample_changed(self._current_sample_index)
        return True

    def _start_next_sample_pair(self) -> None:
        if self._current_pwm_index < 0 and not self._next_pwm():
            self._complete()
            return
        self._current_direction = "+"
        self.current_direction_changed(self._current_direction)
        self._pending_ack_velocity = int(self._current_pwm)
        self._expected_response_description = self._format_run_ack_description(self._current_pwm)
        self._set_state(self.S_SAMPLE_WAIT_ACK)
        self._wait_for = "run_started"
        self.command_requested(build_run(self._current_pwm))

    def _start_negative_leg(self) -> None:
        self._current_direction = "-"
        self.current_direction_changed(self._current_direction)
        self._pending_ack_velocity = -int(self._current_pwm)
        self._expected_response_description = self._format_run_ack_description(-self._current_pwm)
        self._set_state(self.S_SAMPLE_WAIT_ACK)
        self._wait_for = "run_started"
        self.command_requested(build_run(-self._current_pwm))

    def _complete(self) -> None:
        self._running = False
        self._wait_for = None
        self._set_state(self.S_COMPLETED)
        self.status_changed("Sampling completed")
        self.log_message("Sampling completed")
        self.sampling_completed()

    def _fail_with_stop(self, reason: str) -> None:
        if not self._running:
            return
        self._send_stopmotor()
        self._running = False
        self._wait_for = None
        self._set_state(self.S_FAILED)
        self.status_changed(reason)
        self.log_message(f"Sampling failed: {reason}")
        self.sampling_failed(reason)

    def _handle_run_started(self, value: object) -> None:
        if self._wait_for != "run_started":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "RUN ACK", self._expected_response_description or "RUN ACK"
                )
            )
            return
        if value is None:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "RUN ACK", self._expected_response_description or "RUN ACK"
                )
            )
            return
        if self._pending_ack_velocity is not None and int(value) != int(self._pending_ack_velocity):
            reason = (
                f"Unexpected RUN ACK velocity {value}; expected {self._pending_ack_velocity}. "
                f"Current PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}."
            )
            self._fail_with_stop(reason)
            return

        self._pending_ack_time = self._clock()
        self._set_state(self.S_SAMPLE_WAIT_SENSOR)
        self._wait_for = "tpos_status"
        expected_sensor = "R" if self._current_direction == "+" else "L"
        self._expected_response_description = f"{expected_sensor} sensor event for PWM {self._current_pwm} sample {self._current_sample_index}"
        self.status_changed(
            f"Waiting for {expected_sensor} sensor event: PWM {self._current_pwm}, sample {self._current_sample_index}, direction {self._current_direction}"
        )

    def _handle_velocity_ack(self, value: object) -> None:
        if self._state != self.S_HOME_WAIT_VEL_ACK or self._wait_for != "vel_ack":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "VEL", self._expected_response_description or "velocity ACK"
                )
            )
            return
        if value is None:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "VEL", self._expected_response_description or "velocity ACK"
                )
            )
            return
        if int(value) != 80:
            self._fail_with_stop(
                f"Unexpected home velocity ACK {value}; expected 80."
            )
            return

        self._set_state(self.S_HOME_WAIT_TPOS)
        self._wait_for = "tpos_status"
        self._expected_response_description = "TPOS home completion"
        self.status_changed("Moving to home using TPOS 0")
        self.command_requested(build_tpos(0))

    def _handle_tpos_status(self, value: dict | None) -> None:
        if not isinstance(value, dict) or "event" not in value:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "sensor event"
                )
            )
            return

        event = value.get("event")
        if event == "I":
            self._fail_with_stop(
                f"Unexpected encoder reset during sampling. PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}."
            )
            return

        if event == "Z":
            event = value.get("by")

        if self._state == self.S_HOME_WAIT_TPOS:
            if event == "started":
                self.status_changed("Waiting for TPOS home completion")
                return
            if event in ("reached", "no_move"):
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Reading home position")
                self.command_requested(build_getpos())
                return
            if event == "L":
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Home sensor reached; reading home position")
                self.command_requested(build_getpos())
                return
            if event == "Z" and value.get("by") == "L":
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Home sensor reached; reading home position")
                self.command_requested(build_getpos())
                return
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "TPOS home completion"
                )
            )
            return

        if self._state == self.S_WAIT_MIDDLE_TPOS:
            if event == "started":
                self.status_changed("Waiting for TPOS middle completion")
                return
            if event in ("reached", "no_move"):
                self._complete()
                return
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "TPOS middle completion"
                )
            )
            return

        if self._wait_for != "tpos_status":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "sensor event"
                )
            )
            return

        expected_sensor = "L" if self._current_direction in ("HOME", "-") else "R"
        if event not in ("L", "R"):
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "sensor event"
                )
            )
            return

        if self._current_direction == "+" and event != "R":
            self._fail_with_stop(
                f"Wrong sensor event during positive move. Expected R, got {event}. PWM={self._current_pwm}, sample_index={self._current_sample_index}."
            )
            return
        if self._current_direction == "-" and event != "L":
            self._fail_with_stop(
                f"Wrong sensor event during negative move. Expected L, got {event}. PWM={self._current_pwm}, sample_index={self._current_sample_index}."
            )
            return

        self._pending_sensor_time = self._clock()
        self._wait_for = "getpos"
        self._set_state(self.S_SAMPLE_WAIT_GETPOS)
        self._expected_response_description = "GETPOS response"
        self.command_requested(build_getpos())

    def _handle_getpos(self, value: object) -> None:
        if self._wait_for != "getpos":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "GETPOS", self._expected_response_description or "GETPOS response"
                )
            )
            return
        if not isinstance(value, tuple) or len(value) != 2 or value[0] != "G":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "GETPOS", self._expected_response_description or "GETPOS response"
                )
            )
            return

        position = int(value[1])
        if self._current_direction == "HOME":
            self._start_l_pos = position
            self._wait_for = None
            self.status_changed(f"Home position captured: {position}")
            self.log_message(f"Home endpoint captured: {position}")
            self._start_next_sample_pair()
            return

        if self._pending_ack_time is None or self._pending_sensor_time is None:
            self._fail_with_stop("Missing timing data for sampling measurement.")
            return

        elapsed_seconds = float(self._pending_sensor_time - self._pending_ack_time)
        if elapsed_seconds <= 0:
            self._fail_with_stop(
                f"Non-positive sampling duration detected. PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}."
            )
            return

        if self._current_direction == "+":
            self._current_r_pos = position
            if self._start_l_pos is None:
                self._fail_with_stop("Home position is missing before positive measurement.")
                return
            range_value = abs(int(self._current_r_pos) - int(self._start_l_pos))
            return_error = None
        else:
            self._current_l_pos = position
            if self._current_r_pos is None:
                self._fail_with_stop("Positive reference position is missing before negative measurement.")
                return
            range_value = abs(int(self._current_r_pos) - int(self._current_l_pos))
            return_error = abs(int(self._current_l_pos) - int(self._start_l_pos or 0))

        speed = float(range_value) / float(elapsed_seconds)
        rounded_elapsed_seconds = round(float(elapsed_seconds), 3)
        result = SamplingMeasurementResult(
            pwm=self._current_pwm,
            sample_index=self._current_sample_index,
            direction=self._current_direction,
            range_value=range_value,
            elapsed_seconds=elapsed_seconds,
            speed=speed,
            start_l_pos=int(self._start_l_pos or 0),
            r_pos=self._current_r_pos,
            l_pos=self._current_l_pos,
            return_error=return_error,
        )

        try:
            range_cell = self._adapter.write_sampling_result(
                "Range",
                self._current_pwm,
                self._current_direction,
                self._current_sample_index,
                range_value,
                base_group=self._base_group,
            )
            speed_cell = self._adapter.write_sampling_result(
                "Speed",
                self._current_pwm,
                self._current_direction,
                self._current_sample_index,
                speed,
                base_group=self._base_group,
            )
            time_cell = self._adapter.write_sampling_result(
                "Time",
                self._current_pwm,
                self._current_direction,
                self._current_sample_index,
                rounded_elapsed_seconds,
                base_group=self._base_group,
            )
        except Exception as exc:
            self._fail_with_stop(
                f"Workbook write failed for PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}: {exc}"
            )
            return

        result = SamplingMeasurementResult(
            pwm=result.pwm,
            sample_index=result.sample_index,
            direction=result.direction,
            range_value=result.range_value,
            elapsed_seconds=result.elapsed_seconds,
            speed=result.speed,
            start_l_pos=result.start_l_pos,
            r_pos=result.r_pos,
            l_pos=result.l_pos,
            return_error=result.return_error,
            workbook_cells={"Range": range_cell, "Speed": speed_cell, "Time": time_cell},
        )
        self._latest_result = result
        self.latest_measurement_changed(range_value, elapsed_seconds, speed)
        self.measurement_completed(result)
        self.latest_workbook_cell_written(time_cell)

        self._completed_measurements += 1
        self.samples_completed_changed(self._completed_measurements, self._total_measurements)

        if self._current_direction == "+":
            self._start_negative_leg()
            return

        if self._current_sample_index < int(self._run_samples_per_pwm):
            self._current_sample_index += 1
            self.current_sample_changed(self._current_sample_index)
            self._start_next_sample_pair()
            return

        if self._current_pwm_index + 1 < len(self._run_pwm_values):
            self._current_pwm_index += 1
            self._current_sample_index = 1
            self.current_sample_changed(self._current_sample_index)
            self._current_pwm = int(self._run_pwm_values[self._current_pwm_index])
            self.current_pwm_changed(self._current_pwm)
            self._start_next_sample_pair()
            return

        self._move_to_middle_and_complete(range_value)

    def _move_to_middle_and_complete(self, range_value: int) -> None:
        self._middle_target = int(int(range_value) // 2)
        self._set_state(self.S_WAIT_MIDDLE_TPOS)
        self._wait_for = "tpos_status"
        self._expected_response_description = "TPOS middle completion"
        self.status_changed("Moving to middle")
        self.log_message("Moving to middle")
        self.command_requested(build_tpos(int(self._middle_target or 0)))

    def _coerce_packet(self, packet: list[int] | bytes | bytearray | dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(packet, dict):
            if packet.get("status") not in (None, "ok"):
                return None
            if packet.get("type") not in (None, "can_over_uart"):
                return None
            cmd = packet.get("cmd")
            params = packet.get("params", [])
            sender = packet.get("sender")
            if cmd is None:
                return None
            params_list = [int(value) & 0xFF for value in list(params)]
            raw_values = [int(cmd) & 0xFF, *params_list]
            return {
                "cmd": int(cmd) & 0xFF,
                "params": params_list,
                "sender": sender if sender is None else int(sender),
                "raw_hex": " ".join(f"{value:02X}" for value in raw_values),
            }

        values = [int(value) & 0xFF for value in list(packet)]
        if not values:
            return None
        return {
            "cmd": values[0],
            "params": values[1:],
            "sender": None,
            "raw_hex": " ".join(f"{value:02X}" for value in values),
        }

    @staticmethod
    def _format_run_payload(velocity: int) -> str:
        payload = build_run(int(velocity))
        return " ".join(f"{value:02X}" for value in payload)

    @staticmethod
    def _format_run_ack_description(velocity: int) -> str:
        payload = build_run(int(velocity))
        return f"RUN ACK 88 53 {payload[1]:02X} {payload[2]:02X}"

    @staticmethod
    def _build_unexpected_packet_reason(raw_hex: str, expected: str) -> str:
        return f"Unexpected packet while waiting for {expected}: {raw_hex}"
