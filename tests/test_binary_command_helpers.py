import unittest

from data.binary_cmd_builders import (
    build_hunting_timeout,
    build_getpos,
    build_run,
    build_vel,
    build_tpos,
    build_stopmotor,
    build_nodeconfig_query_payload,
    build_lflag_query_payload,
    build_rflag_query_payload,
    build_motor_current_log_rate_payload,
    build_motor_current_query_payload,
    build_position_log_rate_payload,
)
from data.binary_cmd_parser import (
    decode_command,
    decode_nodeconfig_home_sensor,
    decode_nodeconfig_motion_polarity,
    decode_sensor_flags,
    sensor_flag_allows_range_measurement,
)
from services.node_motion_polarity import NodeMotionPolarity


class BinaryCommandBuilderTests(unittest.TestCase):
    def test_hunting_timeout_builder_10000(self):
        self.assertEqual(build_hunting_timeout(10000), [0xC3, 0x21, 0x27, 0x10])

    def test_hunting_timeout_builder_coerces_and_clamps(self):
        self.assertEqual(build_hunting_timeout("10000"), [0xC3, 0x21, 0x27, 0x10])
        self.assertEqual(build_hunting_timeout(-1), [0xC3, 0x21, 0x00, 0x00])
        self.assertEqual(build_hunting_timeout(999999), [0xC3, 0x21, 0xFF, 0xFF])

    def test_getpos_builder(self):
        self.assertEqual(build_getpos(), [0x82])

    def test_run_builder_positive_190(self):
        self.assertEqual(build_run(190), [0x88, 0x00, 0xBE])

    def test_run_builder_negative_190(self):
        self.assertEqual(build_run(-190), [0x88, 0xFF, 0x42])

    def test_run_builder_clamps_out_of_range_like_legacy_production_builder(self):
        self.assertEqual(build_run(40000), [0x88, 0x7F, 0xFF])
        self.assertEqual(build_run(-40000), [0x88, 0x80, 0x00])
        self.assertEqual(build_run("90"), [0x88, 0x00, 0x5A])

    def test_vel_builder_positive_80(self):
        self.assertEqual(build_vel(80), [0x84, 0x00, 0x50])

    def test_tpos_builder_positive_5000(self):
        self.assertEqual(build_tpos(5000), [0x81, 0x00, 0x00, 0x13, 0x88])

    def test_tpos_builder_negative_value(self):
        val = -123456
        # Compute two's complement big-endian
        expected = [0x81] + list(((val & 0xFFFFFFFF).to_bytes(4, 'big', signed=False)))
        self.assertEqual(build_tpos(val), expected)

    def test_tpos_builder_coerces_int_like_legacy_production_builder(self):
        self.assertEqual(build_tpos("5000"), [0x81, 0x00, 0x00, 0x13, 0x88])

    def test_stopmotor_builder(self):
        self.assertEqual(build_stopmotor(), [0xDD])

    def test_nodeconfig_query_builder(self):
        self.assertEqual(build_nodeconfig_query_payload(), [0xC4, 0x3F])

    def test_flag_query_builders(self):
        self.assertEqual(build_lflag_query_payload(), [0xC9, 0x3F])
        self.assertEqual(build_rflag_query_payload(), [0xCA, 0x3F])

    def test_motor_current_query_builder(self):
        self.assertEqual(build_motor_current_query_payload(), [0xCF, 0x3F])

    def test_motor_current_log_rate_builder(self):
        self.assertEqual(build_motor_current_log_rate_payload(0), [0xD3, 0x3D, 0x00, 0x00])
        self.assertEqual(build_motor_current_log_rate_payload(5), [0xD3, 0x3D, 0x00, 0x05])

    def test_position_log_rate_builder(self):
        self.assertEqual(build_position_log_rate_payload(0), [0xE4, 0x3D, 0x00, 0x00])
        self.assertEqual(build_position_log_rate_payload(5), [0xE4, 0x3D, 0x00, 0x05])


