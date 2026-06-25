"""Sampling Test controller/state machine for IPQC workbook capture."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
import time

from data.binary_cmd_builders import build_getpos, build_run, build_stopmotor, build_tpos, build_vel
from data.binary_cmd_parser import decode_command
from services.ipqc_excel_adapter import IpqcExcelAdapter, SamplingWorkbookLayout
from services.node_motion_polarity import NodeMotionPolarity
from services.node_sensor_profile import NodeSensorProfile


@dataclass(frozen=True)
class SamplingTestConfig:
    home_velocity: int = -190
    home_sensor: str = "L"
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


@dataclass(frozen=True)
class SamplingResumeContext:
    node_id: int
    node_name: str | None
    base_group: str
    sheet_name: str
    pwm_values: tuple[int, ...]
    samples_per_direction: int
    current_pwm_index: int
    current_pwm: int
    current_sample_index: int
    current_direction: str
    completed_measurements: int
    total_measurements: int
    terminal_state: str
    reason: str
    resumable: bool
    sample_incomplete: bool
    nodeconfig_raw: int = -1
    home_sensor: str = "L"
    sensor_profile_name: str = ""
    middle_target: int | None = None


@dataclass(frozen=True)
class SamplingTerminalResult:
    terminal_state: str
    final_status: str
    status_text: str
    reason: str
    failure_context: str
    resume_text: str
    pwm: int | None
    direction: str | None
    sample_index: int | None
    completed_count: int
    total_count: int
    resumable: bool


class SamplingTestController:
    """State machine that drives sampling motion and writes workbook results."""

    S_IDLE = "IDLE"
    S_HOME_WAIT_VEL_ACK = "HOME_WAIT_VEL_ACK"
    S_HOME_WAIT_TPOS = "HOME_WAIT_TPOS"
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
        self._motion_polarity: NodeMotionPolarity | None = None
        self._sensor_profile: NodeSensorProfile | None = None
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
        self._home_position: int | None = None
        self._opposite_position: int | None = None
        self._start_l_pos: int | None = None
        self._current_r_pos: int | None = None
        self._current_l_pos: int | None = None
        self._pending_ack_velocity: int | None = None
        self._pending_ack_time: float | None = None
        self._pending_sensor_time: float | None = None
        self._pending_departure_sensor: str | None = None
        self._allow_departure_duplicate: bool = False
        self._pending_getpos_after_sensor: str | None = None
        self._middle_target: int | None = None
        self._latest_result: SamplingMeasurementResult | None = None
        self._stop_command_sent = False
        self._resume_context: SamplingResumeContext | None = None
        self._resume_middle_after_home = False
        self._resume_middle_target: int | None = None
        self._latest_terminal_result: SamplingTerminalResult | None = None

    @property
    def last_result(self) -> SamplingMeasurementResult | None:
        return self._latest_result

    @property
    def last_terminal_result(self) -> SamplingTerminalResult | None:
        return self._latest_terminal_result

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

    @property
    def home_sensor(self) -> str:
        if self._sensor_profile is not None:
            return self._sensor_profile.completion_sensor_for_phase("hunt")
        if self._motion_polarity is not None:
            return self._motion_polarity.home_sensor
        raise RuntimeError("Unsupported or missing node motion context. Motion blocked for safety.")

    def set_home_sensor(self, home_sensor: str) -> None:
        self._config = SamplingTestConfig(
            home_velocity=self._config.home_velocity,
            home_sensor=self._normalize_home_sensor(home_sensor),
            pwm_values=self._config.pwm_values,
            samples_per_direction=self._config.samples_per_direction,
        )

    @property
    def motion_polarity(self) -> NodeMotionPolarity | None:
        return self._motion_polarity

    def set_motion_polarity(self, motion_polarity: NodeMotionPolarity | None) -> None:
        self._motion_polarity = motion_polarity

    @property
    def sensor_profile(self) -> NodeSensorProfile | None:
        return self._sensor_profile

    def set_sensor_profile(self, sensor_profile: NodeSensorProfile | None) -> None:
        self._sensor_profile = sensor_profile

    @property
    def can_resume(self) -> bool:
        return bool(self._resume_context is not None and self._resume_context.resumable)

    @property
    def resume_context(self) -> SamplingResumeContext | None:
        return self._resume_context

    def clear_resume_context(self) -> None:
        self._clear_resume_context()

    @property
    def resume_summary(self) -> str:
        if self._resume_context is None:
            return "Resume unavailable: Sampling has not started."
        if not self._resume_context.resumable:
            return f"Resume unavailable: {self._resume_context.reason}"
        if self._resume_context.terminal_state == self.S_WAIT_MIDDLE_TPOS and self._resume_context.middle_target is not None:
            return f"Resume from middle target {self._resume_context.middle_target}"
        return f"Resume from PWM {self._resume_context.current_pwm}, sample {self._resume_context.current_sample_index}"

    def resume_availability(
        self,
        *,
        node_id: int | None,
        node_name: str | None,
        base_group: str | None,
    ) -> tuple[bool, str]:
        if self._running:
            return False, "Sampling is already active."
        if self._resume_context is None:
            return False, "Resume unavailable: Sampling has not started."
        if not self._resume_context.resumable:
            return False, f"Resume unavailable: {self._resume_context.reason}"
        if self._motion_polarity is None:
            return False, "Unsupported or missing NODECONFIG. Motion blocked for safety."
        if self._sensor_profile is None:
            return False, "Unsupported or missing node sensor profile. Motion blocked for safety."
        if self._resume_context.nodeconfig_raw >= 0 and int(self._motion_polarity.nodeconfig_raw) != int(self._resume_context.nodeconfig_raw):
            return False, "Resume unavailable: select the original NODECONFIG context."
        if self._resume_context.sensor_profile_name and self._sensor_profile.profile_name != self._resume_context.sensor_profile_name:
            return False, "Resume unavailable: select the original node sensor profile."
        if node_id is None or node_name is None:
            return False, "Resume unavailable: select the original Sampling node."
        if int(node_id) != int(self._resume_context.node_id) or str(node_name) != str(self._resume_context.node_name):
            return False, "Resume unavailable: select the original Sampling node."
        if base_group is None:
            return False, "Resume unavailable: select the original Sampling sheet."
        if str(base_group) != str(self._resume_context.base_group):
            return False, "Resume unavailable: select the original Sampling sheet."
        if not self._adapter.has_loaded_workbook():
            return False, "Load an IPQC workbook before resuming Sampling."
        try:
            layout = self._adapter.discover_sampling_layout(str(base_group))
        except Exception as exc:
            return False, f"Resume unavailable: Sampling workbook layout is invalid: {exc}"
        if layout.sheet_name != self._resume_context.sheet_name:
            return False, "Resume unavailable: select the original Sampling sheet."
        return True, self.resume_summary

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
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False
        if not self._adapter.has_loaded_workbook():
            reason = "No IPQC workbook is loaded."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False
        if self._motion_polarity is None:
            reason = "Unsupported or missing NODECONFIG. Motion blocked for safety."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False
        if self._sensor_profile is None:
            reason = "Unsupported or missing node sensor profile. Motion blocked for safety."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False

        self._node_id = int(node_id)
        self._node_name = node_name
        self._base_group = base_group or self._adapter.active_sheet_group
        if not self._base_group:
            reason = "No active IPQC workbook sheet group is selected."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False

        try:
            self._layout = self._adapter.discover_sampling_layout(self._base_group)
        except Exception as exc:
            reason = f"Sampling workbook layout is invalid: {exc}"
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False

        run_pwm_values = tuple(int(value) for value in (pwm_values if pwm_values is not None else self._config.pwm_values))
        if not run_pwm_values:
            reason = "No PWM values are configured for Sampling."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False

        run_samples_per_pwm = int(samples_per_pwm if samples_per_pwm is not None else self._config.samples_per_direction)
        if run_samples_per_pwm <= 0:
            reason = "Sampling requires at least one sample per PWM."
            self.log_message(f"[Sampling] {reason}")
            self._latest_terminal_result = self._build_terminal_result(
                terminal_state=self.S_FAILED,
                final_status="FAILED",
                status_text="FAILED",
                reason=reason,
                failure_context="-",
                resume_text="Unavailable - sampling requires a fresh start.",
                resumable=False,
            )
            self.sampling_failed(reason)
            return False

        self._clear_resume_context()
        self._latest_terminal_result = None
        self._run_pwm_values = run_pwm_values
        self._run_samples_per_pwm = run_samples_per_pwm
        self._begin_sampling_run(
            node_id=self._node_id,
            node_name=self._node_name,
            base_group=self._base_group,
            resume_context=None,
        )
        return True

    def resume(
        self,
        *,
        node_id: int | None = None,
        node_name: str | None = None,
        base_group: str | None = None,
    ) -> bool:
        availability, reason = self.resume_availability(node_id=node_id, node_name=node_name, base_group=base_group)
        if not availability:
            self.log_message(f"[Sampling] {reason}")
            return False
        context = self._resume_context
        if context is None:
            self.log_message("[Sampling] Resume unavailable: Sampling has not started.")
            return False
        if self._motion_polarity is None:
            self.log_message("[Sampling] Unsupported or missing NODECONFIG. Motion blocked for safety.")
            return False
        if self._sensor_profile is None:
            self.log_message("[Sampling] Unsupported or missing node sensor profile. Motion blocked for safety.")
            return False
        if context.nodeconfig_raw >= 0 and int(self._motion_polarity.nodeconfig_raw) != int(context.nodeconfig_raw):
            self.log_message("[Sampling] Resume unavailable: select the original NODECONFIG context.")
            return False
        if context.sensor_profile_name and self._sensor_profile.profile_name != context.sensor_profile_name:
            self.log_message("[Sampling] Resume unavailable: select the original node sensor profile.")
            return False

        self._begin_sampling_run(
            node_id=context.node_id,
            node_name=context.node_name,
            base_group=context.base_group,
            resume_context=context,
        )
        return True

    def stop(self) -> bool:
        return self.abort_by_user()

    def abort_by_user(self) -> bool:
        if not self._running:
            return False
        reason = "Sampling aborted by user."
        self._capture_resume_context(reason, resumable=True, terminal_state=self.S_ABORTED)
        self._send_stopmotor()
        self._running = False
        self._clear_pending_runtime_state()
        self._state = self.S_ABORTED
        self.state_changed(self._state)
        self.status_changed(reason)
        self.log_message("Sampling aborted")
        self._latest_terminal_result = self._build_terminal_result(
            terminal_state=self.S_ABORTED,
            final_status="ABORTED",
            status_text="ABORTED",
            reason=reason,
            failure_context=self._format_failure_context(),
            resume_text="Unavailable - sampling was aborted.",
            resumable=True,
        )
        self.sampling_aborted(reason)
        return True

    def on_timeout(self) -> None:
        if not self._running:
            return
        reason = f"Timed out waiting for {self._expected_response_description or 'sampling response'}."
        self._fail_with_stop(reason, resumable=True)

    def handle_runtime_packet(self, packet: list[int] | bytes | bytearray | dict[str, Any]) -> None:
        if not self._running or self._state in (self.S_FAILED, self.S_ABORTED, self.S_COMPLETED):
            return

        packet_data = self._coerce_packet(packet)
        if packet_data is None:
            return

        sender = packet_data["sender"]
        if self._node_id is not None and sender is not None and int(sender) != int(self._node_id):
            self._fail_with_stop(
                f"Unexpected packet from node {int(sender)} while sampling node {int(self._node_id)}.",
                resumable=False,
            )
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
                ),
                resumable=False,
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
        if decoded_kind == "sys_mode":
            self._handle_sys_mode(decoded_value)
            return

        self._fail_with_stop(
            self._build_unexpected_packet_reason(
                packet_data["raw_hex"], self._expected_response_description or "sampling response"
            ),
            resumable=False,
        )

    def _reset_runtime_state(self) -> None:
        self._wait_for = None
        self._expected_response_description = ""
        self._current_pwm_index = -1
        self._current_pwm = 0
        self._current_sample_index = 0
        self._current_direction = ""
        self._completed_measurements = 0
        self._home_position = None
        self._opposite_position = None
        self._start_l_pos = None
        self._current_r_pos = None
        self._current_l_pos = None
        self._pending_ack_velocity = None
        self._pending_ack_time = None
        self._pending_sensor_time = None
        self._pending_departure_sensor = None
        self._allow_departure_duplicate = False
        self._pending_getpos_after_sensor = None
        self._middle_target = None
        self._latest_result = None
        self._total_measurements = len(self._run_pwm_values) * self._run_samples_per_pwm * 2
        self._stop_command_sent = False
        self._latest_terminal_result = None

    @staticmethod
    def _normalize_home_sensor(value: object) -> str:
        return "R" if str(value).strip().upper() == "R" else "L"

    def _require_motion_polarity(self) -> NodeMotionPolarity | None:
        if self._motion_polarity is None:
            self._fail_with_stop("Unsupported or missing NODECONFIG. Motion blocked for safety.", resumable=False)
            return None
        return self._motion_polarity

    def _require_sensor_profile(self) -> NodeSensorProfile | None:
        if self._sensor_profile is None:
            self._fail_with_stop("Unsupported or missing node sensor profile. Motion blocked for safety.", resumable=False)
            return None
        return self._sensor_profile

    @property
    def _opposite_sensor(self) -> str:
        profile = self._require_sensor_profile()
        if profile is None:
            raise RuntimeError("Unsupported or missing node sensor profile. Motion blocked for safety.")
        return profile.completion_sensor_for_phase("outward")

    @property
    def _outward_direction(self) -> str:
        polarity = self._require_motion_polarity()
        if polarity is None:
            raise RuntimeError("Unsupported or missing NODECONFIG. Motion blocked for safety.")
        return "+" if polarity.outward_sign > 0 else "-"

    @property
    def _return_direction(self) -> str:
        polarity = self._require_motion_polarity()
        if polarity is None:
            raise RuntimeError("Unsupported or missing NODECONFIG. Motion blocked for safety.")
        return "+" if polarity.return_home_sign > 0 else "-"

    def _velocity_for_direction(self, direction: str, pwm: int) -> int:
        return int(pwm) if direction == "+" else -int(pwm)

    def _expected_sensor_for_direction(self, direction: str) -> str:
        profile = self._require_sensor_profile()
        if profile is None:
            raise RuntimeError("Unsupported or missing node sensor profile. Motion blocked for safety.")
        return profile.completion_sensor_for_phase("outward" if direction == self._outward_direction else "return")

    def _departure_sensor_for_direction(self, direction: str) -> str:
        profile = self._require_sensor_profile()
        if profile is None:
            raise RuntimeError("Unsupported or missing node sensor profile. Motion blocked for safety.")
        return profile.completion_sensor_for_phase("hunt" if direction == self._outward_direction else "outward")

    def _clear_resume_context(self) -> None:
        self._resume_context = None
        self._resume_middle_after_home = False
        self._resume_middle_target = None

    def _begin_sampling_run(
        self,
        *,
        node_id: int | None,
        node_name: str | None,
        base_group: str | None,
        resume_context: SamplingResumeContext | None,
    ) -> None:
        self._node_id = int(node_id) if node_id is not None else None
        self._node_name = node_name
        self._base_group = base_group
        if self._motion_polarity is None or self._sensor_profile is None:
            self._fail_with_stop("Unsupported or missing motion context. Motion blocked for safety.", resumable=False)
            return
        if resume_context is not None:
            self._run_pwm_values = tuple(resume_context.pwm_values)
            self._run_samples_per_pwm = int(resume_context.samples_per_direction)
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
        if resume_context is not None:
            self._resume_context = resume_context
            self._resume_middle_after_home = resume_context.terminal_state == self.S_WAIT_MIDDLE_TPOS
            self._resume_middle_target = resume_context.middle_target
            self._current_pwm_index = int(resume_context.current_pwm_index)
            self._current_pwm = int(resume_context.current_pwm)
            self._current_sample_index = int(resume_context.current_sample_index)
            self._completed_measurements = int(resume_context.completed_measurements)
            if (
                resume_context.sample_incomplete
                and resume_context.current_direction == "-"
                and resume_context.terminal_state in (
                    self.S_SAMPLE_WAIT_ACK,
                    self.S_SAMPLE_WAIT_SENSOR,
                    self.S_SAMPLE_WAIT_GETPOS,
                )
            ):
                self._completed_measurements = max(0, self._completed_measurements - 1)
            self._total_measurements = int(resume_context.total_measurements)
            self.current_pwm_changed(self._current_pwm)
            self.current_sample_changed(self._current_sample_index)
            self.samples_completed_changed(self._completed_measurements, self._total_measurements)
            self.log_message(f"[Sampling] {self.resume_summary}")
        else:
            self._clear_resume_context()
        self.status_changed("Setting home velocity")
        self.command_requested(build_vel(80))

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
        self._current_direction = self._outward_direction
        self.current_direction_changed(self._current_direction)
        self._pending_ack_velocity = self._velocity_for_direction(self._current_direction, self._current_pwm)
        self._expected_response_description = self._format_run_ack_description(self._pending_ack_velocity)
        self._set_state(self.S_SAMPLE_WAIT_ACK)
        self._wait_for = "run_started"
        self.command_requested(build_run(self._pending_ack_velocity))

    def _start_negative_leg(self) -> None:
        self._current_direction = self._return_direction
        self.current_direction_changed(self._current_direction)
        self._pending_ack_velocity = self._velocity_for_direction(self._current_direction, self._current_pwm)
        self._expected_response_description = self._format_run_ack_description(self._pending_ack_velocity)
        self._set_state(self.S_SAMPLE_WAIT_ACK)
        self._wait_for = "run_started"
        self.command_requested(build_run(self._pending_ack_velocity))

    def _complete(self) -> None:
        self._clear_resume_context()
        self._clear_pending_runtime_state()
        self._running = False
        self._set_state(self.S_COMPLETED)
        self.status_changed("Sampling completed")
        self.log_message("Sampling completed")
        self._latest_terminal_result = self._build_terminal_result(
            terminal_state=self.S_COMPLETED,
            final_status="COMPLETED",
            status_text="Sampling completed",
            reason="-",
            failure_context="-",
            resume_text="-",
            resumable=False,
        )
        self.sampling_completed()

    def _capture_resume_context(self, reason: str, *, resumable: bool, terminal_state: str) -> None:
        sample_incomplete = self._is_sample_incomplete_for_resume()
        resume_pwm_index = int(self._current_pwm_index)
        resume_pwm = int(self._current_pwm)
        resume_sample_index = int(self._current_sample_index)
        if resume_pwm_index < 0 and self._run_pwm_values:
            resume_pwm_index = 0
            resume_pwm = int(self._run_pwm_values[0])
            resume_sample_index = 1
        context = SamplingResumeContext(
            node_id=int(self._node_id or 0),
            node_name=self._node_name,
            base_group=str(self._base_group or ""),
            sheet_name=str(self.sheet_name or ""),
            pwm_values=tuple(self._run_pwm_values),
            samples_per_direction=int(self._run_samples_per_pwm),
            current_pwm_index=resume_pwm_index,
            current_pwm=resume_pwm,
            current_sample_index=resume_sample_index,
            current_direction=self._current_direction,
            completed_measurements=int(self._completed_measurements),
            total_measurements=int(self._total_measurements),
            terminal_state=terminal_state,
            reason=reason,
            resumable=bool(resumable),
            sample_incomplete=sample_incomplete,
            nodeconfig_raw=int(self._motion_polarity.nodeconfig_raw) if self._motion_polarity is not None else -1,
            home_sensor=self.home_sensor,
            sensor_profile_name=self._sensor_profile.profile_name if self._sensor_profile is not None else "",
            middle_target=int(self._middle_target) if self._middle_target is not None else None,
        )
        self._resume_context = context
        self._resume_middle_after_home = terminal_state == self.S_WAIT_MIDDLE_TPOS
        self._resume_middle_target = context.middle_target

    def _is_sample_incomplete_for_resume(self) -> bool:
        return self._state in (self.S_SAMPLE_WAIT_ACK, self.S_SAMPLE_WAIT_SENSOR, self.S_SAMPLE_WAIT_GETPOS) and self._current_direction in ("+", "-")

    def _fail_with_stop(self, reason: str, *, resumable: bool = False) -> None:
        if not self._running:
            return
        self._pending_getpos_after_sensor = None
        self._capture_resume_context(reason, resumable=resumable, terminal_state=self.S_FAILED)
        self._send_stopmotor()
        self._running = False
        self._clear_pending_runtime_state()
        self._set_state(self.S_FAILED)
        self.status_changed(reason)
        self.log_message(f"Sampling failed: {reason}")
        self._latest_terminal_result = self._build_terminal_result(
            terminal_state=self.S_FAILED,
            final_status="FAILED",
            status_text="FAILED",
            reason=self._summarize_failure_reason(reason),
            failure_context=self._format_failure_context(),
            resume_text=self._build_resume_text(reason, resumable=resumable),
            resumable=resumable,
        )
        self.sampling_failed(reason)

    def _handle_run_started(self, value: object) -> None:
        if self._wait_for != "run_started":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "RUN ACK", self._expected_response_description or "RUN ACK"
                ),
                resumable=False,
            )
            return
        if value is None:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "RUN ACK", self._expected_response_description or "RUN ACK"
                ),
                resumable=False,
            )
            return
        if self._pending_ack_velocity is not None and int(value) != int(self._pending_ack_velocity):
            reason = (
                f"Unexpected RUN ACK velocity {value}; expected {self._pending_ack_velocity}. "
                f"Current PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}."
            )
            self._fail_with_stop(reason, resumable=False)
            return

        self._pending_ack_time = self._clock()
        self._set_state(self.S_SAMPLE_WAIT_SENSOR)
        self._wait_for = "tpos_status"
        expected_sensor = self._expected_sensor_for_direction(self._current_direction)
        self._pending_departure_sensor = self._departure_sensor_for_direction(self._current_direction)
        self._allow_departure_duplicate = True
        self._expected_response_description = f"{expected_sensor} sensor event for PWM {self._current_pwm} sample {self._current_sample_index}"
        self.status_changed(
            f"Waiting for {expected_sensor} sensor event: PWM {self._current_pwm}, sample {self._current_sample_index}, direction {self._current_direction}"
        )

    def _handle_velocity_ack(self, value: object) -> None:
        if self._state != self.S_HOME_WAIT_VEL_ACK or self._wait_for != "vel_ack":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "VEL", self._expected_response_description or "velocity ACK"
                ),
                resumable=True,
            )
            return
        if value is None:
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "VEL", self._expected_response_description or "velocity ACK"
                ),
                resumable=True,
            )
            return
        if int(value) != 80:
            self._fail_with_stop(
                f"Unexpected home velocity ACK {value}; expected 80.",
                resumable=True,
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
                ),
                resumable=False,
            )
            return

        event = value.get("event")
        if event == "I":
            self._fail_with_stop(
                f"Unexpected encoder reset during sampling. PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}.",
                resumable=False,
            )
            return

        if event == "Z":
            event = value.get("by")

        if self._state == self.S_HOME_WAIT_TPOS:
            profile = self._require_sensor_profile()
            if profile is None:
                return
            if event == "started":
                self.status_changed("Waiting for TPOS home completion")
                return
            if event in ("reached", "no_move"):
                self._pending_getpos_after_sensor = profile.completion_sensor_for_phase("hunt")
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Reading home position")
                self.command_requested(build_getpos())
                return
            if profile.matches_phase_sensor("hunt", event):
                self._pending_getpos_after_sensor = profile.completion_sensor_for_phase("hunt")
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Home sensor reached; reading home position")
                self.command_requested(build_getpos())
                return
            if event == "Z" and profile.matches_phase_sensor("hunt", value.get("by")):
                self._pending_getpos_after_sensor = profile.completion_sensor_for_phase("hunt")
                self._wait_for = "getpos"
                self._set_state(self.S_HOME_WAIT_GETPOS)
                self._expected_response_description = "GETPOS response for home position"
                self.status_changed("Home sensor reached; reading home position")
                self.command_requested(build_getpos())
                return
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "TPOS home completion"
                ),
                resumable=True,
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
                ),
                resumable=True,
            )
            return

        if self._wait_for == "getpos" and self._pending_getpos_after_sensor in ("L", "R"):
            expected_sensor = self._pending_getpos_after_sensor
            if event == expected_sensor or (event == "Z" and value.get("by") == expected_sensor):
                return

        if self._state == self.S_SAMPLE_WAIT_SENSOR and self._wait_for == "tpos_status":
            expected_departure_sensor = self._pending_departure_sensor
            if (
                self._allow_departure_duplicate
                and expected_departure_sensor in ("L", "R")
                and (event == expected_departure_sensor or (event == "Z" and value.get("by") == expected_departure_sensor))
            ):
                self._allow_departure_duplicate = False
                return

        if self._wait_for != "tpos_status":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "sensor event"
                ),
                resumable=False,
            )
            return

        if event not in ("L", "R"):
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "TPOS", self._expected_response_description or "sensor event"
                ),
                resumable=False,
            )
            return

        expected_sensor = self._expected_sensor_for_direction(self._current_direction)
        if event != expected_sensor:
            self._fail_with_stop(
                f"Wrong sensor event during {('outward' if self._current_direction == self._outward_direction else 'return')} move. Expected {expected_sensor}, got {event}. PWM={self._current_pwm}, sample_index={self._current_sample_index}.",
                resumable=True,
            )
            return

        self._pending_sensor_time = self._clock()
        self._pending_getpos_after_sensor = expected_sensor
        self._pending_departure_sensor = None
        self._allow_departure_duplicate = False
        self._wait_for = "getpos"
        self._set_state(self.S_SAMPLE_WAIT_GETPOS)
        self._expected_response_description = "GETPOS response"
        self.command_requested(build_getpos())

    def _handle_getpos(self, value: object) -> None:
        if self._wait_for != "getpos":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "GETPOS", self._expected_response_description or "GETPOS response"
                ),
                resumable=False,
            )
            return
        self._pending_getpos_after_sensor = None
        self._pending_departure_sensor = None
        self._allow_departure_duplicate = False
        if not isinstance(value, tuple) or len(value) != 2 or value[0] != "G":
            self._fail_with_stop(
                self._build_unexpected_packet_reason(
                    "GETPOS", self._expected_response_description or "GETPOS response"
                ),
                resumable=False,
            )
            return

        position = int(value[1])
        if self._current_direction == "HOME":
            self._start_l_pos = position
            self._home_position = position
            profile = self._require_sensor_profile()
            if profile is None:
                return
            self._pending_getpos_after_sensor = profile.completion_sensor_for_phase("hunt")
            self._wait_for = None
            self.status_changed(f"Home position captured: {position}")
            self.log_message(f"Home endpoint captured: {position}")
            if self._resume_middle_after_home and self._resume_middle_target is not None:
                self._resume_move_to_middle_and_complete()
            else:
                self._start_next_sample_pair()
            return

        if self._pending_ack_time is None or self._pending_sensor_time is None:
            self._fail_with_stop("Missing timing data for sampling measurement.", resumable=False)
            return

        elapsed_seconds = float(self._pending_sensor_time - self._pending_ack_time)
        if elapsed_seconds <= 0:
            self._fail_with_stop(
                f"Non-positive sampling duration detected. PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}.",
                resumable=False,
            )
            return

        if self._current_direction == self._outward_direction:
            self._current_r_pos = position
            self._opposite_position = position
            if self._start_l_pos is None:
                self._fail_with_stop("Home position is missing before outward measurement.", resumable=False)
                return
            range_value = abs(int(self._current_r_pos) - int(self._start_l_pos))
            return_error = None
        else:
            self._current_l_pos = position
            if self._current_r_pos is None:
                self._fail_with_stop("Opposite reference position is missing before return measurement.", resumable=False)
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
                f"Workbook write failed for PWM={self._current_pwm}, direction={self._current_direction}, sample_index={self._current_sample_index}: {exc}",
                resumable=True,
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

        if self._current_direction == self._outward_direction:
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

    def _resume_move_to_middle_and_complete(self) -> None:
        self._resume_middle_after_home = False
        self._set_state(self.S_WAIT_MIDDLE_TPOS)
        self._wait_for = "tpos_status"
        self._expected_response_description = "TPOS middle completion"
        self.status_changed("Moving to middle")
        self.log_message("Moving to middle")
        self.command_requested(build_tpos(int(self._resume_middle_target or 0)))

    def _handle_sys_mode(self, value: object) -> None:
        if not isinstance(value, dict):
            self._fail_with_stop("Unexpected system mode packet during Sampling.", resumable=False)
            return
        if str(value.get("text", "")).strip().lower() != "fault":
            return
        reason = str(value.get("error_code") or value.get("text") or "Fault")
        self._fail_with_stop(f"Motor fault reported during Sampling: {reason}", resumable=False)

    def _move_to_middle_and_complete(self, range_value: int) -> None:
        _ = range_value
        try:
            self._middle_target = self._calculate_middle_target()
        except RuntimeError as exc:
            self._fail_with_stop(str(exc), resumable=False)
            return
        self._set_state(self.S_WAIT_MIDDLE_TPOS)
        self._wait_for = "tpos_status"
        self._expected_response_description = "TPOS middle completion"
        self.status_changed("Moving to middle")
        self.log_message("Moving to middle")
        self.command_requested(build_tpos(int(self._middle_target or 0)))

    def _calculate_middle_target(self) -> int:
        home_pos = self._home_position if self._home_position is not None else self._start_l_pos
        opposite_pos = self._opposite_position if self._opposite_position is not None else self._current_r_pos
        if home_pos is None or opposite_pos is None:
            raise RuntimeError("Sampling endpoint positions are missing for middle target calculation.")
        return int(int(home_pos) + ((int(opposite_pos) - int(home_pos)) // 2))

    def _clear_pending_runtime_state(self) -> None:
        self._wait_for = None
        self._expected_response_description = ""
        self._pending_ack_velocity = None
        self._pending_ack_time = None
        self._pending_sensor_time = None
        self._pending_departure_sensor = None
        self._allow_departure_duplicate = False
        self._pending_getpos_after_sensor = None

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

    def _build_terminal_result(
        self,
        *,
        terminal_state: str,
        final_status: str,
        status_text: str,
        reason: str,
        failure_context: str,
        resume_text: str,
        resumable: bool,
    ) -> SamplingTerminalResult:
        return SamplingTerminalResult(
            terminal_state=terminal_state,
            final_status=final_status,
            status_text=status_text,
            reason=reason,
            failure_context=failure_context,
            resume_text=resume_text,
            pwm=self._current_pwm if self._current_pwm_index >= 0 else None,
            direction=self._current_direction or None,
            sample_index=self._current_sample_index if self._current_sample_index > 0 else None,
            completed_count=int(self._completed_measurements),
            total_count=int(self._total_measurements),
            resumable=resumable,
        )

    def _format_failure_context(self) -> str:
        parts: list[str] = []
        if self._current_pwm_index >= 0:
            parts.append(f"PWM {int(self._current_pwm)}")
        if self._current_direction:
            parts.append(f"Direction {self._current_direction}")
        if self._current_sample_index > 0:
            parts.append(f"Sample {int(self._current_sample_index)}")
        return " | ".join(parts) if parts else "-"

    def _summarize_failure_reason(self, reason: str) -> str:
        text = str(reason).strip()
        if not text:
            return "-"
        for marker in (" Current PWM=", " PWM=", " direction=", " Direction ", " sample_index="):
            if marker in text:
                text = text.split(marker, 1)[0].rstrip()
        if text.endswith("."):
            return text
        if "." in text:
            return text.split(".", 1)[0].rstrip() + "."
        return text

    def _build_resume_text(self, reason: str, *, resumable: bool) -> str:
        if not resumable:
            if "Unexpected encoder reset during sampling." in reason:
                return "Unavailable - encoder reset requires a fresh start."
            return "Unavailable - sampling requires a fresh start."
        return "Sampling is running."
