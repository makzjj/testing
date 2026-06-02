import unittest

from gui.workspace.controllers.single_axis_functional_test_controller import (
    SingleAxisFunctionalTestController,
    FunctionalTestConfig,
)
from data.binary_cmd_builders import (
    build_hunting_timeout,
    build_getpos,
    build_run,
    build_tpos,
    build_stopmotor,
)


class Recorder(SingleAxisFunctionalTestController):
    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.commands = []
        self.statuses = []
        self.positions = []
        self.flags = {"L": [], "R": []}
        self.range1 = None
        self.range2 = None
        self.diffs = []
        self.passed = False
        self.failed = False
        self.fail_reason = ""

    def command_requested(self, payload: list[int]) -> None:
        self.commands.append(payload)

    def status_changed(self, text: str) -> None:
        self.statuses.append(text)

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


def pkt(*bytes_):
    return list(bytes_)


class FunctionalControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        cfg = FunctionalTestConfig(
            hunt_timeout_ms=10_000,
            velocity_left_to_right=190,
            velocity_right_to_left=-190,
            zero_tolerance=5,
            range_tolerance=10,
            middle_position_tolerance=5,
        )
        self.ctrl = Recorder(cfg)
        self.ctrl.start(3)

    def test_full_pass_path(self):
        # 1) HUNTING command sent
        self.assertEqual(self.ctrl.commands[-1], build_hunting_timeout(10000))

        # 2) Hunting accepted
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41, 0x00))
        self.assertIn("WAIT_FOR_HUNTING_COMPLETION", self.ctrl.statuses[-1])

        # 3) Left sensor cut
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertIn("WAIT_FOR_ENCODER_INITIALIZATION", self.ctrl.statuses[-1])
        self.assertTrue(self.ctrl.flags["L"][-1])

        # 4) Encoder zeroed
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        # GETPOS requested to verify zero
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

        # 5) Zero getpos within tolerance
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # RUN to right should be requested
        self.assertEqual(self.ctrl.commands[-1], build_run(190))

        # 6) RUN started ACK
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.assertIn("WAIT_FOR_RIGHT_SENSOR", self.ctrl.statuses[-1])

        # 7) Right sensor hit
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.assertEqual(self.ctrl.commands[-1], build_getpos())

        # 8) Read and store range_1 as opposite_pos (+100000)
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x01, 0x86, 0xA0))
        self.assertEqual(self.ctrl.range1, 100000)
        # RUN to left requested
        self.assertEqual(self.ctrl.commands[-1], build_run(-190))

        # 9) RUN-to-left started
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.assertIn("WAIT_FOR_LEFT_SENSOR", self.ctrl.statuses[-1])

        # 10) Left sensor hit
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
        self.assertIn("WAIT_FOR_MIDDLE_COMPLETION", self.ctrl.statuses[-1])

        # 14) Completion reached within tolerance (50002 vs 50000 tol=5)
        fin = 50002
        fin_be = list((fin).to_bytes(4, 'big', signed=True))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('E'), 0x82, *fin_be))

        # STOPMOTOR then PASSED
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.passed)
        self.assertIn("PASSED", self.ctrl.statuses[-1])
        # Ensure no POSITION zero (EA ...) was ever requested
        for cmd in self.ctrl.commands:
            assert not cmd or cmd[0] != 0xEA

    def test_hunting_nack_fails_and_stops(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x4E))  # NACK
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.failed)

    def test_hunting_no_left_sensor_timeout_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.on_timeout()
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())
        self.assertTrue(self.ctrl.failed)

    def test_missing_encoder_init_after_left_sensor_fails(self):
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

    def test_run_to_right_ack_missing_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        # Now expecting RUN ack; timeout -> fail
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_wrong_sensor_during_right_move_fails(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        # Wrong sensor: L occurs instead of R
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_range1_getpos_and_abs_store_then_run_left(self):
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        # supply negative range_1 to ensure abs is used in UI value
        neg = int.from_bytes((-1234).to_bytes(4, 'big', signed=True), 'big', signed=False)
        self.ctrl.handle_runtime_packet(pkt(0x82, (neg>>24)&0xFF, (neg>>16)&0xFF, (neg>>8)&0xFF, neg&0xFF))
        self.assertEqual(self.ctrl.range1, 1234)
        self.assertEqual(self.ctrl.commands[-1], build_run(-190))

    def test_run_to_left_ack_missing_fails(self):
        # Reach state where left ACK is expected
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        # Expecting RUN -190 ack
        self.ctrl.on_timeout()
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_wrong_sensor_during_left_move_fails(self):
        # Reach left move state
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        # Wrong sensor: R occurs instead of L
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_range2_delta_and_mismatch_fails(self):
        # Drive until GETPOS r2 then fail compare
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
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
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_tpos_no_move_outside_tolerance_fails(self):
        # Same as above but outside tol
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        # returned_home_pos = +3 -> middle 2500
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x03))
        # Immediate no-move with pos outside tolerance (2470, tol=5)
        pos = 2470
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('N'), 0x82, *list(pos.to_bytes(4, 'big', signed=True))))
        self.assertTrue(self.ctrl.failed)
        self.assertEqual(self.ctrl.commands[-1], build_stopmotor())

    def test_big_endian_middle_byte_order(self):
        # Drive up to middle command emission and check bytes
        self.ctrl.handle_runtime_packet(pkt(0xC3, 0x41))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('I')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0x00, 0xBE))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('R')))
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x13, 0x88))  # +5000
        self.ctrl.handle_runtime_packet(pkt(0x88, 0x53, 0x84, 0xFF, 0x42))
        self.ctrl.handle_runtime_packet(pkt(0x81, ord('L')))
        # returned_home_pos = 0 -> middle should be +2500
        self.ctrl.handle_runtime_packet(pkt(0x82, 0x00, 0x00, 0x00, 0x00))
        expected = build_tpos(2500)
        self.assertEqual(self.ctrl.commands[-1], expected)

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