class BinaryCommandParserTests(unittest.TestCase):
    def test_getpos_decode_positive_and_negative(self):
        # Positive
        cmd, val = decode_command(0x82, [0x00, 0x00, 0x01, 0xF4])
        self.assertEqual(cmd, 'getpos')
        self.assertEqual(val, ('G', 500))
        # Negative
        neg = int.from_bytes((-250).to_bytes(4, 'big', signed=True), 'big', signed=False)
        params = [(neg >> 24) & 0xFF, (neg >> 16) & 0xFF, (neg >> 8) & 0xFF, neg & 0xFF]
        cmd2, val2 = decode_command(0x82, params)
        self.assertEqual(cmd2, 'getpos')
        self.assertEqual(val2, ('G', -250))

    def test_run_started_response_decode(self):
        cmd, val = decode_command(0x88, [0x53, 0x84, 0x00, 0xBE])
        self.assertEqual(cmd, 'run_started')
        self.assertEqual(val, 190)

        cmd2, val2 = decode_command(0x88, [0x53, 0x84, 0xFF, 0x42])
        self.assertEqual(cmd2, 'run_started')
        self.assertEqual(val2, -190)

    def test_velocity_ack_decode(self):
        cmd, val = decode_command(0x84, [0x53, 0x00, 0x50])
        self.assertEqual(cmd, 'velocity_ack')
        self.assertEqual(val, 80)

    def test_hunting_status_decode(self):
        self.assertEqual(decode_command(0xC3, [0x41]), ('hunting', 'accepted'))
        self.assertEqual(decode_command(0xC3, [0x4E]), ('hunting', 'rejected'))
        self.assertEqual(decode_command(0xC3, [0x54]), ('hunting', 'timeout'))

    def test_tpos_and_status_events_decode(self):
        # Simple sensor hits
        self.assertEqual(decode_command(0x81, [ord('L')]), ('tpos_status', {'event': 'L'}))
        self.assertEqual(decode_command(0x81, [ord('R')]), ('tpos_status', {'event': 'R'}))
        self.assertEqual(decode_command(0x81, [ord('I')]), ('tpos_status', {'event': 'I'}))

        # Started / Reached / No move with position marker 0x82
        pos = (1234).to_bytes(4, 'big', signed=True)
        self.assertEqual(
            decode_command(0x81, [ord('S'), 0x82] + list(pos)),
            ('tpos_status', {'event': 'started', 'position': 1234}),
        )
        self.assertEqual(
            decode_command(0x81, [ord('E'), 0x82] + list(pos)),
            ('tpos_status', {'event': 'reached', 'position': 1234}),
        )
        self.assertEqual(
            decode_command(0x81, [ord('N'), 0x82] + list(pos)),
            ('tpos_status', {'event': 'no_move', 'position': 1234}),
        )

        # Zeroed by flags
        self.assertEqual(decode_command(0x81, [0x5A, 0x4C]), ('tpos_status', {'event': 'Z', 'by': 'L'}))
        self.assertEqual(decode_command(0x81, [0x5A, 0x52]), ('tpos_status', {'event': 'Z', 'by': 'R'}))

    def test_nodeconfig_decode(self):
        # Valid responses for 0x00..0x03
        for val in (0x00, 0x01, 0x02, 0x03):
            self.assertEqual(decode_command(0xC4, [0x3A, val]), ('nodeconfig', val))
        # Invalid payload
        self.assertEqual(decode_command(0xC4, [0x00]), ('nodeconfig', None))

    def test_flag_and_helpers_decode(self):
        # LFLAG/RFLAG decode
        self.assertEqual(decode_command(0xC9, [0x3A, 0x09]), ('lflag', 0x09))
        self.assertEqual(decode_command(0xCA, [0x3A, 0x0B]), ('rflag', 0x0B))
        # NODECONFIG home sensor comes from the canonical motion model.
        self.assertEqual(decode_nodeconfig_home_sensor(0x00), 'L')
        with self.assertRaisesRegex(ValueError, "Unsupported or missing NODECONFIG 0x01"):
            decode_nodeconfig_home_sensor(0x01)
        polarity_00 = decode_nodeconfig_motion_polarity(0x00)
        self.assertIsInstance(polarity_00, NodeMotionPolarity)
        self.assertEqual(polarity_00.home_sensor, 'L')
        self.assertEqual(polarity_00.opposite_sensor, 'R')
        self.assertEqual(polarity_00.hunting_sign, -1)
        self.assertEqual(polarity_00.outward_sign, 1)
        self.assertEqual(polarity_00.return_home_sign, -1)
        self.assertEqual(polarity_00.negative_run_sensor, 'L')
        self.assertEqual(polarity_00.positive_run_sensor, 'R')
        polarity_02 = decode_nodeconfig_motion_polarity(0x02)
        self.assertEqual(polarity_02.home_sensor, 'L')
        self.assertEqual(polarity_02.opposite_sensor, 'R')
        self.assertEqual(polarity_02.hunting_sign, 1)
        self.assertEqual(polarity_02.outward_sign, -1)
        self.assertEqual(polarity_02.return_home_sign, 1)
        self.assertEqual(polarity_02.negative_run_sensor, 'R')
        self.assertEqual(polarity_02.positive_run_sensor, 'L')
        with self.assertRaisesRegex(ValueError, "Unsupported or missing NODECONFIG 0x01"):
            decode_nodeconfig_motion_polarity(0x01)
        with self.assertRaisesRegex(ValueError, "Unsupported or missing NODECONFIG 0x03"):
            decode_nodeconfig_motion_polarity(0x03)
        # Sensor flag parser
        f1 = decode_sensor_flags(0x01)
        self.assertTrue(f1['send_response'])
        self.assertFalse(f1['zero_reset'])
        self.assertFalse(f1['stop_motor'])
        f9 = decode_sensor_flags(0x09)
        self.assertTrue(f9['send_response'] and f9['stop_motor'] and not f9['zero_reset'])
        fb = decode_sensor_flags(0x0B)
        self.assertTrue(fb['send_response'] and fb['stop_motor'] and fb['zero_reset'])
        # Range measurement gate
        self.assertTrue(sensor_flag_allows_range_measurement(0x09))
        self.assertFalse(sensor_flag_allows_range_measurement(0x0B))

    def test_motor_current_decode(self):
        self.assertEqual(decode_command(0xCF, [0x3A, 0x04, 0xD2]), ("motor_current_mA", 1234))
        self.assertEqual(decode_command(0xCF, [0xCF, 0x04, 0xD2]), ("motor_current_mA", 1234))
        self.assertEqual(decode_command(0xCF, [0x04, 0xD2]), ("motor_current_mA", 1234))
        self.assertEqual(decode_command(0xCF, [0x3A, 0x04]), ("motor_current_mA", None))


if __name__ == '__main__':
    unittest.main()
