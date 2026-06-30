"""Focused UI tests for the Mechanical workspace page."""

from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import QObject, QPoint, QtMsgType, pyqtSignal, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton, QRadioButton, QWidget

from gui.workspace.pages.mechanical_page import COUNTS_PER_REV, PRESET_COUNTS, MechanicalPage, MotorMovementControlPopup
from gui.workspace.pages.production_parameter_controller import (
    EEPROM_SAVE_COMMAND,
    PARAM_READ,
    PARAM_RESPONSE,
    PID_D_COMMAND,
    PID_D_SUB_ID,
    PID_I_COMMAND,
    PID_I_SUB_ID,
    PID_P_COMMAND,
    PID_P_SUB_ID,
    RAMPDOWN_MINVEL_COMMAND,
    RAMPDOWN_REGION_COMMAND,
    RAMPDOWN_SLOPE_COMMAND,
    RAMPDOWN_STEP_COMMAND,
    RAMPDOWN_TARGET_OFFSET_COMMAND,
    SET_COMMAND_SUFFIX,
    build_pwm_write_payload,
)


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBackendClient:
    def __init__(self, *, connected: bool = True) -> None:
        self._connected = connected
        self.sent_commands: list[tuple[int, list[int]]] = []

    def is_connected(self) -> bool:
        return self._connected

    def send_command_bytes(self, node_id: int, command_bytes: list[int]) -> bytearray:
        payload = list(command_bytes)
        self.sent_commands.append((int(node_id), payload))
        return bytearray([0x25, 0xA5, 0x01, node_id, 0x31, len(payload), *payload])


class _FakeRuntimeWindow(QObject):
    packet_received = pyqtSignal(object)

    def __init__(self, *, connected: bool = True) -> None:
        super().__init__()
        self.backend_client = _FakeBackendClient(connected=connected)


class _FakeBridge:
    def __init__(self, runtime_window: _FakeRuntimeWindow | None = None) -> None:
        self.runtime_window = runtime_window
        self.raw_config = {
            "robot": {
                "axes": {
                    "x": {
                        "node_id": 6,
                        "node_config": "00",
                        "pos_kp": 0.75,
                        "pos_ki": 0.25,
                        "pos_kd": 0.1,
                        "ramp_down_slope": 8,
                        "ramp_down_step": 18,
                        "ramp_down_min_velocity": 28,
                        "ramp_down_target_offset": 38,
                        "ramp_down_region": 48,
                    },
                    "rz": {
                        "node_id": 8,
                        "node_config": "02",
                        "pos_kp": 1.0,
                        "pos_ki": 0.5,
                        "pos_kd": 0.25,
                        "ramp_down_slope": 10,
                        "ramp_down_step": 20,
                        "ramp_down_min_velocity": 30,
                        "ramp_down_target_offset": 40,
                        "ramp_down_region": 50,
                    }
                }
            }
        }

    def get_runtime_window(self, *, create_if_missing: bool = False):
        return self.runtime_window

    def get_runtime_connection_state(self, *, create_if_missing: bool = False) -> tuple[bool, bool]:
        if self.runtime_window is None:
            return False, False
        connected = self.runtime_window.backend_client.is_connected()
        return connected, connected


class MechanicalPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_connected_page(self) -> tuple[MechanicalPage, _FakeRuntimeWindow]:
        runtime_window = _FakeRuntimeWindow(connected=True)
        page = MechanicalPage(_FakeBridge(runtime_window))
        page.resize(1440, 980)
        page.show()
        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        node_combo.setCurrentIndex(5)
        self._app.processEvents()
        return page, runtime_window

    def test_mechanical_page_renders_without_qt_warnings_and_replaces_placeholder_sections(self) -> None:
        messages: list[str] = []

        def _handler(_msg_type, _context, message) -> None:
            if _msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                messages.append(str(message))

        previous = qInstallMessageHandler(_handler)
        try:
            page = MechanicalPage(_FakeBridge())
            page.resize(1440, 980)
            page.show()
            self._app.processEvents()
        finally:
            qInstallMessageHandler(previous)

        self.assertEqual(messages, [])
        labels = {label.text() for label in page.findChildren(QLabel)}
        self.assertNotIn("Motor behaviour", labels)
        self.assertNotIn("Axis motion control", labels)
        self.assertNotIn("Repeatability check", labels)
        self.assertNotIn("Sensor limits & offsets", labels)
        self.assertNotIn("Selected axis snapshot", labels)
        self.assertNotIn("Motor Position", labels)
        self.assertNotIn("Preview mode", labels)
        self.assertIsNotNone(page.findChild(QWidget, "MechanicalSensorPanel"))
        self.assertIsNotNone(page.findChild(QWidget, "MechanicalNodeConfigPanel"))
        self.assertIn("Velocity / Motion Control", labels)
        self.assertIsNotNone(page.findChild(QWidget, "MechanicalVelocityPanel"))
        self.assertIsNotNone(page.findChild(QWidget, "MechanicalPidPanel"))
        self.assertIsNotNone(page.findChild(QWidget, "MechanicalRampPanel"))
        self.assertIn("Mechanical Log", labels)

    def test_mechanical_page_exposes_required_sections_and_local_control_states(self) -> None:
        bridge = _FakeBridge()
        page = MechanicalPage(bridge)
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        self.assertIsNotNone(page.findChild(QComboBox, "MechanicalNodeCombo"))
        self.assertIsNotNone(page.findChild(QPushButton, "MechanicalOpenMotorMovementControlButton"))
        self.assertIsNotNone(page.findChild(QPushButton, "MechanicalClearLogButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalCopyLogButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalRefreshButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalSensorFlagStatusButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalRunPositiveButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalRunNegativeButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalBrakeMotorButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalSetPwmButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalSpeedPidButton"))
        self.assertIsNone(page.findChild(QLineEdit, "MechanicalLeftFlagRawValue"))
        self.assertIsNone(page.findChild(QLineEdit, "MechanicalRightFlagRawValue"))
        self.assertIsNone(page.findChild(QComboBox, "MechanicalLFlagSelector"))
        self.assertIsNone(page.findChild(QComboBox, "MechanicalRFlagSelector"))
        self.assertIsNone(page.findChild(QLineEdit, "MechanicalMotionPolarityValue"))
        self.assertIsNone(page.findChild(QLineEdit, "MechanicalSensorProfileValue"))

        enabled_names = {
            "MechanicalNodeCombo",
            "MechanicalOpenMotorMovementControlButton",
            "MechanicalClearLogButton",
        }
        disabled_names = {
            "MechanicalReadLFlagButton",
            "MechanicalReadRFlagButton",
            "MechanicalReadPwmButton",
            "MechanicalSetPwmRowButton",
            "MechanicalReadRpmButton",
            "MechanicalSetRpmButton",
            "MechanicalHomeHuntButton",
            "MechanicalVelocityStopMotorButton",
            "MechanicalReadNodeConfigButton",
            "MechanicalWriteNodeConfigButton",
            "MechanicalPidReadButton",
            "MechanicalPidWriteButton",
            "MechanicalRampReadButton",
            "MechanicalRampWriteButton",
        }

        for object_name in enabled_names:
            widget = page.findChild(QPushButton, object_name)
            if widget is None:
                widget = page.findChild(QComboBox, object_name)
            self.assertIsNotNone(widget)
            assert widget is not None
            self.assertTrue(widget.isEnabled(), object_name)

        for object_name in disabled_names:
            button = page.findChild(QPushButton, object_name)
            self.assertIsNotNone(button)
            assert button is not None
            self.assertFalse(button.isEnabled(), object_name)

        self.assertIsNone(page.findChild(QPushButton, "MechanicalPidLoadButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalPidSaveButton"))
        self.assertIsNone(page.findChild(QPushButton, "MechanicalSpeedPidButton"))
        self.assertFalse(page.findChild(QComboBox, "MechanicalLeftFlagSettingSelector").isEnabled())
        self.assertFalse(page.findChild(QComboBox, "MechanicalRightFlagSettingSelector").isEnabled())
        self.assertFalse(page.findChild(QComboBox, "MechanicalPolaritySelector").isEnabled())
        self.assertFalse(page.findChild(QComboBox, "MechanicalFlagSelector").isEnabled())
        self.assertFalse(page.findChild(QComboBox, "MechanicalPwmSelectionCombo").isEnabled())
        self.assertFalse(page.findChild(QComboBox, "MechanicalRpmSelectionCombo").isEnabled())

    def test_mechanical_sections_and_log_use_revised_structure(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        row_one = page.findChild(QWidget, "MechanicalRowOne")
        row_two = page.findChild(QWidget, "MechanicalRowTwo")
        row_three = page.findChild(QWidget, "MechanicalRowThree")
        log_panel = page.findChild(type(page.log_panel), "MechanicalLogPanel")
        self.assertIsNotNone(row_one)
        self.assertIsNotNone(row_two)
        self.assertIsNotNone(row_three)
        self.assertIsNotNone(log_panel)

        labels = {label.text() for label in page.findChildren(QLabel)}
        self.assertIn("Left Flag (INT0)", labels)
        self.assertIn("Right Flag (INT1)", labels)
        self.assertIn("Current NODECONFIG", labels)
        self.assertIn("Polarity", labels)
        self.assertIn("Flag Selector", labels)
        self.assertNotIn("Status", labels)
        self.assertNotIn("Preview mode", labels)
        self.assertNotIn("Raw:", labels)
        self.assertNotIn("Sensor Flag Status", labels)
        self.assertNotIn("Sensor Profile", labels)

        button = page.findChild(QPushButton, "MechanicalOpenMotorMovementControlButton")
        assert button is not None
        self.assertEqual(button.text(), "Motor Movement Control")
        self.assertGreaterEqual(button.minimumWidth(), 250)
        self.assertGreaterEqual(button.width() or button.sizeHint().width(), button.minimumWidth())
        self.assertTrue(button.isVisible())

        log_output = page.findChild(type(page.log_output), "MechanicalLogOutput")
        assert log_output is not None
        self.assertGreaterEqual(log_output.minimumHeight(), 230)
        self.assertGreaterEqual(log_panel.minimumWidth(), 400)

        motion_labels = {label.text() for label in page.findChildren(QLabel)}
        self.assertIn("Velocity / Motion Control", motion_labels)
        self.assertIn("Position & Speed PID", motion_labels)
        self.assertIn("Ramp Down Profile", motion_labels)
        button_texts = {button.text() for button in page.findChildren(QPushButton)}
        self.assertIn("Hunt for Zero", button_texts)
        self.assertIn("Stop Motor", button_texts)

        node_panel = page.findChild(QWidget, "MechanicalNodeHeaderPanel")
        sensor_panel = page.findChild(QWidget, "MechanicalSensorPanel")
        config_panel = page.findChild(QWidget, "MechanicalNodeConfigPanel")
        velocity_panel = page.findChild(QWidget, "MechanicalVelocityPanel")
        ramp_panel = page.findChild(QWidget, "MechanicalRampPanel")
        pid_panel = page.findChild(QWidget, "MechanicalPidPanel")
        for widget in (node_panel, sensor_panel, velocity_panel, ramp_panel, pid_panel, log_panel):
            assert widget is not None
            self.assertIn("background: rgba(255, 255, 255, 0.98)", widget.styleSheet())

        node_pos = node_panel.mapTo(page, QPoint(0, 0))
        sensor_pos = sensor_panel.mapTo(page, QPoint(0, 0))
        config_pos = config_panel.mapTo(page, QPoint(0, 0))
        log_pos = log_panel.mapTo(page, QPoint(0, 0))
        velocity_pos = velocity_panel.mapTo(page, QPoint(0, 0))
        ramp_pos = ramp_panel.mapTo(page, QPoint(0, 0))
        pid_pos = pid_panel.mapTo(page, QPoint(0, 0))

        self.assertLess(abs(node_pos.y() - sensor_pos.y()), 20)
        self.assertLess(abs(config_pos.y() - node_pos.y()), 100)
        self.assertLess(abs(velocity_pos.y() - ramp_pos.y()), 20)
        self.assertLess(abs(ramp_pos.y() - pid_pos.y()), 20)
        self.assertGreater(log_pos.y(), velocity_pos.y())
        self.assertLess(node_pos.x(), sensor_pos.x())
        self.assertLess(velocity_pos.x(), ramp_pos.x())
        self.assertLess(ramp_pos.x(), pid_pos.x())
        self.assertTrue(node_panel.isAncestorOf(config_panel))
        self.assertGreaterEqual(log_panel.width(), velocity_panel.width())

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        self.assertEqual(node_combo.count(), 14)
        self.assertEqual(node_combo.itemText(0), "Node 3")
        self.assertEqual(node_combo.itemText(node_combo.count() - 1), "Node 16")
        node_combo.setCurrentIndex(3)
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0000")

        left_flag_selector = page.findChild(QComboBox, "MechanicalLeftFlagSettingSelector")
        right_flag_selector = page.findChild(QComboBox, "MechanicalRightFlagSettingSelector")
        assert left_flag_selector is not None
        assert right_flag_selector is not None
        self.assertEqual([left_flag_selector.itemText(i) for i in range(left_flag_selector.count())], ["1", "9", "11"])
        self.assertEqual([right_flag_selector.itemText(i) for i in range(right_flag_selector.count())], ["1", "9", "11"])

        pwm_radio = page.findChild(QRadioButton, "MechanicalPwmModeRadio")
        rpm_radio = page.findChild(QRadioButton, "MechanicalRpmModeRadio")
        assert pwm_radio is not None
        assert rpm_radio is not None
        self.assertTrue(pwm_radio.isChecked())
        self.assertFalse(rpm_radio.isChecked())
        rpm_radio.click()
        self.assertFalse(pwm_radio.isChecked())
        self.assertTrue(rpm_radio.isChecked())

        pwm_combo = page.findChild(QComboBox, "MechanicalPwmSelectionCombo")
        assert pwm_combo is not None
        self.assertEqual([int(pwm_combo.itemText(i)) for i in range(pwm_combo.count())], list(range(-100, 101, 10)))
        self.assertEqual(pwm_combo.currentText(), "0")

    def test_axis_type_updates_with_selected_node_mapping(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        axis_value = page.findChild(QLineEdit, "MechanicalAxisTypeValue")
        assert node_combo is not None
        assert axis_value is not None

        node_combo.setCurrentIndex(3)  # Node 6
        self._app.processEvents()
        self.assertEqual(axis_value.text(), "X")
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0000")

        node_combo.setCurrentIndex(5)  # Node 8
        self._app.processEvents()
        self.assertEqual(axis_value.text(), "RZ")
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0010")

    def test_safe_reads_send_existing_commands_and_update_ui(self) -> None:
        page, runtime_window = self._build_connected_page()

        get_position_button = page.findChild(QPushButton, "MechanicalGetPositionButton")
        read_pwm_button = page.findChild(QPushButton, "MechanicalReadPwmButton")
        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        assert get_position_button is not None
        assert read_pwm_button is not None
        assert read_nodeconfig_button is not None
        assert read_lflag_button is not None
        assert read_rflag_button is not None

        get_position_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0x82]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x82, "params": [0x00, 0x00, 0x01, 0x00]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentPositionValue").text(), "256")

        read_pwm_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0x85]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x85, "params": [0xFF, 0xF6]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentPwmValue").text(), "-10")

        read_nodeconfig_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0xC4, 0x3F]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC4, "params": [0x3A, 0x02]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0010")
        self.assertEqual(page.findChild(QComboBox, "MechanicalPolaritySelector").currentText(), "Reversed")
        self.assertEqual(page.findChild(QComboBox, "MechanicalFlagSelector").currentText(), "INT0")

        read_lflag_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0xC9, 0x3F]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalLeftFlagStateValue").text(), "0x09")

        read_rflag_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0xCA, 0x3F]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xCA, "params": [0x3A, 0x0B]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalRightFlagStateValue").text(), "0x0B")

    def test_wrong_node_packets_are_ignored_and_timeouts_are_logged(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        assert read_nodeconfig_button is not None
        read_nodeconfig_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 7, "cmd": 0xC4, "params": [0x3A, 0x00]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0010")
        self.assertIn("ignored packet: node=7, payload=C4 3A 00, reason=wrong node 7", page.log_output.toPlainText())

        page._handle_simple_request_timeout()
        self._app.processEvents()
        self.assertIn("Read NODECONFIG timed out", page.log_output.toPlainText())

    def test_mechanical_combos_use_local_light_popup_styling(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        for object_name in (
            "MechanicalNodeCombo",
            "MechanicalPolaritySelector",
            "MechanicalFlagSelector",
            "MechanicalLeftFlagSettingSelector",
            "MechanicalRightFlagSettingSelector",
            "MechanicalPwmSelectionCombo",
            "MechanicalRpmSelectionCombo",
        ):
            combo = page.findChild(QComboBox, object_name)
            assert combo is not None
            style = combo.styleSheet()
            self.assertIn("QAbstractItemView", style, object_name)
            self.assertIn("background: #FFFFFF;", style, object_name)
            self.assertIn("selection-background-color: #FFD7AE;", style, object_name)

    def test_clicking_one_orange_button_does_not_restyle_unrelated_orange_buttons(self) -> None:
        page, _runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        assert read_lflag_button is not None
        assert read_rflag_button is not None

        before_style = read_rflag_button.styleSheet()
        read_lflag_button.click()
        self._app.processEvents()

        self.assertTrue(read_rflag_button.isEnabled())
        self.assertEqual(read_rflag_button.styleSheet(), before_style)
        self.assertIn("QPushButton:pressed", read_lflag_button.styleSheet())

    def test_sensor_reads_keep_independent_left_and_right_state(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        left_value = page.findChild(QLineEdit, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLineEdit, "MechanicalRightFlagStateValue")
        assert read_lflag_button is not None
        assert read_rflag_button is not None
        assert left_value is not None
        assert right_value is not None

        read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "unknown")

        read_rflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xCA, "params": [0x3A, 0x0B]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "0x0B")

    def test_sensor_reads_keep_independent_right_and_left_state(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        left_value = page.findChild(QLineEdit, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLineEdit, "MechanicalRightFlagStateValue")
        assert read_lflag_button is not None
        assert read_rflag_button is not None
        assert left_value is not None
        assert right_value is not None

        read_rflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xCA, "params": [0x3A, 0x0B]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "unknown")
        self.assertEqual(right_value.text(), "0x0B")

        read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "0x0B")

    def test_node_change_resets_sensor_state_and_stale_packets_do_not_overwrite(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        left_value = page.findChild(QLineEdit, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLineEdit, "MechanicalRightFlagStateValue")
        assert read_lflag_button is not None
        assert node_combo is not None
        assert left_value is not None
        assert right_value is not None

        read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")

        read_lflag_button.click()
        node_combo.setCurrentIndex(3)  # Node 6
        self._app.processEvents()
        self.assertEqual(left_value.text(), "unknown")
        self.assertEqual(right_value.text(), "unknown")

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x0B]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "unknown")
        self.assertEqual(right_value.text(), "unknown")

    def test_sensor_led_mapping_uses_orange_for_active_and_grey_for_inactive_or_unknown(self) -> None:
        page = MechanicalPage(_FakeBridge())
        active = page._sensor_state_from_raw(0x09)
        inactive = page._sensor_state_from_raw(0x01)
        unknown = page._sensor_state_from_raw(None)

        self.assertTrue(active["active"])
        self.assertEqual(active["color"], "#F39C12")
        self.assertEqual(active["text"], "0x09")
        self.assertFalse(inactive["active"])
        self.assertEqual(inactive["color"], "#777777")
        self.assertEqual(inactive["text"], "0x01")
        self.assertFalse(unknown["active"])
        self.assertEqual(unknown["color"], "#777777")
        self.assertEqual(unknown["text"], "unknown")

    def test_pwm_write_performs_ack_then_readback_without_enabling_eeprom(self) -> None:
        page, runtime_window = self._build_connected_page()

        pwm_combo = page.findChild(QComboBox, "MechanicalPwmSelectionCombo")
        set_pwm_button = page.findChild(QPushButton, "MechanicalSetPwmRowButton")
        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        assert pwm_combo is not None
        assert set_pwm_button is not None
        assert save_button is not None

        pwm_combo.setCurrentText("20")
        set_pwm_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, build_pwm_write_payload(20)))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x84, "params": [0x53, 0x00, 0x14]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0x85]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x85, "params": [0x00, 0x14]})
        self._app.processEvents()

        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentPwmValue").text(), "20")
        self.assertFalse(save_button.isEnabled())
        self.assertNotIn((8, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]), runtime_window.backend_client.sent_commands)

    def test_pid_and_ramp_read_write_reuse_parameter_definitions_and_gate_eeprom(self) -> None:
        page, runtime_window = self._build_connected_page()

        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        pid_write_button = page.findChild(QPushButton, "MechanicalPidWriteButton")
        ramp_read_button = page.findChild(QPushButton, "MechanicalRampReadButton")
        ramp_write_button = page.findChild(QPushButton, "MechanicalRampWriteButton")
        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        assert pid_read_button is not None
        assert pid_write_button is not None
        assert ramp_read_button is not None
        assert ramp_write_button is not None
        assert save_button is not None

        pid_read_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [PID_P_COMMAND, PARAM_READ, PID_P_SUB_ID]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_P_COMMAND, "params": [PARAM_RESPONSE, PID_P_SUB_ID, 0x00, 0x0F, 0x42, 0x40]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [PID_I_COMMAND, PARAM_READ, PID_I_SUB_ID]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_I_COMMAND, "params": [PARAM_RESPONSE, PID_I_SUB_ID, 0x00, 0x07, 0xA1, 0x20]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [PID_D_COMMAND, PARAM_READ, PID_D_SUB_ID]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_D_COMMAND, "params": [PARAM_RESPONSE, PID_D_SUB_ID, 0x00, 0x03, 0xD0, 0x90]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalPidPValue").text(), "1")
        self.assertEqual(page.findChild(QLineEdit, "MechanicalPidIValue").text(), "0.5")
        self.assertEqual(page.findChild(QLineEdit, "MechanicalPidDValue").text(), "0.25")

        page.findChild(QLineEdit, "MechanicalPidPValue").setText("1.5")
        page.findChild(QLineEdit, "MechanicalPidIValue").setText("0.5")
        page.findChild(QLineEdit, "MechanicalPidDValue").setText("0.25")
        pid_write_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [PID_P_COMMAND, 0x3D, PID_P_SUB_ID, 0x00, 0x16, 0xE3, 0x60]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_P_COMMAND, "params": [PARAM_RESPONSE, PID_P_SUB_ID, 0x00, 0x16, 0xE3, 0x60]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [PID_P_COMMAND, PARAM_READ, PID_P_SUB_ID]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_P_COMMAND, "params": [PARAM_RESPONSE, PID_P_SUB_ID, 0x00, 0x16, 0xE3, 0x60]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_I_COMMAND, "params": [PARAM_RESPONSE, PID_I_SUB_ID, 0x00, 0x07, 0xA1, 0x20]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_D_COMMAND, "params": [PARAM_RESPONSE, PID_D_SUB_ID, 0x00, 0x03, 0xD0, 0x90]})
        self._app.processEvents()
        self.assertTrue(save_button.isEnabled())

        ramp_read_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [RAMPDOWN_SLOPE_COMMAND, PARAM_READ]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_SLOPE_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x0A]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_STEP_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x14]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_MINVEL_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x1E]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_TARGET_OFFSET_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x00, 0x00, 0x28]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_REGION_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x32]})
        self._app.processEvents()

        page.findChild(QLineEdit, "MechanicalRampSlopeValue").setText("11")
        ramp_write_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [RAMPDOWN_SLOPE_COMMAND, 0x3D, 0x00, 0x0B]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_SLOPE_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x0B]})
        self._app.processEvents()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [RAMPDOWN_SLOPE_COMMAND, PARAM_READ]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_SLOPE_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x0B]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_STEP_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x14]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_MINVEL_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x1E]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_TARGET_OFFSET_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x00, 0x00, 0x28]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": RAMPDOWN_REGION_COMMAND, "params": [PARAM_RESPONSE, 0x00, 0x32]})
        self._app.processEvents()
        self.assertTrue(save_button.isEnabled())

        save_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": EEPROM_SAVE_COMMAND, "params": [0x0A]})
        self._app.processEvents()
        self.assertFalse(save_button.isEnabled())

    def test_manual_and_unverified_controls_remain_disabled_when_connected(self) -> None:
        page, _runtime_window = self._build_connected_page()
        for object_name in (
            "MechanicalHomeHuntButton",
            "MechanicalVelocityStopMotorButton",
            "MechanicalReadRpmButton",
            "MechanicalSetRpmButton",
            "MechanicalWriteNodeConfigButton",
        ):
            button = page.findChild(QPushButton, object_name)
            assert button is not None
            self.assertFalse(button.isEnabled(), object_name)

    def test_open_motor_movement_control_opens_popup_with_required_controls(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        open_button = page.findChild(QPushButton, "MechanicalOpenMotorMovementControlButton")
        assert open_button is not None
        open_button.click()
        self._app.processEvents()

        popup = page._movement_popup
        self.assertIsInstance(popup, MotorMovementControlPopup)
        assert popup is not None
        self.assertTrue(popup.isVisible())

        for object_name in (
            "MechanicalPopupRunPositiveButton",
            "MechanicalPopupRunNegativeButton",
            "MechanicalPopupHomeButton",
            "MechanicalPopupStopButton",
            "MechanicalPopupSetPwmButton",
            "MechanicalPopupMoveRelativeButton",
            "MechanicalPopupGetPositionButton",
            "MechanicalPopupNodeCombo",
            "MechanicalPopupRelativePresetCombo",
            "MechanicalPopupRelativeDirectionCombo",
            "MechanicalPopupMoveAbsoluteCheckbox",
            "MechanicalPopupCloseButton",
        ):
            widget = popup.findChild(QPushButton, object_name)
            if widget is None:
                widget = popup.findChild(QComboBox, object_name)
            if widget is None:
                widget = popup.findChild(QCheckBox, object_name)
            self.assertIsNotNone(widget, object_name)

        self.assertTrue(popup.findChild(QComboBox, "MechanicalPopupNodeCombo").isEnabled())
        self.assertTrue(popup.findChild(QComboBox, "MechanicalPopupRelativePresetCombo").isEnabled())
        self.assertTrue(popup.findChild(QComboBox, "MechanicalPopupRelativeDirectionCombo").isEnabled())
        self.assertTrue(popup.findChild(QCheckBox, "MechanicalPopupMoveAbsoluteCheckbox").isEnabled())

        for object_name in (
            "MechanicalPopupRunPositiveButton",
            "MechanicalPopupRunNegativeButton",
            "MechanicalPopupHomeButton",
            "MechanicalPopupStopButton",
            "MechanicalPopupSetPwmButton",
            "MechanicalPopupMoveRelativeButton",
            "MechanicalPopupGetPositionButton",
        ):
            button = popup.findChild(QPushButton, object_name)
            assert button is not None
            self.assertFalse(button.isEnabled(), object_name)

    def test_popup_contains_all_relative_movement_presets(self) -> None:
        popup = MotorMovementControlPopup(node_options=[{"label": "Node 8 - RZ", "node_id": 8, "axis": "RZ"}])
        popup.show()
        self._app.processEvents()

        preset_combo = popup.findChild(QComboBox, "MechanicalPopupRelativePresetCombo")
        assert preset_combo is not None
        self.assertEqual(preset_combo.count(), len(PRESET_COUNTS))
        self.assertEqual(tuple(preset_combo.itemData(index) for index in range(preset_combo.count())), PRESET_COUNTS)
        self.assertIn(f"{COUNTS_PER_REV} - 1 rev", [preset_combo.itemText(index) for index in range(preset_combo.count())])

        direction_combo = popup.findChild(QComboBox, "MechanicalPopupRelativeDirectionCombo")
        relative_value = popup.findChild(type(popup.relative_count_value), "MechanicalPopupRelativeCountValue")
        assert direction_combo is not None
        assert relative_value is not None

        preset_combo.setCurrentIndex(9)
        direction_combo.setCurrentText("Negative")
        self._app.processEvents()
        self.assertEqual(relative_value.text(), f"-{COUNTS_PER_REV}")


if __name__ == "__main__":
    unittest.main()
