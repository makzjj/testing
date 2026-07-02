"""Single Axis Functional Test controller/state machine.

Fake-transport friendly: emits command payloads via `command_requested(list[int])`
and consumes incoming packets via `handle_runtime_packet(packet)` where `packet`
is a `list[int]` or `bytes` in the format `[cmd, <params...>]`.

Architecture:
- Uses existing command builders from gui.workspace.pages.production_parameter_controller
  via the thin shim module `data.binary_cmd_builders`.
- Uses existing parser helpers from `data.binary_cmd_parser.decode_command`.

This module intentionally contains no real serial I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from data.binary_cmd_builders import (
    build_hunting_timeout,
    build_getpos,
    build_run,
    build_tpos,
    build_stopmotor,
    build_nodeconfig_query_payload,
)
from data.binary_cmd_parser import (
    decode_command,
    decode_nodeconfig_motion_polarity,
)
from myconfig.node_display import get_ml20_node_name
from services.node_sensor_profile import NodeSensorProfile
from data.binary_cmd_builders import (
    build_lflag_query_payload,
    build_rflag_query_payload,
)


@dataclass
class FunctionalTestConfig:
    hunt_timeout_ms: int = 10_000
    velocity_left_to_right: int = 190
    velocity_right_to_left: int = -190
    zero_tolerance: int = 5
    movement_tolerance: int | None = None
    range_tolerance: int = 512
    middle_position_tolerance: int = 10
    # Configurable sensor sequence (reference/opposite). Defaults to current production: R -> I -> L -> R
    reference_sensor: str = "R"  # either "L" or "R"
    opposite_sensor: str = "L"   # the other one

    def __post_init__(self) -> None:
        # Keep legacy fields aligned while allowing the popup to provide one shared tolerance.
        if self.movement_tolerance is None:
            if self.middle_position_tolerance != 10:
                chosen = self.middle_position_tolerance
            elif self.range_tolerance != 512:
                chosen = self.range_tolerance
            else:
                chosen = 512
        else:
            chosen = self.movement_tolerance
        chosen = max(0, int(chosen))
        self.movement_tolerance = chosen
        self.range_tolerance = chosen
        self.middle_position_tolerance = chosen


class SingleAxisFunctionalTestController:
    """Implements the state machine described in the issue specification.

    Signals are exposed as methods; tests can monkeypatch/override them to observe events.
    """

    # States (string constants)
    S_IDLE = "IDLE"
    S_HUNTING = "HUNTING"
    S_WAIT_HUNTING_SENSOR = "WAIT_FOR_HUNTING_COMPLETION"
    S_WAIT_ZERO = "WAIT_FOR_ENCODER_INITIALIZATION"
    S_VERIFY_ZERO = "VERIFY_HOME_POSITION_ZERO"
    S_WAIT_LFLAG = "WAIT_FOR_SENSOR_L_FLAG"
    S_WAIT_RFLAG = "WAIT_FOR_SENSOR_R_FLAG"
    S_RUN_TO_RIGHT = "MOVE_TO_OPPOSITE_SENSOR_R"
    S_WAIT_RIGHT = "WAIT_FOR_RIGHT_SENSOR"
    S_READ_RANGE1 = "READ_AND_STORE_RANGE_1"
    S_RUN_TO_LEFT = "MOVE_TO_OPPOSITE_SENSOR_L"
    S_WAIT_LEFT = "WAIT_FOR_LEFT_SENSOR"
    S_READ_RANGE2 = "READ_AND_STORE_RANGE_2"
    S_COMPARE = "COMPARE_RANGE"
    S_MOVE_MIDDLE = "MOVE_TO_MIDDLE"
    S_WAIT_MIDDLE = "WAIT_FOR_MIDDLE_COMPLETION"
    S_ABORTED = "ABORTED"
    S_PASSED = "PASSED"
    S_FAILED = "FAILED"
    _SAFE_PARK_TARGET_COUNTS = -44_000

    def __init__(self, config: FunctionalTestConfig | None = None) -> None:
        self.cfg = config or FunctionalTestConfig()
        self._node_id: int | None = None
        self._state: str = self.S_IDLE

        # Measurements
        self._signed_range_1: int | None = None
        self._range_1: int | None = None
        self._signed_range_2: int | None = None
        self._range_2: int | None = None
        # Positions per corrected plan
        self._opposite_pos: int | None = None
        self._returned_home_pos: int | None = None
        self._middle_target: int | None = None

        # Internal wait kind for timeouts
        self._wait_for: str | None = None
        # Sensor flag cache (queried before first RUN)
        self._lflag: int | None = None
        self._rflag: int | None = None
        self._running: bool = False
        self._motion_polarity = None
        self._sensor_profile: NodeSensorProfile | None = None
        self._movement_phase: str | None = None

    # --- Signal-like methods (override/monkeypatch in tests) ---
    def command_requested(self, payload: list[int]) -> None:  # pragma: no cover - overridden in tests
        pass

    def status_changed(self, text: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def position_changed(self, pos: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def range1_changed(self, value: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def range2_changed(self, value: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def difference_changed(self, value: int) -> None:  # pragma: no cover - overridden in tests
        pass

    def left_flag_changed(self, active: bool) -> None:  # pragma: no cover - overridden in tests
        pass

    def right_flag_changed(self, active: bool) -> None:  # pragma: no cover - overridden in tests
        pass

    def test_passed(self) -> None:  # pragma: no cover - overridden in tests
        pass

    def test_failed(self, reason: str) -> None:  # pragma: no cover - overridden in tests
        pass

    def test_aborted(self, reason: str) -> None:  # pragma: no cover - overridden in tests
        pass

    # --- Public API ---
    def start(self, node_id: int) -> None:
        """Start state machine. Query NODECONFIG, then begin HUNTING based on it."""
        self._node_id = int(node_id)
        self._reset_run_state()
        self._running = True
        self._set_state(self.S_IDLE)
        # Query NODECONFIG first to derive the live motion polarity and sensor profile.
        self._wait_for = "nodeconfig"
        # Log explicitly for live popup visibility
        self.status_changed("Querying NODECONFIG: C4 3F")
        self._emit_command(build_nodeconfig_query_payload())

    def stop(self) -> None:
        self.abort_by_user()

    def abort_by_user(self) -> bool:
        """Abort the active functional test from the UI."""
        if not self._running:
            return False
        node_id = self._node_id
        self._running = False
        self._wait_for = None
        self._set_state(self.S_ABORTED)
        self.status_changed("Functional test aborted by user")
        if node_id is not None:
            self.status_changed(f"Node {node_id}: Functional test ABORTED by user.")
        self._request_stopmotor()
        self.test_aborted("Functional test aborted by user")
        return True

    def stop_requested_by_user(self) -> bool:
        return self.abort_by_user()

    @property
    def current_wait_for(self) -> str | None:
        return self._wait_for

    def on_timeout(self) -> None:
        """Tests can invoke to simulate a timeout for the current wait condition."""
        if not self._running:
            return
        if self._wait_for == "nodeconfig":
            self._request_stopmotor()
            return self._fail("NODECONFIG query timeout")
        if self._state == self.S_HUNTING and self._wait_for == "hunting_ack":
            # No ACK/NACK -> fail
            self._request_stopmotor()
            return self._fail("HUNTING no ACK/NACK/timeout")
        if self._state == self.S_WAIT_HUNTING_SENSOR and self._wait_for in ("left_sensor", "right_sensor"):
            self._request_stopmotor()
            return self._fail("HUNTING timed out before reference sensor event")
        if self._state == self.S_WAIT_ZERO and self._wait_for == "zeroed":
            self._request_stopmotor()
            return self._fail("Encoder init timeout after Left sensor")
        if self._state == self.S_VERIFY_ZERO and self._wait_for == "getpos_zero":
            self._request_stopmotor()
            return self._fail("GETPOS timeout during zero verification")
        if self._state == self.S_VERIFY_ZERO and self._wait_for == "lflag_query":
            self._request_stopmotor()
            return self._fail("SensorL flag timeout")
        if self._state == self.S_VERIFY_ZERO and self._wait_for == "rflag_query":
            self._request_stopmotor()
            return self._fail("SensorR flag timeout")
        if self._state == self.S_RUN_TO_RIGHT and self._wait_for == "run_right_ack":
            self._request_stopmotor()
            return self._fail("RUN-to-right ACK not received")
        if self._state == self.S_WAIT_RIGHT and self._wait_for == "right_sensor":
            self._request_stopmotor()
            return self._fail("Right sensor event timeout")
        if self._state == self.S_READ_RANGE1 and self._wait_for == "getpos_r1":
            self._request_stopmotor()
            return self._fail("GETPOS timeout after right sensor")
        if self._state == self.S_RUN_TO_LEFT and self._wait_for == "run_left_ack":
            self._request_stopmotor()
            return self._fail("RUN-to-left ACK not received")
        if self._state == self.S_WAIT_LEFT and self._wait_for == "left_sensor":
            self._request_stopmotor()
            return self._fail("Left sensor event timeout")
        if self._state == self.S_READ_RANGE2 and self._wait_for == "getpos_r2":
            self._request_stopmotor()
            return self._fail("GETPOS timeout after left sensor")
        if self._state == self.S_MOVE_MIDDLE and self._wait_for == "tpos_ack":
            self._request_stopmotor()
            return self._fail("TPOS ACK not received")
        if self._state == self.S_WAIT_MIDDLE and self._wait_for == "tpos_complete":
            self._request_stopmotor()
            return self._fail("TPOS completion timeout")

    def accepts_workflow_packet(self, decoded_kind: str | None, decoded_value, packet: list[int] | None = None) -> bool:
        """Return whether one decoded packet is relevant to the active workflow step."""
        if not self._running or self._state in (self.S_FAILED, self.S_PASSED, self.S_ABORTED):
            return False

        if self._wait_for == "nodeconfig":
            return decoded_kind == "nodeconfig"
        if self._wait_for == "hunting_ack":
            return decoded_kind == "hunting"
        if self._wait_for == "getpos_zero":
            return decoded_kind == "getpos"
        if self._wait_for == "lflag_query":
            return decoded_kind == "lflag"
        if self._wait_for == "rflag_query":
            return decoded_kind == "rflag"
        if self._wait_for == "run_right_ack":
            return (
                self._state == self.S_RUN_TO_RIGHT
                and decoded_kind == "run_started"
                and self._run_ack_matches_expected_velocity(decoded_value)
            )
        if self._wait_for == "run_left_ack":
            return (
                self._state == self.S_RUN_TO_LEFT
                and decoded_kind == "run_started"
                and self._run_ack_matches_expected_velocity(decoded_value)
            )
        if self._wait_for in ("left_sensor", "right_sensor"):
            return self._accepts_sensor_wait_packet(decoded_kind, decoded_value)
        if self._wait_for == "zeroed":
            return self._accepts_zero_wait_packet(decoded_kind, decoded_value)
        if self._wait_for == "getpos_r1":
            return self._state == self.S_READ_RANGE1 and decoded_kind == "getpos"
        if self._wait_for == "getpos_r2":
            return self._state == self.S_READ_RANGE2 and decoded_kind == "getpos"
        if self._wait_for == "tpos_ack":
            return self._accepts_middle_tpos_packet(decoded_kind, decoded_value, require_completion=False)
        if self._wait_for == "tpos_complete":
            return self._accepts_middle_tpos_packet(decoded_kind, decoded_value, require_completion=True)
        return False

    def handle_runtime_packet(self, packet: list[int] | bytes) -> None:
        if not packet:
            return
        if not self._running or self._state in (self.S_FAILED, self.S_PASSED, self.S_ABORTED):
            return
        if isinstance(packet, (bytes, bytearray)):
            data = list(packet)
        else:
            data = list(packet)
        cmd = data[0]
        params = data[1:]

        kind, value = decode_command(cmd, params)

        # While waiting for RUN ACK, ignore unrelated packets (e.g., GETPOS) and keep waiting
        if self._wait_for in ("run_right_ack", "run_left_ack") and kind != "run_started":
            # Log raw packet bytes for traceability
            try:
                hex_payload = " ".join(f"{b:02X}" for b in data)
            except Exception:
                hex_payload = str(data)
            self.status_changed(f"Ignoring out-of-state packet while waiting for RUN ACK: {hex_payload}")
            return
        if self._state == self.S_VERIFY_ZERO and self._wait_for == "lflag_query" and kind != "lflag":
            try:
                hex_payload = " ".join(f"{b:02X}" for b in data)
            except Exception:
                hex_payload = str(data)
            self.status_changed(f"Ignoring out-of-state packet while waiting for SensorL flag: {hex_payload}")
            return
        if self._state == self.S_VERIFY_ZERO and self._wait_for == "rflag_query" and kind != "rflag":
            try:
                hex_payload = " ".join(f"{b:02X}" for b in data)
            except Exception:
                hex_payload = str(data)
            self.status_changed(f"Ignoring out-of-state packet while waiting for SensorR flag: {hex_payload}")
            return

        if kind == "nodeconfig":
            self._handle_nodeconfig(value)
            return
        # Route based on expected wait/state
        if kind == "hunting":
            self._handle_hunting_response(value)
            return
        if kind == "tpos_status":
            self._handle_tpos_status(value)
            return
        if kind == "getpos":
            self._handle_getpos(value)
            return
        if kind == "run_started":
            self._handle_run_started(value)
            return
        if kind == "lflag":
            self._handle_lflag(value)
            return
        if kind == "rflag":
            self._handle_rflag(value)
            return

    # --- Internal helpers ---
    def _emit_command(self, payload: list[int]) -> None:
        self.command_requested(payload)

    def _set_state(self, state: str) -> None:
        self._state = state
        self.status_changed(state)

    def _request_stopmotor(self) -> None:
        self._emit_command(build_stopmotor())

    def _fail(self, reason: str) -> None:
        self._running = False
        self._wait_for = None
        self._set_state(self.S_FAILED)
        self.test_failed(reason)

    def _reset_run_state(self) -> None:
        self._signed_range_1 = None
        self._range_1 = None
        self._signed_range_2 = None
        self._range_2 = None
        self._opposite_pos = None
        self._returned_home_pos = None
        self._middle_target = None
        self._wait_for = None
        self._lflag = None
        self._rflag = None
        self._motion_polarity = None
        self._sensor_profile = None
        self._movement_phase = None
        self._running = False

    @property
    def motion_polarity(self):
        return self._motion_polarity

    @property
    def sensor_profile(self) -> NodeSensorProfile | None:
        return self._sensor_profile

    def _complete_pass(self) -> None:
        self._running = False
        self._wait_for = None
        self._set_state(self.S_PASSED)
        self.test_passed()

    # --- Handlers ---
    def _handle_hunting_response(self, value) -> None:
        if self._state != self.S_HUNTING or self._wait_for != "hunting_ack":
            return
        if value == "accepted":
            polarity = self._require_motion_polarity()
            if polarity is None:
                return
            profile = self._require_sensor_profile()
            if profile is None:
                return
            # Proceed to wait for the configured home sensor.
            self._set_state(self.S_WAIT_HUNTING_SENSOR)
            self._movement_phase = "hunt"
            self._wait_for = "left_sensor" if profile.completion_sensor_for_phase("hunt") == "L" else "right_sensor"
        elif value == "rejected" or value is None:
            self._request_stopmotor()
            self._fail("HUNTING rejected/NACK")
        elif value == "timeout":
            self._request_stopmotor()
            self._fail("HUNTING timeout")

    def _handle_tpos_status(self, value: dict | None) -> None:
        if not isinstance(value, dict) or "event" not in value:
            return
        event = value["event"]
        if event == "Z":
            by = value.get("by")
            if by in ("L", "R"):
                event = by

        if event == "L":
            self.left_flag_changed(True)
        elif event == "R":
            self.right_flag_changed(True)

        if self._state == self.S_WAIT_HUNTING_SENSOR and event in ("L", "R"):
            profile = self._require_sensor_profile()
            if profile is None:
                return
            if profile.matches_phase_sensor("hunt", event):
                self._set_state(self.S_WAIT_ZERO)
                self._wait_for = "zeroed"
                return
            self._request_stopmotor()
            self._fail(f"Wrong sensor event during hunting (expected {self._completion_sensor_for_phase('hunt')}, got {event})")
            return

        if self._state in (self.S_WAIT_LEFT, self.S_WAIT_RIGHT) and self._wait_for in ("left_sensor", "right_sensor") and event in ("L", "R"):
            profile = self._require_sensor_profile()
            if profile is None:
                return
            if self._movement_phase == "outward" and profile.matches_phase_sensor("outward", event):
                self._set_state(self.S_READ_RANGE1)
                self._wait_for = "getpos_r1"
                self._emit_command(build_getpos())
                return
            if self._movement_phase == "return" and profile.matches_phase_sensor("return", event):
                self._set_state(self.S_READ_RANGE2)
                self._wait_for = "getpos_r2"
                self._emit_command(build_getpos())
                return
            self._request_stopmotor()
            self._fail(
                f"Wrong sensor event during {self._movement_phase or 'movement'} move "
                f"(expected {self._completion_sensor_for_phase(self._movement_phase or 'outward')}, got {event})"
            )
            return

        if event == "I":
            # Encoder zeroed
            if self._state == self.S_WAIT_ZERO and self._wait_for == "zeroed":
                self.position_changed(0)
                self._set_state(self.S_VERIFY_ZERO)
                self._wait_for = "getpos_zero"
                self._emit_command(build_getpos())
                return
            # During RUN phases, unexpected reset invalidates measurement
            if self._state in (self.S_RUN_TO_RIGHT, self.S_RUN_TO_LEFT, self.S_WAIT_RIGHT, self.S_WAIT_LEFT):
                self._request_stopmotor()
                self._fail("Encoder reset during RUN invalidates measurement")
                return

        # TPOS middle movement events with explicit position
        if event in ("started", "reached", "no_move"):
            pos = int(value.get("position", 0))
            self.position_changed(pos)
            if self._state == self.S_MOVE_MIDDLE and self._wait_for == "tpos_ack":
                if event == "started":
                    # Wait for completion
                    self._set_state(self.S_WAIT_MIDDLE)
                    self._wait_for = "tpos_complete"
                    return
                if event == "reached":
                    # Immediate completion without a separate 'started' event
                    if self._middle_target is None:
                        self._request_stopmotor()
                        return self._fail("Middle target unknown on reached")
                    if abs(pos - self._middle_target) <= self.cfg.movement_tolerance:
                        self._complete_pass()
                        return
                    self._request_stopmotor()
                    return self._fail("Middle reached but outside tolerance")
                if event == "no_move":
                    # Already at target; accept only if within tolerance
                    if self._middle_target is None:
                        self._request_stopmotor()
                        return self._fail("Middle target unknown on no-move")
                    if abs(pos - self._middle_target) <= self.cfg.movement_tolerance:
                        self._complete_pass()
                        return
                    self._request_stopmotor()
                    return self._fail("Already at middle but outside tolerance")
            elif self._state == self.S_WAIT_MIDDLE and self._wait_for == "tpos_complete":
                if event == "reached":
                    if self._middle_target is None:
                        self._request_stopmotor()
                        return self._fail("Middle target unknown on reached")
                    if abs(pos - self._middle_target) <= self.cfg.movement_tolerance:
                        self._complete_pass()
                        return
                    self._request_stopmotor()
                    return self._fail("Middle reached but outside tolerance")

    def _handle_getpos(self, value) -> None:
        if not isinstance(value, tuple) or len(value) != 2:
            return
        tag, pos = value
        if tag != 'G':
            return
        position = int(pos)
        self.position_changed(position)

        if self._state == self.S_VERIFY_ZERO and self._wait_for == "getpos_zero":
            if abs(position) <= self.cfg.zero_tolerance:
                # Before first RUN, query SensorL first, then SensorR only after SensorL response.
                self._set_state(self.S_VERIFY_ZERO)
                self._wait_for = "lflag_query"
                self.status_changed("Querying SensorL flag: C9 3F")
                self._emit_command(build_lflag_query_payload())
            else:
                self._request_stopmotor()
                self._fail("Zero position outside tolerance")
            return

        if self._state == self.S_READ_RANGE1 and self._wait_for == "getpos_r1":
            # Store opposite sensor position and range_1
            self._signed_range_1 = position
            self._opposite_pos = position
            self._range_1 = abs(position)
            self.range1_changed(self._range_1)
            # Now send RUN in return direction back to reference/home sensor
            polarity = self._require_motion_polarity()
            if polarity is None:
                return
            profile = self._require_sensor_profile()
            if profile is None:
                return
            self._movement_phase = "return"
            run_sign = polarity.sign_to_home()
            run_velocity = self._run_velocity_for_sign(run_sign)
            expected_sensor = profile.completion_sensor_for_phase("return")
            self.status_changed(
                f"Returning home: RUN {run_velocity}, expected sensor {expected_sensor}"
            )
            if expected_sensor == "R":
                self._set_state(self.S_RUN_TO_RIGHT)
                self._emit_command(build_run(run_velocity))
                self._wait_for = "run_right_ack"
            else:
                self._set_state(self.S_RUN_TO_LEFT)
                self._emit_command(build_run(run_velocity))
                self._wait_for = "run_left_ack"
            return

        if self._state == self.S_READ_RANGE2 and self._wait_for == "getpos_r2":
            # Store returned-home position then compute range_2 as delta from opposite_pos
            self._signed_range_2 = position
            self._returned_home_pos = position
            # Compute per corrected plan: range_2 = abs(opposite_pos - returned_home_pos)
            if self._opposite_pos is None:
                self._request_stopmotor()
                return self._fail("Opposite position unavailable for range_2 computation")
            self._range_2 = abs(int(self._opposite_pos) - position)
            self.range2_changed(self._range_2)
            # Compare ranges
            self._set_state(self.S_COMPARE)
            if self._range_1 is None or self._range_2 is None:
                self._request_stopmotor()
                return self._fail("Range values unavailable for compare")
            difference = abs(self._range_1 - self._range_2)
            self.difference_changed(difference)
            if difference > self.cfg.movement_tolerance:
                self._request_stopmotor()
                return self._fail("Range difference exceeds tolerance")
            self._middle_target = self._final_success_target()
            self._set_state(self.S_MOVE_MIDDLE)
            self._wait_for = "tpos_ack"
            self.status_changed(self._final_position_status_text())
            self._emit_command(build_tpos(self._middle_target))
            return

    def _handle_lflag(self, value) -> None:
        if self._state != self.S_VERIFY_ZERO or self._wait_for != "lflag_query":
            return
        if not isinstance(value, int):
            return
        self._lflag = value & 0xFF
        self.status_changed(f"SensorL flag received: 0x{self._lflag:02X}")
        self._wait_for = "rflag_query"
        self.status_changed("Querying SensorR flag: CA 3F")
        self._emit_command(build_rflag_query_payload())

    def _handle_rflag(self, value) -> None:
        if self._state != self.S_VERIFY_ZERO or self._wait_for != "rflag_query":
            return
        if not isinstance(value, int):
            return
        self._rflag = value & 0xFF
        self.status_changed(f"SensorR flag received: 0x{self._rflag:02X}")
        self._wait_for = "check_flags"
        self._maybe_start_first_run()

    def _handle_run_started(self, value) -> None:
        # value is confirmed velocity (int) or None
        if self._state == self.S_RUN_TO_RIGHT and self._wait_for == "run_right_ack":
            if value is None:
                self._request_stopmotor()
                return self._fail("RUN-to-right ACK missing/invalid")
            profile = self._require_sensor_profile()
            if profile is None:
                return
            expected_sensor = profile.completion_sensor_for_phase(self._movement_phase or "outward")
            self._set_state(self.S_WAIT_RIGHT if expected_sensor == "R" else self.S_WAIT_LEFT)
            self._wait_for = "right_sensor" if expected_sensor == "R" else "left_sensor"
            return
        if self._state == self.S_RUN_TO_LEFT and self._wait_for == "run_left_ack":
            if value is None:
                self._request_stopmotor()
                return self._fail("RUN-to-left ACK missing/invalid")
            profile = self._require_sensor_profile()
            if profile is None:
                return
            expected_sensor = profile.completion_sensor_for_phase(self._movement_phase or "outward")
            self._set_state(self.S_WAIT_RIGHT if expected_sensor == "R" else self.S_WAIT_LEFT)
            self._wait_for = "right_sensor" if expected_sensor == "R" else "left_sensor"
            return

    def _handle_nodeconfig(self, value) -> None:
        # Handle C4 3A <nodeconfig> using canonical motion polarity from bits 0 and 1.
        if self._wait_for != "nodeconfig":
            return
        if not isinstance(value, int):
            self._request_stopmotor()
            return self._fail("Invalid NODECONFIG response")
        nodeconfig = value & 0xFF
        try:
            polarity = decode_nodeconfig_motion_polarity(nodeconfig)
        except ValueError as exc:
            self._request_stopmotor()
            return self._fail(str(exc))
        self._motion_polarity = polarity
        if self._node_id is None:
            self._request_stopmotor()
            return self._fail("Node context unavailable for sensor profile resolution.")
        try:
            self._sensor_profile = NodeSensorProfile.from_node_context(self._node_id, polarity)
        except ValueError as exc:
            self._request_stopmotor()
            return self._fail(str(exc))
        self.status_changed(f"NODECONFIG received: 0x{nodeconfig:02X}")
        self.status_changed("Motion polarity:")
        for line in polarity.format_motion_summary().splitlines():
            self.status_changed(f"  {line}")
        self.status_changed("Sensor profile:")
        for line in self._sensor_profile.format_summary().splitlines():
            self.status_changed(line)
        # Proceed to HUNTING
        self._set_state(self.S_HUNTING)
        self.status_changed("Starting HUNTING")
        self._emit_command(build_hunting_timeout(self.cfg.hunt_timeout_ms))
        self._wait_for = "hunting_ack"

    # --- Flag check and first RUN helper ---
    def _maybe_start_first_run(self) -> None:
        if self._wait_for != "check_flags":
            return
        polarity = self._require_motion_polarity()
        if polarity is None:
            return
        profile = self._require_sensor_profile()
        if profile is None:
            return
        # Require both flags
        if self._lflag is None or self._rflag is None:
            return
        # Safety gate: the movement-completion sensor must not reset encoder, and should stop/respond.
        opposite = profile.completion_sensor_for_phase("outward")
        flag_val = self._rflag if opposite == "R" else self._lflag
        # bit1 = reset, bit3 = stop, bit0 = response
        has_reset = bool(flag_val & 0x02)
        has_stop = bool(flag_val & 0x08)
        has_resp = bool(flag_val & 0x01)
        if has_reset or not (has_stop and has_resp):
            self._request_stopmotor()
            self.status_changed("Sensor flag safety check failed")
            self._fail("Opposite sensor flags unsafe for range (need response+stop, no reset)")
            return
        self.status_changed("Sensor flag safety check passed")
        # Safe to start first RUN toward opposite, using the NODECONFIG polarity model.
        self._movement_phase = "outward"
        run_sign = polarity.sign_to_opposite()
        run_velocity = self._run_velocity_for_sign(run_sign)
        self.status_changed(f"Moving outward: RUN {run_velocity}, expected sensor {opposite}")
        if opposite == 'R':
            self._set_state(self.S_RUN_TO_RIGHT)
            self._emit_command(build_run(run_velocity))
            self._wait_for = "run_right_ack"
        else:
            self._set_state(self.S_RUN_TO_LEFT)
            self._emit_command(build_run(run_velocity))
            self._wait_for = "run_left_ack"

    def _require_sensor_profile(self) -> NodeSensorProfile | None:
        if self._sensor_profile is None:
            self._request_stopmotor()
            self._fail("Unsupported or missing node sensor profile. Motion blocked for safety.")
            return None
        return self._sensor_profile

    def _completion_sensor_for_phase(self, phase: str) -> str:
        profile = self._require_sensor_profile()
        if profile is None:
            return "L"
        return profile.completion_sensor_for_phase(phase)

    def _require_motion_polarity(self):
        if self._motion_polarity is None:
            self._request_stopmotor()
            self._fail("Unsupported or missing NODECONFIG. Motion blocked for safety.")
            return None
        return self._motion_polarity

    def _run_velocity_for_sign(self, sign: int) -> int:
        return self.cfg.velocity_left_to_right if int(sign) > 0 else self.cfg.velocity_right_to_left

    def _expected_run_ack_velocity(self) -> int | None:
        polarity = self._motion_polarity
        if polarity is None:
            return None
        if self._movement_phase == "outward":
            return self._run_velocity_for_sign(polarity.sign_to_opposite())
        if self._movement_phase == "return":
            return self._run_velocity_for_sign(polarity.sign_to_home())
        if self._state == self.S_RUN_TO_RIGHT:
            return self.cfg.velocity_left_to_right
        if self._state == self.S_RUN_TO_LEFT:
            return self.cfg.velocity_right_to_left
        return None

    def _run_ack_matches_expected_velocity(self, decoded_value) -> bool:
        if not isinstance(decoded_value, int):
            return False
        expected_velocity = self._expected_run_ack_velocity()
        if expected_velocity is None:
            return False
        return int(decoded_value) == int(expected_velocity)

    @staticmethod
    def _normalized_tpos_event(decoded_value) -> str | None:
        if not isinstance(decoded_value, dict):
            return None
        event = decoded_value.get("event")
        if event == "Z":
            by = decoded_value.get("by")
            return str(by) if by in ("L", "R") else None
        if event in ("L", "R", "I", "started", "reached", "no_move"):
            return str(event)
        return None

    def _accepts_zero_wait_packet(self, decoded_kind: str | None, decoded_value) -> bool:
        return (
            self._state == self.S_WAIT_ZERO
            and decoded_kind == "tpos_status"
            and self._normalized_tpos_event(decoded_value) == "I"
        )

    def _accepts_sensor_wait_packet(self, decoded_kind: str | None, decoded_value) -> bool:
        if decoded_kind != "tpos_status":
            return False
        event = self._normalized_tpos_event(decoded_value)
        if event is None:
            return False
        if self._state == self.S_WAIT_HUNTING_SENSOR:
            return event in ("L", "R")
        if self._state in (self.S_WAIT_LEFT, self.S_WAIT_RIGHT):
            return event in ("L", "R", "I")
        return False

    def _accepts_middle_tpos_packet(self, decoded_kind: str | None, decoded_value, *, require_completion: bool) -> bool:
        if decoded_kind != "tpos_status" or not isinstance(decoded_value, dict):
            return False
        event = self._normalized_tpos_event(decoded_value)
        if require_completion:
            return self._state == self.S_WAIT_MIDDLE and event == "reached"
        return self._state == self.S_MOVE_MIDDLE and event in ("started", "reached", "no_move")

    def _resolved_axis_name(self) -> str:
        return str(get_ml20_node_name(self._node_id) or "").strip().upper()

    def _uses_safe_park_target(self) -> bool:
        return self._resolved_axis_name() in {"Z", "PZ"}

    def _final_success_target(self) -> int:
        if self._uses_safe_park_target():
            return self._SAFE_PARK_TARGET_COUNTS
        if self._opposite_pos is None:
            raise RuntimeError("Opposite position unavailable for middle target computation")
        return int(self._opposite_pos // 2)

    def _final_position_status_text(self) -> str:
        if self._uses_safe_park_target():
            return "Final position: moving to safe position -44000 counts (half revolution from home)"
        return f"Final position: moving to midpoint {int(self._middle_target or 0)}"
