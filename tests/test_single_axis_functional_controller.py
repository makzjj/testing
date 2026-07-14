import unittest

from gui.workspace.controllers.single_axis_functional_test_controller import (
    SingleAxisFunctionalTestController,
    FunctionalTestConfig,
)
from data.binary_cmd_builders import (
    build_hunting_timeout,
    build_getpos,
    build_run,
    build_lflag_query_payload,
    build_rflag_query_payload,
    build_tpos,
    build_stopmotor,
)
from data.binary_cmd_parser import decode_nodeconfig_motion_polarity
from services.motion_measurements import (
    SAFE_PARK_TARGET_COUNTS,
    calculate_midpoint_target,
    calculate_outward_range,
    calculate_return_error,
    calculate_return_range,
    calculate_safe_park_target,
)


class Recorder(SingleAxisFunctionalTestController):
    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.commands = []
        self.statuses = []
        self.states = []
        self.positions = []
        self.flags = {"L": [], "R": []}
        self.range1 = None
        self.range2 = None
        self.diffs = []
        self.passed = False
        self.failed = False
        self.fail_reason = ""
        self.aborted = False
        self.abort_reason = ""

    def command_requested(self, payload: list[int]) -> None:
        self.commands.append(payload)

    def status_changed(self, text: str) -> None:
        self.statuses.append(text)

    def state_changed(self, state: str) -> None:
        self.states.append(state)

    def position_changed(self, pos: int) -> None:
        self.positions.append(pos)

    def range1_changed(self, value: int) -> None:
        self.range1 = value

    def range2_changed(self, value: int) -> None:
        self.range2 = value

    def difference_changed(self, value: int) -> None:
        self.diffs.append(value)

    def left_flag_changed(self, active: bool) -> None:
        self.flags["L"].append(active)

    def right_flag_changed(self, active: bool) -> None:
        self.flags["R"].append(active)

    def test_passed(self) -> None:
        self.passed = True

    def test_failed(self, reason: str) -> None:
        self.failed = True
        self.fail_reason = reason

    def test_aborted(self, reason: str) -> None:
        self.aborted = True
        self.abort_reason = reason


def pkt(*bytes_):
    return list(bytes_)


class FunctionalControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = FunctionalTestConfig(
            hunt_timeout_ms=10_000,
            velocity_left_to_right=190,
            velocity_right_to_left=-190,
            zero_tolerance=5,
            movement_tolerance=512,
        )
        self.ctrl = Recorder(cfg)
        self.ctrl.start(3)
        # New flow: controller queries NODECONFIG first. Provide validated home=L mapping (0x00).
        self.assertEqual(self.ctrl.commands[-1], [0xC4, 0x3F])
        self.ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        # After NODECONFIG response, controller should request HUNTING
        self.assertEqual(self.ctrl.commands[-1], build_hunting_timeout(10000))

    def _drive_to_compare(
        self,
        opposite_pos: int,
        returned_home_pos: int,
        ctrl: Recorder | None = None,
        *,
        nodeconfig: int = 0x00,
    ) -> None:
        ctrl = ctrl or self.ctrl
        polarity = decode_nodeconfig_motion_polarity(nodeconfig)
        ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl.handle_runtime_packet(pkt(0x81, ord(polarity.home_sensor)))
        ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(ctrl.commands[-1], build_lflag_query_payload())
        ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.assertEqual(ctrl.commands[-1], build_rflag_query_payload())
        ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl.handle_runtime_packet(pkt(0x81, ord(polarity.opposite_sensor)))
        ctrl.handle_runtime_packet(
            pkt(0x82, (opposite_pos >> 24) & 0xFF, (opposite_pos >> 16) & 0xFF, (opposite_pos >> 8) & 0xFF, opposite_pos & 0xFF)
        )
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl.handle_runtime_packet(pkt(0x81, ord(polarity.home_sensor)))
        returned_be = list((returned_home_pos).to_bytes(4, 'big', signed=True))
        ctrl.handle_runtime_packet(pkt(0x82, *returned_be))

    def _drive_to_zero_verification(self, ctrl: Recorder, home_position: int) -> None:
        ctrl.start(3)
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        self.assertEqual(ctrl.commands[-1], build_hunting_timeout(10000))
        ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl.handle_runtime_packet(pkt(0x82, *list(int(home_position).to_bytes(4, "big", signed=True))))

    def test_motion_measurement_helpers_use_explicit_endpoint_semantics(self):
        self.assertEqual(calculate_outward_range(10, 70), 60)
        self.assertEqual(calculate_outward_range(-10, -70), 60)
        self.assertEqual(calculate_return_range(70, 8), 62)
        self.assertEqual(calculate_return_range(-70, 10), 80)
        self.assertEqual(calculate_return_error(10, 8), 2)
        self.assertEqual(calculate_return_error(-10, 8), 18)
        self.assertEqual(calculate_midpoint_target(10, 71), 40)
        self.assertEqual(calculate_midpoint_target(10, -70), -30)
        self.assertEqual(calculate_safe_park_target("Z", 10, 70), SAFE_PARK_TARGET_COUNTS)
        self.assertEqual(calculate_safe_park_target("PZ", 10, 70), SAFE_PARK_TARGET_COUNTS)
        self.assertEqual(calculate_safe_park_target("X", 10, 71), 40)

    def test_selected_zero_tolerance_boundary_values_pass_and_fail_correctly(self):
        cases = [(-2, True), (2, True), (6, True), (2048, True), (-2048, True), (2049, False), (-2049, False)]
        for home_position, should_pass in cases:
            with self.subTest(home_position=home_position):
                ctrl = Recorder(
                    FunctionalTestConfig(
                        hunt_timeout_ms=10_000,
                        velocity_left_to_right=190,
                        velocity_right_to_left=-190,
                        zero_tolerance=2048,
                        movement_tolerance=512,
                    )
                )
                self._drive_to_zero_verification(ctrl, home_position)
                if should_pass:
                    self.assertNotEqual(ctrl.commands[-1], build_stopmotor())
                    self.assertFalse(ctrl.failed)
                else:
                    self.assertTrue(ctrl.failed)
                    self.assertEqual(ctrl.commands[-1], build_stopmotor())

    def test_zero_verification_uses_selected_ui_tolerance_value(self):
        ctrl = Recorder(
            FunctionalTestConfig(
                hunt_timeout_ms=10_000,
                velocity_left_to_right=190,
                velocity_right_to_left=-190,
                zero_tolerance=2048,
                movement_tolerance=512,
            )
        )
        self._drive_to_zero_verification(ctrl, 6)
        self.assertFalse(ctrl.failed)
        self.assertIn(build_lflag_query_payload(), ctrl.commands)

    def test_zero_reference_flow_stores_explicit_home_position(self):
        self._drive_to_zero_verification(self.ctrl, 4)
        self.assertEqual(self.ctrl._home_pos, 4)

    def test_nonzero_verified_home_uses_explicit_endpoint_range_and_midpoint(self):
        ctrl = Recorder(self.ctrl.cfg)
        ctrl.start(3)
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl.handle_runtime_packet(pkt(0x82, *list((5).to_bytes(4, "big", signed=True))))
        ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        ctrl.handle_runtime_packet(pkt(0x82, *list((100_000).to_bytes(4, "big", signed=True))))
        self.assertEqual(ctrl._home_pos, 5)
        self.assertEqual(ctrl.range1, 99_995)
        self.assertEqual(ctrl.commands[-1], build_run(-190))

        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x82, *list((8).to_bytes(4, "big", signed=True))))
        self.assertEqual(ctrl.range2, 99_992)
        self.assertEqual(ctrl.diffs[-1], 3)
        self.assertEqual(ctrl.commands[-1], build_tpos(50_002))

    def test_abort_by_user_sends_dd_and_ignores_late_packets(self):
        self.ctrl.abort_by_user()
        self.assertTrue(self.ctrl.aborted)
        self.assertFalse(self.ctrl._running)
        self.assertIsNone(self.ctrl._wait_for)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

        cmd_count = len(self.ctrl.commands)
        status_count = len(self.ctrl.statuses)
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.assertEqual(len(self.ctrl.commands), cmd_count)
        self.assertEqual(len(self.ctrl.statuses), status_count)

    def test_restart_after_abort_resets_cleanly(self):
        self.ctrl.abort_by_user()
        self.assertTrue(self.ctrl.aborted)

        self.ctrl.start(4)
        self.assertEqual(self.ctrl.commands[-1], [0xC4, 0x3F])
        self.assertTrue(self.ctrl._running)
        self.assertEqual(self.ctrl._wait_for, "nodeconfig")
        self.assertIsNone(self.ctrl._lflag)
        self.assertIsNone(self.ctrl._rflag)
        self.assertIsNone(self.ctrl._range_1)
        self.assertIsNone(self.ctrl._range_2)
        self.assertIsNone(self.ctrl._middle_target)
        self.assertFalse(self.ctrl.passed)
        self.assertFalse(self.ctrl.failed)

    def test_range_difference_33_passes_with_512_tolerance(self):
        self._drive_to_compare(2_500_797, -33)
        self.assertEqual(self.ctrl.diffs[-1], 33)
        self.assertEqual(self.ctrl.commands[-1], build_tpos(1_250_398))
        self.assertFalse(self.ctrl.failed)

    def test_range_difference_512_passes_with_512_tolerance(self):
        self._drive_to_compare(2_500_000, -512)
        self.assertEqual(self.ctrl.diffs[-1], 512)
        self.assertEqual(self.ctrl.commands[-1], build_tpos(1_250_000))
        self.assertFalse(self.ctrl.failed)

    def test_normal_axis_retains_midpoint_final_target(self):
        self._drive_to_compare(2_500_000, 0)
        self.assertEqual(self.ctrl.commands[-1], build_tpos(1_250_000))
        self.assertIn("Moving to midpoint", self.ctrl.statuses)

    def test_z_axis_uses_safe_park_target_after_successful_validation(self):
        ctrl = Recorder(self.ctrl.cfg)
        ctrl.start(12)
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        self._drive_to_compare(5000, 0, ctrl=ctrl)
        self.assertEqual(ctrl.commands[-1], build_tpos(-44000))
        self.assertIn("Moving to safe position", ctrl.statuses)
        self.assertIn(0, ctrl.positions)

    def test_pz_axis_uses_safe_park_target_after_successful_validation(self):
        ctrl = Recorder(self.ctrl.cfg)
        ctrl.start(9)
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        self._drive_to_compare(5000, 0, ctrl=ctrl)
        self.assertEqual(ctrl.commands[-1], build_tpos(-44000))

    def test_rz_axis_retains_midpoint_final_target(self):
        ctrl = Recorder(self.ctrl.cfg)
        ctrl.start(8)
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        self._drive_to_compare(5000, 0, ctrl=ctrl)
        self.assertEqual(ctrl.commands[-1], build_tpos(2500))

    def test_range_difference_513_fails_and_sends_stop(self):
        self._drive_to_compare(2_500_000, -513)
        self.assertEqual(self.ctrl.diffs[-1], 513)
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_full_pass_path(self):
        # 1) HUNTING command sent
        self.assertEqual(self.ctrl.commands[-1], build_hunting_timeout(10000))

        # 2) Hunting accepted
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41, 0x00))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_HUNTING_SENSOR)

        # 3) Left sensor cut (home)
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_ZERO)
        self.assertTrue(self.ctrl.flags["L"][-1])

        # 4) Encoder zeroed
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        # GETPOS requested to verify zero
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

        # 5) Zero getpos within tolerance
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Flags must be queried sequentially before first RUN
        self.assertEqual(self.ctrl.commands[-1], build_lflag_query_payload())
        # Provide SensorL response first; only then should SensorR be queried
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.assertEqual(self.ctrl.commands[-1], build_rflag_query_payload())
        # Provide SensorR response; only after both should safety check and RUN happen
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # Now RUN outward should be requested first (home -> opposite)
        self.assertEqual(self.ctrl.commands[-1], build_run(190))

        # 6) RUN started ACK
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_RIGHT)

        # 7) Right sensor hit (opposite)
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

        # 8) Read and store range_1 as opposite_pos (+100000)
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x01, 0x86, 0xA0))
        self.assertEqual(self.ctrl.range1, 100000)
        # RUN back home requested
        self.assertEqual(self.ctrl.commands[-1], build_run(-190))

        # 9) RUN-to-right started
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_LEFT)

        # 10) Left sensor hit (return home)
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

        # 11) Read returned_home_pos near zero (+8)
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x08))
        # range_2 = abs(100000 - 8) = 99992, difference = 8
        self.assertEqual(self.ctrl.range2, 99992)
        self.assertEqual(self.ctrl.diffs[-1], 8)

        # 12-13) TPOS to middle = opposite_pos // 2 = 50000 (big-endian)
        middle = 50000
        self.assertEqual(self.ctrl.commands[-1], build_tpos(middle))

        # 13) TPOS immediate started with current pos
        cur = 49990
        cur_be = list((cur).to_bytes(4, 'big', signed=True))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('S'), 0x82, *cur_be))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_MIDDLE)

        # 14) Completion reached within tolerance (50002 vs 50000 tol=5)
        fin = 50002
        fin_be = list((fin).to_bytes(4, 'big', signed=True))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('E'), 0x82, *fin_be))

        # PASS directly after completion
        self.assertTrue(self.ctrl.passed)
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_PASSED)
        self.assertIn("Functional test PASSED", self.ctrl.statuses)
        # Ensure no POSITION zero (EA ...) was ever requested
        for cmd in self.ctrl.commands:
            assert not cmd or cmd[0] != 0xEA

    def test_live_run_ack_minimal_format_is_accepted(self):
        # Drive to first RUN awaiting ACK
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))  # hunting accepted
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))  # home sensor
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))  # encoder init
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))  # zero
        # Provide safe flags then controller will send first RUN (+190)
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # Live ACK format: 88 53 00 BE (no 0x84)
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x00, 0xBE))
        # Should transition to waiting for right sensor
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_RIGHT)

    def test_accepts_workflow_packet_requires_matching_run_ack_velocity(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))

        self.assertEqual(self.ctrl.current_wait_for, "run_right_ack")
        self.assertTrue(self.ctrl.accepts_workflow_packet("run_started", 190, [0x88, 0x53, 0x00, 0xBE]))
        self.assertFalse(self.ctrl.accepts_workflow_packet("run_started", -190, [0x88, 0x53, 0xFF, 0x42]))
        self.assertFalse(self.ctrl.accepts_workflow_packet("getpos", ('G', 0), [0x82, 0x00, 0x00, 0x00, 0x00]))
        self.assertFalse(self.ctrl.accepts_workflow_packet("motor_current_mA", 1234, [0xCF, 0x3A, 0x04, 0xD2]))

    def test_accepts_workflow_packet_keeps_wrong_sensor_relevant_during_active_sensor_wait(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x00, 0xBE))

        self.assertEqual(self.ctrl.current_wait_for, "right_sensor")
        self.assertTrue(self.ctrl.accepts_workflow_packet("tpos_status", {"event": "R"}, [0x81, ord('R')]))
        self.assertTrue(self.ctrl.accepts_workflow_packet("tpos_status", {"event": "L"}, [0x81, ord('L')]))
        self.assertTrue(self.ctrl.accepts_workflow_packet("tpos_status", {"event": "I"}, [0x81, ord('I')]))
        self.assertFalse(
            self.ctrl.accepts_workflow_packet(
                "tpos_status",
                {"event": "reached", "position": 5000},
                [0x81, ord('E'), 0x82, 0x00, 0x00, 0x13, 0x88],
            )
        )

    def test_ignore_getpos_while_waiting_for_run_ack_then_proceed(self):
        # Reach state awaiting first RUN ACK
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # While waiting for RUN ACK, an out-of-state GETPOS arrives — must be ignored
        last_status_count = len(self.ctrl.statuses)
        self.ctrl.handle_runtime_packet(pkt(0x82, 0xFF, 0xFF, 0xFF, 0xFE))
        # No failure; operator log stays clean
        self.assertEqual(len(self.ctrl.statuses), last_status_count)
        self.assertFalse(self.ctrl.failed)
        # Now the valid ACK arrives (live format) and we proceed to wait for left sensor
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x00, 0xBE))
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_RIGHT)

    def test_timeout_waiting_for_run_ack_stops_and_fails(self):
        # Reach state awaiting return RUN ACK (second leg)
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # First leg ack and opposite sensor
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x00, 0xBE))  # +190 live format
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        # Now controller sent RUN back to right; simulate that no ACK comes and timeout fires
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_getpos_is_only_sent_after_encoder_initialized(self):
        # Accept hunting and receive Z-form home sensor (by L)
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, 0x5A, 0x4C))  # 'Z','L'
        # Ensure no GETPOS was sent yet
        self.assertNotEqual(self.ctrl.commands[-1], build_getpos())
        # Now receive encoder initialized 'I' -> GETPOS must be sent immediately
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

    def test_hunting_nack_fails_and_stops(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x4E))  # NACK
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.failed)

    def test_hunting_no_reference_sensor_timeout_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.on_timeout()
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.failed)

    def test_missing_encoder_init_after_reference_sensor_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.on_timeout()
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.failed)

    def test_zero_outside_tolerance_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        # GETPOS returns 10, tolerance 5 -> fail
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x0A))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_first_run_ack_missing_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Expect only SensorL query before any flag response
        self.assertEqual(self.ctrl.commands[-1], build_lflag_query_payload())
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.assertEqual(self.ctrl.commands[-1], build_rflag_query_payload())
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # Now expecting RUN ack; timeout -> fail
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_missing_sensor_l_flag_times_out_and_stops(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(self.ctrl.commands[-1], build_lflag_query_payload())
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_missing_sensor_r_flag_times_out_and_stops(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(self.ctrl.commands[-1], build_lflag_query_payload())
        # SensorL arrives, SensorR is requested, then times out.
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.assertEqual(self.ctrl.commands[-1], build_rflag_query_payload())
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_wrong_command_flag_response_is_ignored_until_timeout(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(self.ctrl.commands[-1], build_lflag_query_payload())
        # Wrong command: SensorR arrives before SensorL.
        cmd_count = len(self.ctrl.commands)
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.assertEqual(len(self.ctrl.commands), cmd_count)
        self.assertEqual(self.ctrl.statuses[-1], "Home position verified: 0 counts")
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_late_flag_packets_after_failure_are_ignored(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        cmd_count = len(self.ctrl.commands)
        status_count = len(self.ctrl.statuses)
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.assertEqual(len(self.ctrl.commands), cmd_count)
        self.assertEqual(len(self.ctrl.statuses), status_count)

    def test_wrong_sensor_during_first_move_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # first leg is R->L, ack packet for negative velocity
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        # Wrong sensor: R occurs instead of L
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_range1_getpos_and_abs_store_then_run_right(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        # supply negative range_1 to ensure abs is used in UI value
        neg = int.from_bytes((-1234).to_bytes(4, 'big', signed=True), 'big', signed=False)
        self.ctrl.handle_runtime_packet(pkt(0x82, (neg>>24)&0xFF, (neg>>16)&0xFF, (neg>>8)&0xFF, neg&0xFF))
        self.assertEqual(self.ctrl.range1, 1234)
        self.assertEqual(self.ctrl.commands[-1], build_run(-190))

    def test_return_run_ack_missing_fails(self):
        # Reach state where home ACK is expected (return to reference L)
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        # Expecting RUN -190 ack
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_wrong_sensor_during_return_move_fails(self):
        # Reach return (right) move state
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        # Wrong sensor: L occurs instead of R
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_range2_delta_and_mismatch_fails(self):
        # Drive until GETPOS r2 then fail compare
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        # returned_home_pos = -5020 -> range_2 = abs(5000 - (-5020)) = 10020
        neg = int.from_bytes((-5020).to_bytes(4, 'big', signed=True), 'big', signed=False)
        self.ctrl.handle_runtime_packet(pkt(0x82, (neg>>24)&0xFF, (neg>>16)&0xFF, (neg>>8)&0xFF, neg&0xFF))
        self.assertEqual(self.ctrl.range2, 10020)
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_tpos_no_move_within_tolerance_passes(self):
        # Up to compare pass with r1=5000 (opposite), returned_home_pos=+3 -> r2=4997, diff=3 => middle=2500
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        # returned_home_pos = +3
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x03))
        # TPOS requested to +2500
        middle = 2500
        self.assertEqual(self.ctrl.commands[-1], build_tpos(middle))
        # Immediate no-move with pos within tolerance (-2498)
        pos = 2498
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('N'), 0x82, *list(pos.to_bytes(4, 'big', signed=True))))
        self.assertTrue(self.ctrl.passed)

    def test_middle_position_tolerance_boundary_uses_shared_value(self):
        ctrl_pass = Recorder(
            FunctionalTestConfig(
                hunt_timeout_ms=10_000,
                velocity_left_to_right=190,
                velocity_right_to_left=-190,
                zero_tolerance=5,
                movement_tolerance=512,
            )
        )
        ctrl_pass.start(3)
        ctrl_pass.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        ctrl_pass.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl_pass.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl_pass.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl_pass.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        ctrl_pass.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        ctrl_pass.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        ctrl_pass.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl_pass.handle_runtime_packet(pkt(0x81, ord('R')))
        ctrl_pass.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        ctrl_pass.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl_pass.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl_pass.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        middle = 2500
        self.assertEqual(ctrl_pass.commands[-1], build_tpos(middle))
        ctrl_pass.handle_runtime_packet(pkt(0x81, ord('N'), 0x82, *list((middle + 512).to_bytes(4, 'big', signed=True))))
        self.assertTrue(ctrl_pass.passed)

        ctrl_fail = Recorder(
            FunctionalTestConfig(
                hunt_timeout_ms=10_000,
                velocity_left_to_right=190,
                velocity_right_to_left=-190,
                zero_tolerance=5,
                movement_tolerance=512,
            )
        )
        ctrl_fail.start(3)
        ctrl_fail.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        ctrl_fail.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl_fail.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl_fail.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl_fail.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        ctrl_fail.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        ctrl_fail.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        ctrl_fail.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl_fail.handle_runtime_packet(pkt(0x81, ord('R')))
        ctrl_fail.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        ctrl_fail.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl_fail.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl_fail.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(ctrl_fail.commands[-1], build_tpos(middle))
        ctrl_fail.handle_runtime_packet(pkt(0x81, ord('N'), 0x82, *list((middle + 513).to_bytes(4, 'big', signed=True))))
        self.assertTrue(ctrl_fail.failed)

    def test_tpos_no_move_outside_tolerance_fails(self):
        # Same as above but outside tolerance for a tighter shared-movement setting.
        ctrl = Recorder(
            FunctionalTestConfig(
                hunt_timeout_ms=10_000,
                velocity_left_to_right=190,
                velocity_right_to_left=-190,
                zero_tolerance=5,
                movement_tolerance=5,
            )
        )
        ctrl.start(3)
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x03))
        pos = 2470
        ctrl.handle_runtime_packet(pkt(0x81, ord('N'), 0x82, *list(pos.to_bytes(4, 'big', signed=True))))
        self.assertTrue(ctrl.failed)
        self.assertEqual(ctrl.commands[-1], build_stopmotor())

    def test_big_endian_middle_byte_order(self):
        # Drive up to middle command emission and check bytes
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags prior to RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        # returned_home_pos = 0 -> middle should be +2500
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        expected = build_tpos(2500)
        self.assertEqual(self.ctrl.commands[-1], expected)

    def test_configurable_left_as_reference_sequence_still_works(self):
        # Node 6 uses the single-sensor profile, so both completions are L.
        cfg = FunctionalTestConfig(
            hunt_timeout_ms=10_000,
            velocity_left_to_right=190,
            velocity_right_to_left=-190,
            zero_tolerance=5,
            range_tolerance=10,
            middle_position_tolerance=5,
            reference_sensor="L",
            opposite_sensor="R",
        )
        ctrl = Recorder(cfg)
        ctrl.start(6)
        # With NODECONFIG flow, expect query first, then respond with 0x00 to
        # emulate legacy Left-home with +190 to opposite and -190 back home.
        self.assertEqual(ctrl.commands[-1], [0xC4, 0x3F])
        ctrl.handle_runtime_packet(pkt(0xC4, 0x3A, 0x00))
        self.assertEqual(ctrl.commands[-1], build_hunting_timeout(10000))
        ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.assertEqual(ctrl.commands[-1], build_getpos())
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Flag queries, then first run L->R (+190)
        ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        self.assertEqual(ctrl.commands[-1], build_run(190))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertEqual(ctrl.commands[-1], build_getpos())
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        # Return L->L (-190)
        self.assertEqual(ctrl.commands[-1], build_run(-190))
        ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x04))
        middle = 2500
        self.assertEqual(ctrl.commands[-1], build_tpos(middle))
        ctrl.handle_runtime_packet(pkt(0x81, ord('E'), 0x82, *list((2502).to_bytes(4, 'big', signed=True))))
        self.assertTrue(ctrl.passed)

    def test_wrong_sensor_events_fail_safely(self):
        # Expect L during hunting, but get R -> fail
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_accept_z_sensor_events_and_fail_on_reset_during_run(self):
        # HUNT accept
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        # Reference via Z-form (e.g., stopped by L flag)
        self.ctrl.handle_runtime_packet(pkt(0x81, 0x5A, 0x4C))  # 'Z','L'
        self.assertEqual(self.ctrl.states[-1], self.ctrl.S_WAIT_ZERO)
        # Zeroed
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.assertEqual(self.ctrl.commands[-1], build_getpos())
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Provide flags and begin RUN
        self.ctrl.handle_runtime_packet(pkt(0xC9, 0x3A, 0x09))
        self.ctrl.handle_runtime_packet(pkt(0xCA, 0x3A, 0x09))
        # RUN ack (toward opposite R)
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        # Unexpected encoder reset during RUN -> should fail
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_any_failure_stops_and_does_not_continue(self):
        # Fail early
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x4E))
        count = len(self.ctrl.commands)
        # Send further packets shouldn't cause new commands beyond STOPMOTOR
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.assertEqual(len(self.ctrl.commands), count)


if __name__ == '__main__':
    unittest.main()
