"""Focused UI tests for the Mechanical workspace page."""

from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import QObject, QPoint, QtMsgType, pyqtSignal, qInstallMessageHandler
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton, QRadioButton, QWidget

from data.binary_cmd_builders import build_run, build_stopmotor
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
        self.node_status = {
            6: {
                "interrupt_state": {
                    "int0": None,
                    "int1": None,
                    "left_cut": None,
                    "right_cut": None,
                    "last_source": None,
                }
            },
            8: {
                "interrupt_state": {
                    "int0": None,
                    "int1": None,
                    "left_cut": None,
                    "right_cut": None,
                    "last_source": None,
                }
            },
            9: {
                "interrupt_state": {
                    "int0": None,
                    "int1": None,
                    "left_cut": None,
                    "right_cut": None,
                    "last_source": None,
                }
            }
        }


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
                    "pz": {
                        "node_id": 9,
                        "node_config": "0010",
                        "pos_kp": 0.9,
                        "pos_ki": 0.45,
                        "pos_kd": 0.2,
                        "ramp_down_slope": 9,
                        "ramp_down_step": 19,
                        "ramp_down_min_velocity": 29,
                        "ramp_down_target_offset": 39,
                        "ramp_down_region": 49,
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

    def get_runtime_node_interrupt_state(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        if self.runtime_window is None:
            return {
                "node_id": int(node_id),
                "int0": None,
                "int1": None,
                "left_cut": None,
                "right_cut": None,
                "last_source": None,
                "left_state": "unknown",
                "right_state": "unknown",
            }
        state = self.runtime_window.node_status.get(int(node_id), {}).get("interrupt_state", {})
        left_cut = state.get("left_cut")
        right_cut = state.get("right_cut")
        return {
            "node_id": int(node_id),
            "int0": state.get("int0"),
            "int1": state.get("int1"),
            "left_cut": left_cut,
            "right_cut": right_cut,
            "last_source": state.get("last_source"),
            "left_state": "cut" if left_cut is True else "not_cut" if left_cut is False else "unknown",
            "right_state": "cut" if right_cut is True else "not_cut" if right_cut is False else "unknown",
        }

    def get_runtime_node_motion_polarity(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        node_id = int(node_id)
        if node_id == 6:
            return {
                "node_id": 6,
                "known": True,
                "source": "config",
                "nodeconfig_raw": 0x00,
                "home_sensor": "L",
                "opposite_sensor": "R",
                "hunting_sign": -1,
                "outward_sign": 1,
                "return_home_sign": -1,
                "negative_run_sensor": "L",
                "positive_run_sensor": "R",
            }
        if node_id == 8:
            return {
                "node_id": 8,
                "known": True,
                "source": "config",
                "nodeconfig_raw": 0x02,
                "home_sensor": "L",
                "opposite_sensor": "R",
                "hunting_sign": 1,
                "outward_sign": -1,
                "return_home_sign": 1,
                "negative_run_sensor": "R",
                "positive_run_sensor": "L",
            }
        if node_id == 9:
            return {
                "node_id": 9,
                "known": True,
                "source": "config",
                "nodeconfig_raw": 0x02,
                "home_sensor": "L",
                "opposite_sensor": "R",
                "hunting_sign": 1,
                "outward_sign": -1,
                "return_home_sign": 1,
                "negative_run_sensor": "R",
                "positive_run_sensor": "L",
            }
        return {
            "node_id": node_id,
            "known": False,
            "source": None,
            "nodeconfig_raw": None,
            "home_sensor": None,
            "opposite_sensor": None,
            "hunting_sign": None,
            "outward_sign": None,
            "return_home_sign": None,
            "negative_run_sensor": None,
            "positive_run_sensor": None,
        }


class _FakeReleaseWatchHelper:
    def __init__(self) -> None:
        self.is_active = False
        self.start_calls: list[tuple[int, str]] = []
        self.stop_calls: list[str] = []
        self.sent_queries: list[list[int]] = []
        self._on_released = None
        self._on_timeout = None
        self._on_stopped = None
        self._node_id: int | None = None
        self._sensor: str | None = None

    def start_release_watch(
        self,
        node_id: int,
        expected_sensor: str,
        send_query,
        *,
        on_released=None,
        on_timeout=None,
        on_stopped=None,
    ) -> bool:
        if self.is_active:
            return False
        self.is_active = True
        self.start_calls.append((int(node_id), str(expected_sensor)))
        self._node_id = int(node_id)
        self._sensor = str(expected_sensor)
        self._on_released = on_released
        self._on_timeout = on_timeout
        self._on_stopped = on_stopped
        send_query([0xD8, 0x3F])
        self.sent_queries.append([0xD8, 0x3F])
        return True

    def stop_release_watch(self, reason: str = "cancelled") -> bool:
        if not self.is_active:
            return False
        self.is_active = False
        self.stop_calls.append(str(reason))
        if self._on_stopped is not None and self._node_id is not None and self._sensor is not None:
            self._on_stopped(self._node_id, self._sensor, str(reason))
        return True

    def trigger_released(self) -> None:
        if self._on_released is None or self._node_id is None or self._sensor is None:
            return
        self.is_active = False
        if self._on_stopped is not None:
            self._on_stopped(self._node_id, self._sensor, "released")
        self._on_released(self._node_id, self._sensor)

    def trigger_timeout(self) -> None:
        if self._on_timeout is None or self._node_id is None or self._sensor is None:
            return
        self.is_active = False
        if self._on_stopped is not None:
            self._on_stopped(self._node_id, self._sensor, "timeout")
        self._on_timeout(self._node_id, self._sensor)


class MechanicalPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_connected_page(self, *, node_id: int = 8) -> tuple[MechanicalPage, _FakeRuntimeWindow]:
        runtime_window = _FakeRuntimeWindow(connected=True)
        page = MechanicalPage(_FakeBridge(runtime_window))
        page.resize(1440, 980)
        page.show()
        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        node_combo.setCurrentIndex(int(node_id) - 3)
        self._app.processEvents()
        return page, runtime_window

    def _open_connected_popup(self, *, node_id: int = 8) -> tuple[MechanicalPage, _FakeRuntimeWindow, MotorMovementControlPopup]:
        page, runtime_window = self._build_connected_page(node_id=node_id)
        open_button = page.findChild(QPushButton, "MechanicalOpenMotorMovementControlButton")
        assert open_button is not None
        open_button.click()
        self._app.processEvents()
        popup = page._movement_popup
        assert popup is not None
        return page, runtime_window, popup

    def _build_center_viewport_page(self, *, connected: bool = False) -> tuple[MechanicalPage, _FakeRuntimeWindow | None]:
        runtime_window = _FakeRuntimeWindow(connected=True) if connected else None
        page = MechanicalPage(_FakeBridge(runtime_window))
        page.resize(1070, 940)
        page.show()
        self._app.processEvents()
        if connected:
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
        self.assertIsNone(page.findChild(QLabel, "PageTitle"))
        self.assertIsNone(page.findChild(QLabel, "PageSubtitle"))

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
        self.assertTrue(page.findChild(QComboBox, "MechanicalPolaritySelector").isEnabled())
        self.assertTrue(page.findChild(QComboBox, "MechanicalFlagSelector").isEnabled())
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
        self.assertIn("Actual NODECONFIG", labels)
        self.assertIn("Pending NODECONFIG", labels)
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
        self.assertTrue(button.isVisible())
        sensor_panel = page.findChild(QWidget, "MechanicalSensorPanel")
        assert sensor_panel is not None
        self.assertTrue(sensor_panel.isAncestorOf(button))

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

    def test_sensor_status_header_keeps_button_inside_card_and_aligned_with_node_header(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        node_panel = page.findChild(QWidget, "MechanicalNodeHeaderPanel")
        sensor_panel = page.findChild(QWidget, "MechanicalSensorPanel")
        button = page.findChild(QPushButton, "MechanicalOpenMotorMovementControlButton")
        header_row = page.findChild(QWidget, "MechanicalSensorHeaderRow")
        assert node_panel is not None
        assert sensor_panel is not None
        assert button is not None
        assert header_row is not None

        node_title = next(
            label for label in page.findChildren(QLabel)
            if label.text() == "Node Header" and node_panel.isAncestorOf(label)
        )
        sensor_title = next(
            label for label in page.findChildren(QLabel)
            if label.text() == "Sensor Status" and sensor_panel.isAncestorOf(label)
        )

        self.assertTrue(sensor_panel.isAncestorOf(button))
        self.assertTrue(sensor_panel.isAncestorOf(header_row))
        self.assertLess(abs(sensor_title.mapTo(page, QPoint(0, 0)).y() - node_title.mapTo(page, QPoint(0, 0)).y()), 4)
        self.assertLess(abs(sensor_title.mapTo(page, QPoint(0, 0)).y() - button.mapTo(page, QPoint(0, 0)).y()), 12)
        self.assertGreater(button.mapTo(page, QPoint(0, 0)).x(), sensor_title.mapTo(page, QPoint(0, 0)).x())
        sensor_right = sensor_panel.mapTo(page, QPoint(0, 0)).x() + sensor_panel.width()
        button_right = button.mapTo(page, QPoint(0, 0)).x() + button.width()
        self.assertLessEqual(button_right, sensor_right + 1)
        self.assertLessEqual(abs(node_panel.height() - sensor_panel.height()), 1)

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        self.assertEqual(node_combo.count(), 14)
        self.assertEqual(node_combo.itemText(0), "Node 3")
        self.assertEqual(node_combo.itemText(node_combo.count() - 1), "Node 16")
        node_combo.setCurrentIndex(3)
        self._app.processEvents()
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue").text(), "0000")
        self.assertEqual(page.findChild(QLineEdit, "MechanicalPendingNodeconfigValue").text(), "0000")

        left_flag_selector = page.findChild(QComboBox, "MechanicalLeftFlagSettingSelector")
        right_flag_selector = page.findChild(QComboBox, "MechanicalRightFlagSettingSelector")
        nodeconfig_flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        nodeconfig_polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        assert left_flag_selector is not None
        assert right_flag_selector is not None
        assert nodeconfig_flag_selector is not None
        assert nodeconfig_polarity_selector is not None
        self.assertEqual([left_flag_selector.itemText(i) for i in range(left_flag_selector.count())], ["1", "9", "11"])
        self.assertEqual([right_flag_selector.itemText(i) for i in range(right_flag_selector.count())], ["1", "9", "11"])
        self.assertEqual([nodeconfig_flag_selector.itemText(i) for i in range(nodeconfig_flag_selector.count())], ["Left / INT0", "Right / INT1"])
        self.assertEqual([nodeconfig_polarity_selector.itemText(i) for i in range(nodeconfig_polarity_selector.count())], ["Negative", "Positive"])
        self.assertIsNotNone(page.findChild(QPushButton, "MechanicalLeftFlagWriteButton"))
        self.assertIsNotNone(page.findChild(QPushButton, "MechanicalRightFlagWriteButton"))

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

    def test_node_header_layout_uses_required_vertical_order(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        axis_value = page.findChild(QLineEdit, "MechanicalAxisTypeValue")
        current_nodeconfig = page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue")
        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        read_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        write_button = page.findChild(QPushButton, "MechanicalWriteNodeConfigButton")
        assert node_combo is not None
        assert axis_value is not None
        assert current_nodeconfig is not None
        assert flag_selector is not None
        assert polarity_selector is not None
        assert read_button is not None
        assert write_button is not None

        node_pos = node_combo.mapTo(page, QPoint(0, 0))
        axis_pos = axis_value.mapTo(page, QPoint(0, 0))
        config_pos = current_nodeconfig.mapTo(page, QPoint(0, 0))
        flag_pos = flag_selector.mapTo(page, QPoint(0, 0))
        polarity_pos = polarity_selector.mapTo(page, QPoint(0, 0))
        read_pos = read_button.mapTo(page, QPoint(0, 0))
        write_pos = write_button.mapTo(page, QPoint(0, 0))

        self.assertLess(abs(node_pos.y() - axis_pos.y()), 24)
        self.assertGreater(flag_pos.y(), config_pos.y())
        self.assertGreater(polarity_pos.y(), flag_pos.y())
        self.assertGreater(read_pos.y(), polarity_pos.y())
        self.assertLess(abs(read_pos.y() - write_pos.y()), 20)

    def test_nodeconfig_selectors_are_enabled_and_write_remains_disabled(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        write_button = page.findChild(QPushButton, "MechanicalWriteNodeConfigButton")
        assert flag_selector is not None
        assert polarity_selector is not None
        assert write_button is not None

        self.assertTrue(flag_selector.isEnabled())
        self.assertTrue(polarity_selector.isEnabled())
        self.assertFalse(write_button.isEnabled())

    def test_nodeconfig_pending_updates_only_bit_zero_for_flag_selector(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()
        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        node_combo.setCurrentIndex(5)  # Node 8 -> 0010 baseline
        self._app.processEvents()

        actual = page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue")
        pending = page.findChild(QLineEdit, "MechanicalPendingNodeconfigValue")
        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        unsaved = page.findChild(QLabel, "MechanicalNodeconfigUnsavedIndicator")
        assert actual is not None
        assert pending is not None
        assert flag_selector is not None
        assert polarity_selector is not None
        assert unsaved is not None

        self.assertEqual(actual.text(), "0010")
        self.assertEqual(pending.text(), "0010")
        self.assertFalse(unsaved.isVisible())

        flag_selector.setCurrentIndex(1)
        self._app.processEvents()
        self.assertEqual(actual.text(), "0010")
        self.assertEqual(pending.text(), "0011")
        self.assertEqual(polarity_selector.currentText(), "Positive")
        self.assertTrue(unsaved.isVisible())

    def test_nodeconfig_pending_updates_only_bit_one_for_polarity(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        actual = page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue")
        pending = page.findChild(QLineEdit, "MechanicalPendingNodeconfigValue")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        assert actual is not None
        assert pending is not None
        assert polarity_selector is not None

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        node_combo.setCurrentIndex(3)  # Node 6 -> 0000 baseline
        self._app.processEvents()
        self.assertEqual(actual.text(), "0000")

        polarity_selector.setCurrentIndex(1)
        self._app.processEvents()
        self.assertEqual(actual.text(), "0000")
        self.assertEqual(pending.text(), "0010")

    def test_nodeconfig_pending_preserves_bits_two_and_three_from_actual(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page._apply_nodeconfig_display(0x0C)
        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        pending = page.findChild(QLineEdit, "MechanicalPendingNodeconfigValue")
        assert flag_selector is not None
        assert polarity_selector is not None
        assert pending is not None

        flag_selector.setCurrentIndex(1)
        polarity_selector.setCurrentIndex(1)
        self._app.processEvents()
        self.assertEqual(pending.text(), "1111")

    def test_nodeconfig_pending_changes_do_not_send_commands_or_change_unrelated_button_state(self) -> None:
        page, runtime_window = self._build_connected_page()
        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        assert flag_selector is not None
        assert polarity_selector is not None
        assert read_lflag_button is not None
        assert pid_read_button is not None

        before_sent = list(runtime_window.backend_client.sent_commands)
        before_lflag = (read_lflag_button.isEnabled(), read_lflag_button.styleSheet())
        before_pid = (pid_read_button.isEnabled(), pid_read_button.styleSheet())

        flag_selector.setCurrentIndex(1)
        polarity_selector.setCurrentIndex(1)
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, before_sent)
        self.assertEqual((read_lflag_button.isEnabled(), read_lflag_button.styleSheet()), before_lflag)
        self.assertEqual((pid_read_button.isEnabled(), pid_read_button.styleSheet()), before_pid)

    def test_read_nodeconfig_resets_pending_to_actual_and_clears_unsaved_state(self) -> None:
        page, runtime_window = self._build_connected_page()
        read_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        flag_selector = page.findChild(QComboBox, "MechanicalFlagSelector")
        polarity_selector = page.findChild(QComboBox, "MechanicalPolaritySelector")
        actual = page.findChild(QLineEdit, "MechanicalCurrentNodeconfigValue")
        pending = page.findChild(QLineEdit, "MechanicalPendingNodeconfigValue")
        unsaved = page.findChild(QLabel, "MechanicalNodeconfigUnsavedIndicator")
        assert read_button is not None
        assert flag_selector is not None
        assert polarity_selector is not None
        assert actual is not None
        assert pending is not None
        assert unsaved is not None

        flag_selector.setCurrentIndex(1)
        self._app.processEvents()
        self.assertTrue(unsaved.isVisible())

        read_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC4, "params": [0x3A, 0x02]})
        self._app.processEvents()

        self.assertEqual(actual.text(), "0010")
        self.assertEqual(pending.text(), "0010")
        self.assertEqual(flag_selector.currentText(), "Left / INT0")
        self.assertEqual(polarity_selector.currentText(), "Positive")
        self.assertFalse(unsaved.isVisible())

    def test_sensor_status_rows_show_state_selector_and_write_controls_without_clipping(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        left_row = page.findChild(QWidget, "MechanicalLeftFlagRow")
        right_row = page.findChild(QWidget, "MechanicalRightFlagRow")
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
        left_selector = page.findChild(QComboBox, "MechanicalLeftFlagSettingSelector")
        right_selector = page.findChild(QComboBox, "MechanicalRightFlagSettingSelector")
        left_write = page.findChild(QPushButton, "MechanicalLeftFlagWriteButton")
        right_write = page.findChild(QPushButton, "MechanicalRightFlagWriteButton")
        assert left_row is not None
        assert right_row is not None
        assert left_value is not None
        assert right_value is not None
        assert left_selector is not None
        assert right_selector is not None
        assert left_write is not None
        assert right_write is not None

        for widget, row in (
            (left_value, left_row),
            (right_value, right_row),
            (left_selector, left_row),
            (right_selector, right_row),
            (left_write, left_row),
            (right_write, right_row),
        ):
            self.assertTrue(row.isAncestorOf(widget))
            self.assertGreater(widget.width() or widget.sizeHint().width(), 0)

    def test_sensor_status_rows_use_two_line_structure(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        for prefix in ("Left", "Right"):
            row = page.findChild(QWidget, f"Mechanical{prefix}FlagRow")
            led = page.findChild(QLabel, f"Mechanical{prefix}FlagLed")
            title = page.findChild(QLabel, f"Mechanical{prefix}FlagRowTitle")
            state_label = page.findChild(QLabel, f"Mechanical{prefix}FlagRowStateLabel")
            setting_label = page.findChild(QLabel, f"Mechanical{prefix}FlagRowSettingLabel")
            selector = page.findChild(QComboBox, f"Mechanical{prefix}FlagSettingSelector")
            write_button = page.findChild(QPushButton, f"Mechanical{prefix}FlagWriteButton")
            assert row is not None
            assert led is not None
            assert title is not None
            assert state_label is not None
            assert setting_label is not None
            assert selector is not None
            assert write_button is not None

            title_pos = title.mapTo(page, QPoint(0, 0))
            led_pos = led.mapTo(page, QPoint(0, 0))
            state_pos = state_label.mapTo(page, QPoint(0, 0))
            setting_pos = setting_label.mapTo(page, QPoint(0, 0))
            selector_pos = selector.mapTo(page, QPoint(0, 0))
            write_pos = write_button.mapTo(page, QPoint(0, 0))

            self.assertLess(led_pos.y(), state_pos.y())
            self.assertLess(title_pos.y(), state_pos.y())
            self.assertGreater(state_pos.y(), title_pos.y())
            self.assertGreater(setting_pos.y(), title_pos.y())
            self.assertGreater(selector_pos.y(), title_pos.y())
            self.assertGreater(write_pos.y(), title_pos.y())
            self.assertGreater(state_pos.x(), led_pos.x())

    def test_clicking_node_header_read_does_not_focus_or_highlight_sensor_status_display(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        assert read_lflag_button is not None
        assert read_nodeconfig_button is not None
        assert left_value is not None

        read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(left_value.focusPolicy(), left_value.focusPolicy().NoFocus)

        read_nodeconfig_button.click()
        self._app.processEvents()
        self.assertFalse(left_value.hasFocus())
        self.assertIsNot(page.focusWidget(), left_value)
        self.assertEqual(left_value.text(), "0x09")

    def test_mechanical_top_row_and_lower_utility_row_stay_side_by_side(self) -> None:
        page = MechanicalPage(_FakeBridge())
        page.resize(1440, 980)
        page.show()
        self._app.processEvents()

        node_panel = page.findChild(QWidget, "MechanicalNodeHeaderPanel")
        sensor_panel = page.findChild(QWidget, "MechanicalSensorPanel")
        velocity_panel = page.findChild(QWidget, "MechanicalVelocityPanel")
        ramp_panel = page.findChild(QWidget, "MechanicalRampPanel")
        pid_panel = page.findChild(QWidget, "MechanicalPidPanel")
        log_panel = page.findChild(QWidget, "MechanicalLogPanel")
        assert node_panel is not None
        assert sensor_panel is not None
        assert velocity_panel is not None
        assert ramp_panel is not None
        assert pid_panel is not None
        assert log_panel is not None

        node_pos = node_panel.mapTo(page, QPoint(0, 0))
        sensor_pos = sensor_panel.mapTo(page, QPoint(0, 0))
        velocity_pos = velocity_panel.mapTo(page, QPoint(0, 0))
        ramp_pos = ramp_panel.mapTo(page, QPoint(0, 0))
        pid_pos = pid_panel.mapTo(page, QPoint(0, 0))
        log_pos = log_panel.mapTo(page, QPoint(0, 0))

        self.assertLess(abs(node_pos.y() - sensor_pos.y()), 20)
        self.assertLess(abs(velocity_pos.y() - ramp_pos.y()), 20)
        self.assertLess(abs(ramp_pos.y() - pid_pos.y()), 20)
        self.assertGreater(log_pos.y(), velocity_pos.y())

    def test_mechanical_layout_fits_center_viewport_without_horizontal_overflow(self) -> None:
        page, _runtime_window = self._build_center_viewport_page()
        viewport_width = page.viewport().width()

        widgets = [
            page.findChild(QWidget, "MechanicalNodeHeaderPanel"),
            page.findChild(QWidget, "MechanicalSensorPanel"),
            page.findChild(QWidget, "MechanicalVelocityPanel"),
            page.findChild(QWidget, "MechanicalRampPanel"),
            page.findChild(QWidget, "MechanicalPidPanel"),
            page.findChild(QWidget, "MechanicalLogPanel"),
        ]
        for widget in widgets:
            assert widget is not None
            pos = widget.mapTo(page.viewport(), QPoint(0, 0))
            self.assertGreaterEqual(pos.x(), 0)
            self.assertLessEqual(pos.x() + widget.width(), viewport_width + 1, widget.objectName())

    def test_sensor_status_controls_fit_within_card_bounds_at_center_viewport(self) -> None:
        page, _runtime_window = self._build_center_viewport_page()
        sensor_panel = page.findChild(QWidget, "MechanicalSensorPanel")
        assert sensor_panel is not None
        panel_pos = sensor_panel.mapTo(page.viewport(), QPoint(0, 0))
        panel_right = panel_pos.x() + sensor_panel.width()

        for object_name in (
            "MechanicalOpenMotorMovementControlButton",
            "MechanicalLeftFlagSettingSelector",
            "MechanicalRightFlagSettingSelector",
            "MechanicalLeftFlagWriteButton",
            "MechanicalRightFlagWriteButton",
        ):
            widget = page.findChild(QWidget, object_name)
            assert widget is not None
            pos = widget.mapTo(page.viewport(), QPoint(0, 0))
            self.assertLessEqual(pos.x() + widget.width(), panel_right + 1, object_name)

    def test_lower_utility_cards_share_same_row_and_fit_viewport_at_center_width(self) -> None:
        page, _runtime_window = self._build_center_viewport_page()
        viewport_width = page.viewport().width()
        velocity_panel = page.findChild(QWidget, "MechanicalVelocityPanel")
        ramp_panel = page.findChild(QWidget, "MechanicalRampPanel")
        pid_panel = page.findChild(QWidget, "MechanicalPidPanel")
        assert velocity_panel is not None
        assert ramp_panel is not None
        assert pid_panel is not None

        velocity_pos = velocity_panel.mapTo(page.viewport(), QPoint(0, 0))
        ramp_pos = ramp_panel.mapTo(page.viewport(), QPoint(0, 0))
        pid_pos = pid_panel.mapTo(page.viewport(), QPoint(0, 0))

        self.assertLess(abs(velocity_pos.y() - ramp_pos.y()), 20)
        self.assertLess(abs(ramp_pos.y() - pid_pos.y()), 20)
        for widget, pos in ((velocity_panel, velocity_pos), (ramp_panel, ramp_pos), (pid_panel, pid_pos)):
            self.assertLessEqual(pos.x() + widget.width(), viewport_width + 1, widget.objectName())

    def test_velocity_controls_keep_label_value_action_alignment_at_center_width(self) -> None:
        page, _runtime_window = self._build_center_viewport_page()
        pwm_radio = page.findChild(QRadioButton, "MechanicalPwmModeRadio")
        current_pwm = page.findChild(QLineEdit, "MechanicalCurrentPwmValue")
        read_pwm = page.findChild(QPushButton, "MechanicalReadPwmButton")
        selected_pwm = page.findChild(QComboBox, "MechanicalPwmSelectionCombo")
        set_pwm = page.findChild(QPushButton, "MechanicalSetPwmRowButton")
        assert pwm_radio is not None
        assert current_pwm is not None
        assert read_pwm is not None
        assert selected_pwm is not None
        assert set_pwm is not None

        pwm_radio_pos = pwm_radio.mapTo(page.viewport(), QPoint(0, 0))
        current_pwm_pos = current_pwm.mapTo(page.viewport(), QPoint(0, 0))
        read_pwm_pos = read_pwm.mapTo(page.viewport(), QPoint(0, 0))
        selected_pwm_pos = selected_pwm.mapTo(page.viewport(), QPoint(0, 0))
        set_pwm_pos = set_pwm.mapTo(page.viewport(), QPoint(0, 0))

        self.assertLess(abs(current_pwm_pos.x() - selected_pwm_pos.x()), 20)
        self.assertLess(abs(read_pwm_pos.x() - set_pwm_pos.x()), 20)
        self.assertLess(pwm_radio_pos.x(), current_pwm_pos.x())
        self.assertLess(current_pwm_pos.x(), read_pwm_pos.x())

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
        self.assertEqual(page.findChild(QComboBox, "MechanicalPolaritySelector").currentText(), "Positive")
        self.assertEqual(page.findChild(QComboBox, "MechanicalFlagSelector").currentText(), "Left / INT0")

        read_lflag_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0xC9, 0x3F]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLabel, "MechanicalLeftFlagStateValue").text(), "0x09")

        read_rflag_button.click()
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0xCA, 0x3F]))
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xCA, "params": [0x3A, 0x0B]})
        self._app.processEvents()
        self.assertEqual(page.findChild(QLabel, "MechanicalRightFlagStateValue").text(), "0x0B")

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
        self.assertNotIn("ignored: another request is already in progress", page.log_output.toPlainText())

    def test_read_pwm_changes_only_its_local_pending_state(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_pwm_button = page.findChild(QPushButton, "MechanicalReadPwmButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        assert read_pwm_button is not None
        assert read_lflag_button is not None
        assert read_nodeconfig_button is not None
        assert save_button is not None

        before_lflag_style = read_lflag_button.styleSheet()
        before_nodeconfig_style = read_nodeconfig_button.styleSheet()
        before_save_style = save_button.styleSheet()
        read_pwm_button.click()
        self._app.processEvents()

        pending = page._pending_request
        assert pending is not None
        self.assertEqual(pending.family, "parameter")
        self.assertEqual(pending.action, "read")
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [0x85]))
        self.assertFalse(read_pwm_button.isEnabled())
        self.assertEqual(read_pwm_button.text(), "Reading...")
        self.assertTrue(read_lflag_button.isEnabled())
        self.assertTrue(read_nodeconfig_button.isEnabled())
        self.assertEqual(read_lflag_button.styleSheet(), before_lflag_style)
        self.assertEqual(read_nodeconfig_button.styleSheet(), before_nodeconfig_style)
        self.assertEqual(save_button.styleSheet(), before_save_style)

    def test_read_pwm_response_restores_only_read_pwm(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_pwm_button = page.findChild(QPushButton, "MechanicalReadPwmButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        assert read_pwm_button is not None
        assert read_lflag_button is not None

        read_pwm_button.click()
        self._app.processEvents()
        self.assertFalse(read_pwm_button.isEnabled())
        self.assertTrue(read_lflag_button.isEnabled())

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x85, "params": [0x00, 0x14]})
        self._app.processEvents()

        self.assertTrue(read_pwm_button.isEnabled())
        self.assertEqual(read_pwm_button.text(), "Read PWM")
        self.assertTrue(read_lflag_button.isEnabled())
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentPwmValue").text(), "20")

    def test_blocked_second_click_does_not_visually_alter_unrelated_controls(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        assert read_lflag_button is not None
        assert read_rflag_button is not None
        assert pid_read_button is not None

        before_rflag_style = read_rflag_button.styleSheet()
        before_pid_style = pid_read_button.styleSheet()
        read_lflag_button.click()
        self._app.processEvents()
        command_count = len(runtime_window.backend_client.sent_commands)
        read_rflag_button.click()
        self._app.processEvents()

        self.assertEqual(len(runtime_window.backend_client.sent_commands), command_count)
        self.assertTrue(read_rflag_button.isEnabled())
        self.assertTrue(pid_read_button.isEnabled())
        self.assertEqual(read_rflag_button.styleSheet(), before_rflag_style)
        self.assertEqual(pid_read_button.styleSheet(), before_pid_style)
        self.assertIn("Another Mechanical request is still pending.", page.log_output.toPlainText())

    def test_timeout_clears_only_matching_pending_action(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
        assert read_nodeconfig_button is not None
        assert read_rflag_button is not None
        assert left_value is not None
        assert right_value is not None

        page.read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "unknown")

        read_nodeconfig_button.click()
        self._app.processEvents()
        self.assertIsNotNone(page._pending_request)

        page._handle_simple_request_timeout()
        self._app.processEvents()

        self.assertIsNone(page._pending_request)
        self.assertTrue(read_nodeconfig_button.isEnabled())
        self.assertEqual(read_nodeconfig_button.text(), "Read")
        self.assertTrue(read_rflag_button.isEnabled())
        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "unknown")
        self.assertIn("Read NODECONFIG timed out", page.log_output.toPlainText())

    def test_read_lflag_does_not_alter_other_button_state_or_style(self) -> None:
        page, _runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        read_nodeconfig_button = page.findChild(QPushButton, "MechanicalReadNodeConfigButton")
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        ramp_read_button = page.findChild(QPushButton, "MechanicalRampReadButton")
        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        assert read_lflag_button is not None
        assert read_rflag_button is not None
        assert read_nodeconfig_button is not None
        assert pid_read_button is not None
        assert ramp_read_button is not None
        assert save_button is not None

        before = {
            read_rflag_button: (read_rflag_button.styleSheet(), read_rflag_button.isEnabled()),
            read_nodeconfig_button: (read_nodeconfig_button.styleSheet(), read_nodeconfig_button.isEnabled()),
            pid_read_button: (pid_read_button.styleSheet(), pid_read_button.isEnabled()),
            ramp_read_button: (ramp_read_button.styleSheet(), ramp_read_button.isEnabled()),
            save_button: (save_button.styleSheet(), save_button.isEnabled()),
        }

        read_lflag_button.click()
        self._app.processEvents()

        for button, (style, enabled) in before.items():
            self.assertEqual(button.isEnabled(), enabled)
            self.assertEqual(button.styleSheet(), style)

    def test_sensor_reads_keep_independent_left_and_right_state(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
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
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
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
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
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

    def test_sensor_readbacks_update_state_without_lighting_leds_orange(self) -> None:
        page, runtime_window = self._build_connected_page()

        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        read_rflag_button = page.findChild(QPushButton, "MechanicalReadRFlagButton")
        left_value = page.findChild(QLabel, "MechanicalLeftFlagStateValue")
        right_value = page.findChild(QLabel, "MechanicalRightFlagStateValue")
        left_selector = page.findChild(QComboBox, "MechanicalLeftFlagSettingSelector")
        right_selector = page.findChild(QComboBox, "MechanicalRightFlagSettingSelector")
        left_led = page.findChild(QLabel, "MechanicalLeftFlagLed")
        right_led = page.findChild(QLabel, "MechanicalRightFlagLed")
        assert read_lflag_button is not None
        assert read_rflag_button is not None
        assert left_value is not None
        assert right_value is not None
        assert left_selector is not None
        assert right_selector is not None
        assert left_led is not None
        assert right_led is not None

        read_lflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        read_rflag_button.click()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xCA, "params": [0x3A, 0x0B]})
        self._app.processEvents()

        self.assertEqual(left_value.text(), "0x09")
        self.assertEqual(right_value.text(), "0x0B")
        self.assertEqual(left_selector.currentText(), "9")
        self.assertEqual(right_selector.currentText(), "11")
        self.assertIn("#777777", left_led.styleSheet())
        self.assertIn("#777777", right_led.styleSheet())

    def test_sensor_led_mapping_uses_runtime_interrupt_state_only(self) -> None:
        page, runtime_window = self._build_connected_page()
        self.assertEqual(page._sensor_display_from_raw(0x09)["text"], "0x09")
        self.assertEqual(page._sensor_display_from_raw(0x01)["text"], "0x01")
        self.assertEqual(page._sensor_display_from_raw(None)["text"], "unknown")
        self.assertFalse(page._sensor_led_state("left")["active"])
        self.assertEqual(page._sensor_led_state("left")["color"], "#777777")

        runtime_window.node_status[8]["interrupt_state"]["left_cut"] = True
        self.assertTrue(page._sensor_led_state("left")["active"])
        self.assertEqual(page._sensor_led_state("left")["color"], "#F39C12")

    def test_runtime_left_interrupt_state_lights_only_left_led(self) -> None:
        page, runtime_window = self._build_connected_page()
        left_led = page.findChild(QLabel, "MechanicalLeftFlagLed")
        right_led = page.findChild(QLabel, "MechanicalRightFlagLed")
        assert left_led is not None
        assert right_led is not None

        runtime_window.node_status[8]["interrupt_state"].update(
            {"left_cut": True, "right_cut": False, "last_source": "tpos_cut"}
        )
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [0x5A, 0x4C]})
        self._app.processEvents()
        self.assertIn("#F39C12", left_led.styleSheet())
        self.assertIn("#777777", right_led.styleSheet())

    def test_runtime_right_interrupt_state_lights_only_right_led(self) -> None:
        page, runtime_window = self._build_connected_page()
        left_led = page.findChild(QLabel, "MechanicalLeftFlagLed")
        right_led = page.findChild(QLabel, "MechanicalRightFlagLed")
        assert left_led is not None
        assert right_led is not None

        runtime_window.node_status[8]["interrupt_state"].update(
            {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}
        )
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [0x5A, 0x52]})
        self._app.processEvents()
        self.assertIn("#777777", left_led.styleSheet())
        self.assertIn("#F39C12", right_led.styleSheet())

    def test_runtime_right_interrupt_state_from_unknown_does_not_block_right_led_display(self) -> None:
        page, runtime_window = self._build_connected_page()
        left_led = page.findChild(QLabel, "MechanicalLeftFlagLed")
        right_led = page.findChild(QLabel, "MechanicalRightFlagLed")
        assert left_led is not None
        assert right_led is not None

        runtime_window.node_status[8]["interrupt_state"].update(
            {"left_cut": False, "right_cut": True, "last_source": "tpos_cut"}
        )
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [0x52]})
        self._app.processEvents()

        self.assertIn("#777777", left_led.styleSheet())
        self.assertIn("#F39C12", right_led.styleSheet())

    def test_d8_runtime_state_preserves_other_side_and_updates_leds(self) -> None:
        page, runtime_window = self._build_connected_page()
        left_led = page.findChild(QLabel, "MechanicalLeftFlagLed")
        right_led = page.findChild(QLabel, "MechanicalRightFlagLed")
        assert left_led is not None
        assert right_led is not None

        runtime_window.node_status[8]["interrupt_state"].update(
            {"left_cut": True, "right_cut": False, "int0": 0, "int1": 1, "last_source": "tpos_cut"}
        )
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x81, "params": [0x5A, 0x4C]})
        self._app.processEvents()
        self.assertIn("#F39C12", left_led.styleSheet())
        self.assertIn("#777777", right_led.styleSheet())

        runtime_window.node_status[8]["interrupt_state"].update(
            {"left_cut": True, "right_cut": False, "int0": 0, "int1": 1, "last_source": "d8_query"}
        )
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xD8, "params": [0x3A, 0x00, 0x01]})
        self._app.processEvents()
        self.assertIn("#F39C12", left_led.styleSheet())
        self.assertIn("#777777", right_led.styleSheet())

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

    def test_save_to_eeprom_remains_untouched_during_other_requests_and_only_pending_during_its_own_flow(self) -> None:
        page, runtime_window = self._build_connected_page()

        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        assert save_button is not None
        assert read_lflag_button is not None

        page._persistent_write_pending = True
        page._update_control_states()
        self.assertTrue(save_button.isEnabled())
        save_style = save_button.styleSheet()

        read_lflag_button.click()
        self._app.processEvents()
        self.assertTrue(save_button.isEnabled())
        self.assertEqual(save_button.styleSheet(), save_style)
        self.assertEqual(page._pending_request.family, "simple_read")

        save_button.click()
        self._app.processEvents()
        self.assertEqual(page._pending_request.family, "simple_read")
        self.assertEqual(save_button.styleSheet(), save_style)
        self.assertIn("Another Mechanical request is still pending.", page.log_output.toPlainText())

        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0xC9, "params": [0x3A, 0x09]})
        self._app.processEvents()
        self.assertTrue(save_button.isEnabled())

        save_button.click()
        self._app.processEvents()
        pending = page._pending_request
        assert pending is not None
        self.assertEqual(pending.family, "eeprom")
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (8, [EEPROM_SAVE_COMMAND, SET_COMMAND_SUFFIX]))
        self.assertFalse(save_button.isEnabled())
        self.assertEqual(save_button.text(), "Saving...")

        page._on_eeprom_save_finished(True, "EEPROM save ACK received.")
        self._app.processEvents()
        self.assertIsNone(page._pending_request)
        self.assertFalse(save_button.isEnabled())
        self.assertEqual(save_button.text(), "Save to EEPROM")

    def test_request_lifecycle_does_not_invoke_page_wide_control_state_update(self) -> None:
        page, runtime_window = self._build_connected_page()
        read_pwm_button = page.findChild(QPushButton, "MechanicalReadPwmButton")
        assert read_pwm_button is not None

        calls: list[str] = []
        original = page._update_control_states

        def _tracked() -> None:
            calls.append("update")
            original()

        page._update_control_states = _tracked  # type: ignore[method-assign]
        read_pwm_button.click()
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x85, "params": [0xFF, 0xF6]})
        self._app.processEvents()

        self.assertEqual(calls, [])

    def test_live_readback_is_not_overwritten_by_generic_refresh_during_read_pwm_response(self) -> None:
        page, runtime_window = self._build_connected_page()
        read_pwm_button = page.findChild(QPushButton, "MechanicalReadPwmButton")
        assert read_pwm_button is not None

        refresh_calls: list[str] = []
        original_refresh = page._refresh_from_selected_node

        def _tracked_refresh() -> None:
            refresh_calls.append("refresh")
            original_refresh()

        page._refresh_from_selected_node = _tracked_refresh  # type: ignore[method-assign]
        read_pwm_button.click()
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": 0x85, "params": [0x00, 0x14]})
        self._app.processEvents()

        self.assertEqual(refresh_calls, [])
        self.assertEqual(page.findChild(QLineEdit, "MechanicalCurrentPwmValue").text(), "20")

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

    def test_pid_write_invalid_input_rejects_locally_without_touching_other_controls(self) -> None:
        page, runtime_window = self._build_connected_page()
        pid_write_button = page.findChild(QPushButton, "MechanicalPidWriteButton")
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        ramp_read_button = page.findChild(QPushButton, "MechanicalRampReadButton")
        assert pid_write_button is not None
        assert pid_read_button is not None
        assert ramp_read_button is not None

        page.findChild(QLineEdit, "MechanicalPidPValue").setText("bad")
        before_sent = list(runtime_window.backend_client.sent_commands)
        before_pid_read = (pid_read_button.isEnabled(), pid_read_button.styleSheet())
        before_ramp_read = (ramp_read_button.isEnabled(), ramp_read_button.styleSheet())

        pid_write_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, before_sent)
        self.assertIsNone(page._pending_request)
        self.assertTrue(pid_write_button.isEnabled())
        self.assertEqual((pid_read_button.isEnabled(), pid_read_button.styleSheet()), before_pid_read)
        self.assertEqual((ramp_read_button.isEnabled(), ramp_read_button.styleSheet()), before_ramp_read)
        self.assertIn("[Mechanical] Write PID rejected:", page.log_output.toPlainText())

    def test_ramp_write_invalid_input_rejects_locally_without_touching_other_controls(self) -> None:
        page, runtime_window = self._build_connected_page()
        ramp_write_button = page.findChild(QPushButton, "MechanicalRampWriteButton")
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        assert ramp_write_button is not None
        assert pid_read_button is not None

        page.findChild(QLineEdit, "MechanicalRampStepValue").setText("256")
        before_sent = list(runtime_window.backend_client.sent_commands)
        before_pid_read = (pid_read_button.isEnabled(), pid_read_button.styleSheet())

        ramp_write_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, before_sent)
        self.assertIsNone(page._pending_request)
        self.assertTrue(ramp_write_button.isEnabled())
        self.assertEqual((pid_read_button.isEnabled(), pid_read_button.styleSheet()), before_pid_read)
        self.assertIn("[Mechanical] Write Ramp Down rejected:", page.log_output.toPlainText())

    def test_pid_write_failed_verification_restores_only_initiating_button_and_does_not_enable_eeprom(self) -> None:
        page, runtime_window = self._build_connected_page()
        pid_write_button = page.findChild(QPushButton, "MechanicalPidWriteButton")
        save_button = page.findChild(QPushButton, "MechanicalSaveToEepromButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        assert pid_write_button is not None
        assert save_button is not None
        assert read_lflag_button is not None

        page.findChild(QLineEdit, "MechanicalPidPValue").setText("1.5")
        page.findChild(QLineEdit, "MechanicalPidIValue").setText("0.5")
        page.findChild(QLineEdit, "MechanicalPidDValue").setText("0.25")
        before_lflag = (read_lflag_button.isEnabled(), read_lflag_button.styleSheet())

        pid_write_button.click()
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_P_COMMAND, "params": [PARAM_RESPONSE, PID_P_SUB_ID, 0x00, 0x16, 0xE3, 0x60]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_I_COMMAND, "params": [PARAM_RESPONSE, PID_I_SUB_ID, 0x00, 0x07, 0xA1, 0x20]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_D_COMMAND, "params": [PARAM_RESPONSE, PID_D_SUB_ID, 0x00, 0x03, 0xD0, 0x90]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_P_COMMAND, "params": [PARAM_RESPONSE, PID_P_SUB_ID, 0x00, 0x0F, 0x42, 0x40]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_I_COMMAND, "params": [PARAM_RESPONSE, PID_I_SUB_ID, 0x00, 0x07, 0xA1, 0x20]})
        self._app.processEvents()
        runtime_window.packet_received.emit({"type": "can_over_uart", "sender": 8, "cmd": PID_D_COMMAND, "params": [PARAM_RESPONSE, PID_D_SUB_ID, 0x00, 0x03, 0xD0, 0x90]})
        self._app.processEvents()

        self.assertIsNone(page._pending_request)
        self.assertTrue(pid_write_button.isEnabled())
        self.assertEqual(pid_write_button.text(), "Write")
        self.assertFalse(save_button.isEnabled())
        self.assertEqual((read_lflag_button.isEnabled(), read_lflag_button.styleSheet()), before_lflag)
        self.assertIn("requested 1.5, read-back 1, FAIL", page.log_output.toPlainText())

    def test_parameter_timeout_restores_only_initiating_button(self) -> None:
        page, _runtime_window = self._build_connected_page()
        pid_read_button = page.findChild(QPushButton, "MechanicalPidReadButton")
        read_lflag_button = page.findChild(QPushButton, "MechanicalReadLFlagButton")
        assert pid_read_button is not None
        assert read_lflag_button is not None

        before_lflag = (read_lflag_button.isEnabled(), read_lflag_button.styleSheet())
        pid_read_button.click()
        self._app.processEvents()
        self.assertFalse(pid_read_button.isEnabled())

        page._handle_simple_request_timeout()
        self._app.processEvents()

        self.assertIsNone(page._pending_request)
        self.assertTrue(pid_read_button.isEnabled())
        self.assertEqual(pid_read_button.text(), "Read")
        self.assertEqual((read_lflag_button.isEnabled(), read_lflag_button.styleSheet()), before_lflag)
        self.assertIn("Read PID timed out", page.log_output.toPlainText())

    def test_manual_and_unverified_controls_remain_disabled_when_connected(self) -> None:
        page, _runtime_window = self._build_connected_page()
        for object_name in (
            "MechanicalHomeHuntButton",
            "MechanicalVelocityStopMotorButton",
            "MechanicalReadRpmButton",
            "MechanicalSetRpmButton",
            "MechanicalWriteNodeConfigButton",
            "MechanicalLeftFlagWriteButton",
            "MechanicalRightFlagWriteButton",
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

    def test_popup_run_positive_starts_release_watch_for_l_cut_when_nodeconfig_maps_positive_away_from_l(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, build_run(100)))
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (6, [0xD8, 0x3F]))
        self.assertEqual(fake_helper.start_calls, [(6, "L")])
        self.assertIn("Release-watch started", page.log_output.toPlainText())

    def test_popup_run_negative_starts_release_watch_for_l_cut_when_nodeconfig_maps_negative_away_from_l(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=8)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_negative_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands[0], (8, build_run(-100)))
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (8, [0xD8, 0x3F]))
        self.assertEqual(fake_helper.start_calls, [(8, "L")])

    def test_popup_run_positive_does_not_start_release_watch_for_l_cut_when_nodeconfig_maps_positive_toward_l(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=8)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, build_run(100))])
        self.assertEqual(fake_helper.start_calls, [])

    def test_popup_run_negative_does_not_start_release_watch_for_l_cut_when_nodeconfig_maps_negative_toward_l(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_negative_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(6, build_run(-100))])
        self.assertEqual(fake_helper.start_calls, [])

    def test_popup_run_does_not_start_release_watch_without_cut_sensor(self) -> None:
        page, runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": False, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, build_run(100))])
        self.assertEqual(fake_helper.start_calls, [])

    def test_popup_run_does_not_start_release_watch_when_interrupt_state_is_unknown(self) -> None:
        page, runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": None, "right_cut": None})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, build_run(100))])
        self.assertEqual(fake_helper.start_calls, [])
        self.assertIn("interrupt state is incomplete", page.log_output.toPlainText())

    def test_popup_run_toward_cut_sensor_does_not_start_release_watch(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=8)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, build_run(100))])
        self.assertEqual(fake_helper.start_calls, [])

    def test_popup_run_skips_release_watch_when_both_sensors_are_cut(self) -> None:
        page, runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": True, "right_cut": True})

        popup.run_negative_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(8, build_run(-100))])
        self.assertEqual(fake_helper.start_calls, [])
        self.assertIn("both sensors are cut", page.log_output.toPlainText())

    def test_popup_run_skips_release_watch_when_nodeconfig_mapping_is_unknown(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        page._bridge.get_runtime_node_motion_polarity = lambda node_id, create_if_missing=False: {  # type: ignore[method-assign]
            "node_id": int(node_id),
            "known": False,
            "source": None,
        }
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands, [(6, build_run(100))])
        self.assertEqual(fake_helper.start_calls, [])
        self.assertIn("NODECONFIG mapping is unknown", page.log_output.toPlainText())

    def test_popup_run_away_from_right_cut_starts_release_watch_when_polarity_confirms_it(self) -> None:
        page, runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[8]["interrupt_state"].update({"left_cut": False, "right_cut": True})
        page._bridge.get_runtime_node_motion_polarity = lambda node_id, create_if_missing=False: {  # type: ignore[method-assign]
            "node_id": int(node_id),
            "known": True,
            "source": "runtime",
            "nodeconfig_raw": 0x01,
            "home_sensor": "R",
            "opposite_sensor": "L",
            "hunting_sign": -1,
            "outward_sign": 1,
            "return_home_sign": -1,
            "negative_run_sensor": "R",
            "positive_run_sensor": "L",
        }

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands[0], (8, build_run(100)))
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (8, [0xD8, 0x3F]))
        self.assertEqual(fake_helper.start_calls, [(8, "R")])

    def test_node9_binary_nodeconfig_allows_tpos_left_cut_then_run_negative_to_start_release_watch(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=9)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[9]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_negative_button.click()
        self._app.processEvents()

        self.assertEqual(runtime_window.backend_client.sent_commands[0], (9, build_run(-100)))
        self.assertEqual(runtime_window.backend_client.sent_commands[1], (9, [0xD8, 0x3F]))
        self.assertEqual(fake_helper.start_calls, [(9, "L")])

    def test_popup_run_does_not_start_release_watch_when_send_path_is_unavailable(self) -> None:
        page, _runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        page._ensure_transport_adapter = lambda node_id: None  # type: ignore[method-assign]

        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(fake_helper.start_calls, [])
        self.assertIn("serial transport is unavailable", page.log_output.toPlainText())

    def test_popup_run_does_not_start_release_watch_without_selected_node(self) -> None:
        page, _runtime_window, popup = self._open_connected_popup()
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        page._popup_selected_node_id = lambda: None  # type: ignore[method-assign]

        page._handle_popup_run_positive_clicked()
        self._app.processEvents()

        self.assertEqual(fake_helper.start_calls, [])
        self.assertIn("no valid connected Mechanical node is selected", page.log_output.toPlainText())

    def test_popup_duplicate_run_does_not_create_overlapping_release_watch(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        popup.run_positive_button.click()
        self._app.processEvents()

        self.assertEqual(fake_helper.start_calls, [(6, "L")])
        self.assertEqual(runtime_window.backend_client.sent_commands[0], (6, build_run(100)))
        self.assertEqual(runtime_window.backend_client.sent_commands[2], (6, build_run(100)))

    def test_release_watch_release_callback_logs_completion(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()
        fake_helper.trigger_released()

        self.assertIn("Release detected for Node 06 sensor L.", page.log_output.toPlainText())

    def test_release_watch_timeout_callback_logs_timeout(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()
        fake_helper.trigger_timeout()

        self.assertIn("Release-watch timeout for Node 06 sensor L.", page.log_output.toPlainText())

    def test_popup_stop_cancels_release_watch_and_sends_stopmotor(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()
        popup.stop_button.click()
        self._app.processEvents()

        self.assertIn("stop", fake_helper.stop_calls)
        self.assertEqual(runtime_window.backend_client.sent_commands[-1], (6, build_stopmotor()))

    def test_selected_node_change_cancels_active_release_watch(self) -> None:
        page, runtime_window, popup = self._open_connected_popup(node_id=6)
        fake_helper = _FakeReleaseWatchHelper()
        page._release_watch_helper = fake_helper
        runtime_window.node_status[6]["interrupt_state"].update({"left_cut": True, "right_cut": False})

        popup.run_positive_button.click()
        self._app.processEvents()

        node_combo = page.findChild(QComboBox, "MechanicalNodeCombo")
        assert node_combo is not None
        node_combo.setCurrentIndex(4)
        self._app.processEvents()

        self.assertIn("node_change", fake_helper.stop_calls)

    def test_popup_run_buttons_enable_for_connected_selected_node(self) -> None:
        page, _runtime_window, popup = self._open_connected_popup()

        self.assertTrue(popup.run_positive_button.isEnabled())
        self.assertTrue(popup.run_negative_button.isEnabled())
        self.assertTrue(popup.stop_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
