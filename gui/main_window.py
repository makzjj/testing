# gui/main_window.py
"""Main application window."""
import sys
import os
import time
import collections
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QGroupBox, QLineEdit, QSlider,
    QGridLayout)
from PyQt6.QtCore import Qt, QTimer, QDateTime, pyqtSignal
from PyQt6.QtGui import QPixmap,  QColor, QIcon
from PyQt6.QtWidgets import QStackedWidget

from .serial_monitor import SerialMonitorDialog
from .zposs_plot import ZPOSSPlotWindow
from .tof_plot import ToFPlotWindow
from myconfig.constants import COMMANDS
from myconfig.version import VERSION
from myconfig.constants import NODE_ID_MAPPING

from services import (
    CommunicationLogStore,
    NodeDiscoveryCoordinator,
    RobotBackendClient,
    RuntimePacketEvent,
    RuntimePacketHandler,
    RxLogWriter,
    build_default_node_status,
    connected_node_ids,
    ensure_node_status,
    reset_node_status,
)
from utils.deployment_paths import get_bundle_resource_path, get_runtime_exports_dir
from gui.test_all_dialog import TestAllDialog
from gui.comm_monitor import CommMonitorDialog
from gui.motor_animation_module import MotorAnimationModule
from gui.rp_axis_animation import RpAxisAnimation

# startup / sequencing
COMMUNICATION_START_DELAY = 200      # Delay before starting communication
MCU_QUERY_DELAY_MS = 200
NODE_SCAN_START_DELAY = 600           # Delay before starting node scan
NODE_ADVANCE_DELAY = 500              # Batch discovery window duration
NODE_INFO_REQUEST_DELAY = 200         # Delay before requesting node info
UUID_RETRY_CHECK_DELAY = 200          # Delay before checking UUID retry
NODE_CMD_DELAY_1 = 150                # First command delay
NODE_CMD_DELAY_2 = 300                # Second command delay
NODE_CMD_DELAY_3 = 450                # Third command delay

def get_timestamp():
    return QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")

def get_light_theme(self):
    return """
        QWidget { background-color: #FFFFFF; color: #000000; font-family: Segoe UI; font-size: 10pt; }
        QPushButton { background-color: #F0F0F0; border: 1px solid #C0C0C0; padding: 4px 10px; border-radius: 4px; }
        QPushButton:hover { background-color: #E0E0E0; }
        QPushButton:pressed { background-color: #D0D0D0; }
        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {
            background-color: #FFFFFF; color: #000000;
            border: 1px solid #C0C0C0; padding: 2px; border-radius: 4px;
        }
        QTableWidget { background-color: #FFFFFF; alternate-background-color: #F9F9F9; gridline-color: #DDDDDD; }
        QHeaderView::section {
            background-color: #F2F2F2; padding: 4px; border: 1px solid #DADADA; font-weight: bold;
        }
    """

def get_dark_theme(self):
    return """
        QWidget { background-color: #1E1E1E; color: #DCDCDC; font-family: Segoe UI; font-size: 10pt; }
        QPushButton { background-color: #333; border: 1px solid #555; padding: 4px 10px; border-radius: 4px; color: #EEE; }
        QPushButton:hover { background-color: #444; }
        QPushButton:pressed { background-color: #555; }
        QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {
            background-color: #2A2A2A; color: #FFFFFF;
            border: 1px solid #666; padding: 2px; border-radius: 4px;
        }
        QTableWidget { background-color: #2B2B2B; alternate-background-color: #202020; gridline-color: #555555; }
        QHeaderView::section {
            background-color: #3A3A3A; padding: 4px; border: 1px solid #444; font-weight: bold; color: #EEE;
        }
    """

class MainWindow(QMainWindow):
    packet_received = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        # --- Theme ---
        self.theme = "light"  # Add this line

        # --- Serial communication attributes ---
        self.rx_buffer = bytearray()

        self.backend_client = RobotBackendClient()
        self.communication_log_store = CommunicationLogStore()
        self.comm_log_store = self.communication_log_store
        self.backend_client.serial_connection.set_communication_log_store(self.communication_log_store)
        self.packet_handler = RuntimePacketHandler()
        self.runtime_system_state = {"mcu_version": None}
        self.rx_log_writer: RxLogWriter | None = None
        # Legacy dialogs still expect these attributes while MainWindow is being migrated.
        self.serial_conn = self.backend_client.serial_connection
        self.command_builder = self.backend_client.command_builder
        self.monitor_dialog = SerialMonitorDialog(self)
        self.zposs_plot = ZPOSSPlotWindow(self)
        self.tof_plot = ToFPlotWindow(self)
        self.comm_monitor = CommMonitorDialog(self)
        self.log_file = None
        
        # Disable zposs start/stop until a serial connection is established
        try:
            if hasattr(self.zposs_plot, 'start_action'):
                self.zposs_plot.start_action.setEnabled(False)
            if hasattr(self.zposs_plot, 'stop_action'):
                self.zposs_plot.stop_action.setEnabled(False)
        except Exception:
            pass
        self.test_all_dialog = None  # Initialize variable for the dialog

        # --- Connection state tracking ---
        self.is_connected = False  # Track connection state
        self.scan_active = False  # Track if scanning is active

        # Per-node panels and state
        self.motor_panels = {} # {node_id: MotorAnimationModule}
        self.active_panel = None
        self.init_state = {}     # {node_id: int} 0=Idle, 1=Sent C9, 2=Sent RUN
        self.init_signals = {}   # {node_id: set(['Z', 'I'])}
        self.last_positions = {} # {node_id: int}
        self.m_tpos_done_sent = {} # {node_id: bool}
        self.is_first_auto_move_check = False
        self.waiting_for_s = {}      # node_id -> bool
        self.move_sent_time = {}    # node_id -> float
        self.last_s_time = {}       # node_id -> float
        self.pos_buffer = collections.defaultdict(lambda: collections.deque(maxlen=5))
        self.auto_move_e_timeout = 10.0 # 10 seconds
        self.auto_move_s_timeout = 0.8  # 800 ms
        
        # Scan Continue timing
        self.is_scanning_continue = False
        self.scan_start_reported = False
        self.scan_target_start = 0
        self.scan_target_end = 0
        self.scan_target_node = 0
        self.scan_target_velocity = 0
        self.scan_start_time = 0.0
        
        self.scan_finish_timer = QTimer(self)
        self.scan_finish_timer.setSingleShot(True)
        self.scan_finish_timer.timeout.connect(self.finalize_scan)
        self.scan_last_elapsed = 0.0

        self.setup_ui()
        self.setup_logging()

        self.mcu_version_queried = False  # Track if MCU version already queried
        self.mcu_version = None  # Store the MCU version in shared runtime state

        self.node_discovery_coordinator = NodeDiscoveryCoordinator()

        # --- Node scanning initialization ---
        # Node status table
        # --- Node scanning state ---
        self.current_scan_node = 2
        self.detected_nodes = set()
        self.node_scan_timeout_timer = QTimer(self)
        self.node_scan_timeout_timer.setSingleShot(True)
        self.node_scan_timeout_timer.timeout.connect(self.on_node_scan_timeout)
        self._batch_node_scan_active = False
        self.emergency_stop_active = None

        # Node status monitoring
        self.node_status = {}  # Dictionary to store node status

        # Initialize node status for all possible nodes (2-16, matching legacy defaults)
        self.node_status = build_default_node_status()

        # Create the timer but don't connect it yet
        self.node_status_timer = QTimer()

        self.sys_mode = {"text": "Unknown", "color": "#808080", "blink": 0}
        self.blink_state = True
        self.sys_mode_timer = QTimer(self)
        self.sys_mode_timer.timeout.connect(self.query_sys_mode)
        
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.update_blink)
        self.blink_timer.start(250) # 4Hz tick for 1Hz/3Hz logic
        self.blink_counter = 0

        self.setup_timers()

    @property
    def mcu_version(self):
        """Expose MCU firmware through one runtime-owned state slot."""
        return self.runtime_system_state.get("mcu_version")

    @mcu_version.setter
    def mcu_version(self, value):
        self.runtime_system_state["mcu_version"] = value


    def setup_ui(self):
        title_logo_path = str(get_bundle_resource_path("resources", "biobot_logo.png"))
        self.setWindowIcon(QIcon(title_logo_path))
        self.setWindowTitle(f"BioBot Robot Arm Tester Version: {VERSION}")
        self.resize(1386, 900) # Increased width by 5% (1320 * 1.05)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ================= TOP ROW: SYSTEM INFORMATION =================
        system_group = QGroupBox("System Information")
        system_group.setMaximumHeight(150)
        system_layout = QHBoxLayout(system_group)
        system_layout.setContentsMargins(6, 4, 6, 6)
        system_layout.setSpacing(6)

        system_layout.addWidget(self.create_system_status_panel(), 1)
        system_layout.addWidget(self.create_communication_panel(), 1)
        system_layout.addWidget(self.create_nodes_summary_panel(), 8)
        system_layout.addWidget(self.create_logo_panel(), 0)
        main_layout.addWidget(system_group, 2)

        # ================= MIDDLE ROW: DEBUG SECTION (full width) =================
        debug_group = QGroupBox("Debug")
        debug_layout = QVBoxLayout(debug_group)
        debug_layout.setContentsMargins(8, 8, 8, 8)
        debug_layout.setSpacing(8)

        self.cmd_section = self.create_command_section_widget()
        debug_layout.addWidget(self.cmd_section, 0)

        debug_body_layout = QHBoxLayout()
        debug_body_layout.setSpacing(8)

        self.motor_control_box = self.create_motor_control_box()
        # Set minimum height instead of maximum to prevent squishing
        self.motor_control_box.setMinimumHeight(220)
        # Remove fixed maximum height to allow expansion in full-screen
        debug_body_layout.addWidget(self.motor_control_box, 3)
        
        # Link Node combos (inverse)
        self.target_node_id_combo.currentIndexChanged.connect(self._sync_motion_node_to_command)

        viz_group = QGroupBox("Visualization")
        # Set minimum height instead of maximum to prevent squishing
        viz_group.setMinimumHeight(220)
        # Remove fixed maximum height to allow expansion in full-screen
        viz_layout = QVBoxLayout(viz_group)
        viz_layout.setContentsMargins(8, 8, 8, 8)
        self.viz_stack = QStackedWidget()
        viz_layout.addWidget(self.viz_stack)
        debug_body_layout.addWidget(viz_group, 4)

        debug_layout.addLayout(debug_body_layout, 1)
        main_layout.addWidget(debug_group, 4)

        # ================= BOTTOM ROW: CONSOLE SECTION (full width) =================
        main_layout.addWidget(self.create_console_box(), 4)

        # Initialize default visualization
        self.update_motion_node_label()

    def create_system_status_panel(self):
        group = QGroupBox("Status")
        # Remove setMinimumWidth to allow responsive sizing
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(3)

        status_row = QHBoxLayout()
        self.status_led = QLabel()
        self.status_led.setFixedSize(16, 16)
        self.status_led.setStyleSheet("border-radius: 8px; background-color: #808080;")
        self.status_text_lbl = QLabel("System Status: Unknown")
        self.status_text_lbl.setStyleSheet("font-weight: bold;")
        status_row.addWidget(self.status_led)
        status_row.addWidget(self.status_text_lbl)
        status_row.addStretch()

        self.error_code_lbl = QLabel("Error Code: --")
        self.error_code_lbl.setStyleSheet("font-weight: bold; color: #666666;")
        self.error_detail_lbl = QLabel("Error Detail: --")
        self.error_detail_lbl.setWordWrap(True)
        self.mcu_version_lbl = QLabel("MCU Firmware Version: ")

        layout.addLayout(status_row)
        layout.addWidget(self.error_code_lbl)
        layout.addWidget(self.error_detail_lbl)
        layout.addWidget(self.mcu_version_lbl)
        layout.addStretch()
        return group

    def create_communication_panel(self):
        group = QGroupBox("Communication")
        # Remove setMinimumWidth to allow responsive sizing
        layout = QGridLayout(group)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(3)

        self.port_combo = QComboBox()
        # Remove setMinimumWidth to allow responsive sizing
        self.refresh_ports()

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "230400", "345600"])
        self.baud_combo.setCurrentText("115200")
        self.baud_combo.currentTextChanged.connect(self.on_baud_rate_changed)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.connect_btn.clicked.connect(self.toggle_connection)

        layout.addWidget(QLabel("Serial Port:"), 0, 0)
        layout.addWidget(self.port_combo, 0, 1)
        layout.addWidget(QLabel("Baud Rate:"), 1, 0)
        layout.addWidget(self.baud_combo, 1, 1)
        layout.addWidget(self.connect_btn, 2, 0, 1, 2)
        return group

    def create_nodes_summary_panel(self):
        group = QGroupBox("Robot Arm Nodes")
        # Remove setFixedWidth(760) to allow responsive sizing based on parent container
        layout = QVBoxLayout(group)
        layout.setContentsMargins(6, 4, 6, 6)
        layout.setSpacing(2)

        self.node_status_lbl = QLabel("Connected nodes: None")
        self.node_status_lbl.setStyleSheet("color: red; font-weight: bold;")
        self.node_table = self.create_node_table()

        layout.addWidget(self.node_status_lbl)
        layout.addWidget(self.node_table)
        return group

    def create_logo_panel(self):
        logo_label = QLabel()
        pixmap = QPixmap(str(get_bundle_resource_path("resources", "biobot_logo.png")))
        logo_label.setPixmap(pixmap.scaledToHeight(44, Qt.TransformationMode.SmoothTransformation))
        logo_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Remove setFixedWidth to allow responsive sizing
        return logo_label

    def create_console_box(self):
        console_group = QGroupBox("Console")
        console_layout = QVBoxLayout(console_group)
        console_layout.setContentsMargins(8, 8, 8, 8)
        console_layout.setSpacing(6)

        ctrl_row = QHBoxLayout()
        self.autoscroll_chk = QCheckBox("Auto")
        self.autoscroll_chk.setToolTip("Auto-scroll console output")
        self.autoscroll_chk.setChecked(True)
        self.hide_sys_mode_chk = QCheckBox("Hide Sys")
        self.hide_sys_mode_chk.setToolTip("Hide periodic system status logs")
        self.clear_log_btn = QPushButton("Clear")

        ctrl_row.addWidget(self.autoscroll_chk)
        ctrl_row.addWidget(self.hide_sys_mode_chk)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self.clear_log_btn)
        console_layout.addLayout(ctrl_row)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        # Reduce console log font size a bit to make messages less large
        self.log_box.setStyleSheet("background-color: #f8f9fa; font-family: 'Consolas', monospace; font-size: 9pt;")
        self.clear_log_btn.clicked.connect(self.log_box.clear)
        console_layout.addWidget(self.log_box)
        console_layout.addLayout(self.create_bottom_controls())
        return console_group

    def create_top_bar_comport(self):
        layout = QHBoxLayout()

        # Very compact setup
        port_label = QLabel("Serial Port:")
        port_label.setMaximumWidth(70)

        self.port_combo = QComboBox()
        self.port_combo.setMaximumWidth(140)
        self.refresh_ports()

        # Baud rate selection
        baud_label = QLabel("Baud Rate:")
        baud_label.setMaximumWidth(60)

        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "230400","345600"])
        self.baud_combo.setCurrentText("115200")  # Default to recommended
        self.baud_combo.currentTextChanged.connect(self.on_baud_rate_changed)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setCheckable(True)
        self.connect_btn.setMaximumWidth(100)
        self.connect_btn.clicked.connect(self.toggle_connection)

        logo_label = QLabel()
        # pixmap = QPixmap("resources/biobot_logo.png")  # Adjust path as needed
        pixmap = QPixmap(str(get_bundle_resource_path("resources", "biobot_logo.png")))

        logo_label.setPixmap(pixmap.scaledToHeight(50))
        # logo_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        layout.addWidget(port_label)
        layout.addWidget(self.port_combo)
        layout.addWidget(baud_label)
        layout.addWidget(self.baud_combo)
        layout.addWidget(self.connect_btn)


        layout.addStretch()  # This pushes everything to the left
        layout.addWidget(logo_label)

        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        return layout

    def on_baud_rate_changed(self, baud_str):
        """Update serial connection baud rate when selection changes."""
        try:
            baud_rate = int(baud_str)
            self.backend_client.baudrate = baud_rate
            self.log(f"Baud rate set to: {baud_rate}")
        except ValueError:
            self.log(f"Invalid baud rate: {baud_str}")

    def create_top_bar_mcu_version(self):

        layout = QHBoxLayout()

        self.mcu_version_lbl = QLabel("MCU Version:")
        
        # System status LED
        self.status_led = QLabel()
        self.status_led.setFixedSize(16, 16)
        self.status_led.setStyleSheet("border-radius: 8px; background-color: #808080;")
        self.status_text_lbl = QLabel("System Status: Unknown")
        self.status_text_lbl.setStyleSheet("font-weight: bold;")

        layout.addWidget(self.mcu_version_lbl)
        layout.addStretch(1)
        layout.addWidget(self.status_led)
        layout.addWidget(self.status_text_lbl)
        return layout

    def create_node_status_label(self):
        node_status_label_layout = QHBoxLayout()
        self.node_status_lbl = QLabel("Nodes: --")
        node_status_label_layout.addWidget(self.node_status_lbl)
        return node_status_label_layout

    def create_node_table(self):
        """Create the node information table (6 columns)."""
        table = QTableWidget()

        # Define headers matching update_node_status_table()
        headers = [
            "Node",  # 02 ✅ Connected
            "Firmware",  # from GET_VERSION (0xC8)
            "Serial(UUID)",  # from GET_UUID (0xE0)
            "Node Type",  # from GET_NODETYPE (0xCD)
            "Status",  # from GET_INTERRUPT (0xD8)
        ]

        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)

        # Use Stretch mode to make columns adapt to available width instead of forcing minimum widths
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Table styling
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(22)
        table.horizontalHeader().setFixedHeight(24)
        table.setAlternatingRowColors(True)
        table.setStyleSheet("""
            QTableWidget {
                background-color: #fafafa;
                alternate-background-color: #f3f3f3;
                gridline-color: #cccccc;
                font-size: 11px;
            }
            QHeaderView::section {
                background-color: #dcdcdc;
                font-weight: bold;
                font-size: 10px;
                border: 1px solid #b0b0b0;
                padding: 2px;
            }
        """)

        table.setMinimumHeight(78)
        table.setMaximumHeight(108)

        return table
    def create_command_section_widget(self):
        widget = QGroupBox("Command Sending")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        cmd_layout = QHBoxLayout()
        self.command_combo = QComboBox()
        # Remove setMinimumWidth to allow responsive sizing
        self.command_combo.addItems(list(COMMANDS.keys()))

        self.target_node_id_combo = QComboBox()
        # Reduce setFixedWidth from 90 to allow wrapping in compact layouts
        self.target_node_id_combo.setMaximumWidth(90)
        for i in range(1, 18):
            self.target_node_id_combo.addItem(f"Node {i:02d}", i)
        default_index = self.target_node_id_combo.findData(0x10)
        if default_index >= 0:
            self.target_node_id_combo.setCurrentIndex(default_index)

        self.send_btn = QPushButton("Send")
        # Reduce setFixedWidth from 80 to allow responsive sizing
        self.send_btn.setMaximumWidth(80)
        self.send_btn.clicked.connect(self.send_command)

        self.stop_btn = QPushButton("STOP Motor")
        self.stop_btn.setToolTip("Send emergency STOP motor command (0xDD)")
        self.stop_btn.clicked.connect(self.send_stop_motor)
        self.stop_btn.setEnabled(False)

        self.all_logpos_stop_btn = QPushButton("All LogPos Stop")
        self.all_logpos_stop_btn.setToolTip("Send Set Log Position Stop to key nodes")
        self.all_logpos_stop_btn.clicked.connect(self.send_all_logpos_stop)
        self.all_logpos_stop_btn.setEnabled(False)

        cmd_layout.addWidget(QLabel("Command:"))
        cmd_layout.addWidget(self.command_combo, 1)
        cmd_layout.addWidget(QLabel("Node:"))
        cmd_layout.addWidget(self.target_node_id_combo)
        cmd_layout.addWidget(self.send_btn)
        cmd_layout.addWidget(self.stop_btn)
        cmd_layout.addWidget(self.all_logpos_stop_btn)
        cmd_layout.addStretch()

        layout.addLayout(cmd_layout)
        return widget

    def create_motor_control_box(self):
        group = QGroupBox("Motor Movement Control")
        layout = QVBoxLayout()
        layout.setSpacing(6)
        layout.setContentsMargins(6, 6, 6, 6)

        # Row 1: Target Node and Main Actions
        top_row = QHBoxLayout()
        self.motion_node_combo = QComboBox()
        # Reduce setFixedWidth to allow wrapping
        self.motion_node_combo.setMaximumWidth(100)
        for i in range(2, 18):
            self.motion_node_combo.addItem(f"Node {i:02d}", i)
        self.motion_node_combo.currentIndexChanged.connect(self.update_motion_node_label)
        self.motion_node_combo.currentIndexChanged.connect(self._sync_command_node_to_motion)
        
        self.auto_move_btn = QPushButton("Start Auto Move")
        self.auto_move_btn.setCheckable(True)
        self.auto_move_btn.clicked.connect(self.toggle_auto_move)
        
        self.stop_motor_btn = QPushButton("Stop Motor")
        self.stop_motor_btn.clicked.connect(self.send_stop_motor)
        self.stop_motor_btn.setStyleSheet("background-color: #ffcccc; font-weight: bold;") # Light red for safety
        
        top_row.addWidget(QLabel("Target Node:"))
        top_row.addWidget(self.motion_node_combo)
        top_row.addStretch()
        top_row.addWidget(self.auto_move_btn)
        top_row.addWidget(self.stop_motor_btn)
        layout.addLayout(top_row)

        # Main horizontal split for Config and Init boxes
        sub_boxes_layout = QHBoxLayout()
        
        # --- Configuration Box ---
        config_group = QGroupBox("Configuration")
        config_layout = QGridLayout()
        config_layout.setSpacing(4)
        
        # CPD
        config_layout.addWidget(QLabel("CPD:"), 0, 0)
        self.counts_per_degree_input = QLineEdit("2684.49")
        self.counts_per_degree_input.setMaximumWidth(70)
        self.counts_per_degree_input.textChanged.connect(self.update_active_panel_cpd)
        config_layout.addWidget(self.counts_per_degree_input, 0, 1)
        
        # Threshold
        config_layout.addWidget(QLabel("Threshold:"), 0, 2)
        self.threshold_input = QLineEdit("1500")
        self.threshold_input.setMaximumWidth(60)
        config_layout.addWidget(self.threshold_input, 0, 3)

        # LogPos and Interval
        self.enable_logpos_chk = QCheckBox("Log Pos")
        self.enable_logpos_chk.stateChanged.connect(self.toggle_log_position)
        config_layout.addWidget(self.enable_logpos_chk, 1, 0, 1, 2)
        
        config_layout.addWidget(QLabel("Intv(ms):"), 1, 2)
        self.auto_interval_input = QLineEdit("300")
        self.auto_interval_input.setMaximumWidth(60)
        config_layout.addWidget(self.auto_interval_input, 1, 3)

        # Start Pos and Offset
        config_layout.addWidget(QLabel("Start:"), 2, 0)
        self.start_pos_input = QLineEdit("26844") # 10 deg
        self.start_pos_input.setMaximumWidth(70)
        self.start_angle_input = QLineEdit("10.0")
        self.start_angle_input.setMaximumWidth(50)
        self.start_pos_input.textEdited.connect(self.sync_start_count_to_angle)
        self.start_angle_input.textEdited.connect(self.sync_start_angle_to_count)
        
        start_pos_layout = QHBoxLayout()
        start_pos_layout.addWidget(self.start_pos_input)
        start_pos_layout.addWidget(QLabel("|"))
        start_pos_layout.addWidget(self.start_angle_input)
        start_pos_layout.addWidget(QLabel("\u00b0"))
        config_layout.addLayout(start_pos_layout, 2, 1)
        
        config_layout.addWidget(QLabel("Off:"), 2, 2)
        self.start_offset_lbl = QLabel("0")
        self.start_offset_lbl.setStyleSheet("font-weight: bold; color: blue;")
        config_layout.addWidget(self.start_offset_lbl, 2, 3)

        # End Pos and Offset
        config_layout.addWidget(QLabel("End:"), 3, 0)
        self.end_pos_input = QLineEdit("295293") # 110 deg
        self.end_pos_input.setMaximumWidth(70)
        self.end_angle_input = QLineEdit("110.0")
        self.end_angle_input.setMaximumWidth(50)
        self.end_pos_input.textEdited.connect(self.sync_end_count_to_angle)
        self.end_angle_input.textEdited.connect(self.sync_end_angle_to_count)
        
        end_pos_layout = QHBoxLayout()
        end_pos_layout.addWidget(self.end_pos_input)
        end_pos_layout.addWidget(QLabel("|"))
        end_pos_layout.addWidget(self.end_angle_input)
        end_pos_layout.addWidget(QLabel("\u00b0"))
        config_layout.addLayout(end_pos_layout, 3, 1)
        
        config_layout.addWidget(QLabel("Off:"), 3, 2)
        self.end_offset_lbl = QLabel("0")
        self.end_offset_lbl.setStyleSheet("font-weight: bold; color: blue;")
        config_layout.addWidget(self.end_offset_lbl, 3, 3)

        config_group.setLayout(config_layout)
        sub_boxes_layout.addWidget(config_group, 3)

        # --- Motor Initialization Box ---
        init_group = QGroupBox("Motor Initialization")
        init_layout = QVBoxLayout()
        init_layout.setSpacing(4)
        
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Status:"))
        self.init_status_lbl = QLabel("Idle")
        self.init_status_lbl.setStyleSheet("font-weight: bold;")
        status_row.addWidget(self.init_status_lbl)
        init_layout.addLayout(status_row)
        
        vel_row = QHBoxLayout()
        vel_row.addWidget(QLabel("Velocity:"))
        self.velocity_input = QLineEdit("-20")
        self.velocity_input.setMaximumWidth(50)
        vel_row.addWidget(self.velocity_input)
        init_layout.addLayout(vel_row)
        
        self.init_motor_btn = QPushButton("Init Motor")
        self.init_motor_btn.clicked.connect(self.init_motor)
        init_layout.addWidget(self.init_motor_btn)
        
        init_group.setLayout(init_layout)
        sub_boxes_layout.addWidget(init_group, 2)
        
        layout.addLayout(sub_boxes_layout)

        group.setLayout(layout)
        return group

    # --- Sync Logic ---
    def sync_start_count_to_angle(self): self._sync_count_to_angle(self.start_pos_input, self.start_angle_input)
    def sync_start_angle_to_count(self): self._sync_angle_to_count(self.start_angle_input, self.start_pos_input)
    def sync_end_count_to_angle(self): self._sync_count_to_angle(self.end_pos_input, self.end_angle_input)
    def sync_end_angle_to_count(self): self._sync_angle_to_count(self.end_angle_input, self.end_pos_input)

    def _sync_count_to_angle(self, count_edit, angle_edit):
        try:
            cpd = float(self.counts_per_degree_input.text())
            count = float(count_edit.text())
            angle = count / cpd if cpd != 0 else 0
            angle_edit.setText(f"{angle:.1f}")
        except ValueError: pass

    def _sync_angle_to_count(self, angle_edit, count_edit):
        try:
            cpd = float(self.counts_per_degree_input.text())
            angle = float(angle_edit.text())
            count = int(angle * cpd)
            count_edit.setText(str(count))
        except ValueError: pass

    def update_active_panel_cpd(self):
        try:
            cpd = float(self.counts_per_degree_input.text())
            node_id = self.motion_node_combo.currentData()
            if node_id in self.motor_panels:
                self.motor_panels[node_id].set_counts_per_degree(cpd)
        except ValueError: pass

    def update_motion_node_label(self):
        node_id = self.motion_node_combo.currentData()
        
        # Update Counts Per Degree default based on node
        cpd_defaults = {
            3: "2684.49", # Ya
            4: "2684.49", # Yb
            5: "2684.49", # Nd
            6: "2684.49", # Rs
            8: "2684.49", # Rp
            9: "44.44",   # Z
            12: "2684.49" # Rn
        }
        if node_id in cpd_defaults:
            self.counts_per_degree_input.setText(cpd_defaults[node_id])
            
        # Node 08 Specific Defaults
        if node_id == 8:
            self.velocity_input.setText("-20")
            self.auto_interval_input.setText("300")
            self.start_angle_input.setText("10.0")
            self.end_angle_input.setText("110.0")
            # Trigger sync to update counts
            self.sync_start_angle_to_count()
            self.sync_end_angle_to_count()
            self.log(f"📋 Loaded defaults for Node 08 (Rp)")
            
        # Switch Visualization Panel
        if node_id not in self.motor_panels:
            panel = MotorAnimationModule(node_id)
            self.viz_stack.addWidget(panel)
            self.motor_panels[node_id] = panel
            # Initial CPD sync
            try:
                cpd = float(self.counts_per_degree_input.text())
                panel.set_counts_per_degree(cpd)
            except ValueError: pass
            
        self.viz_stack.setCurrentWidget(self.motor_panels[node_id])

    def _sync_command_node_to_motion(self):
        node_id = self.motion_node_combo.currentData()
        idx = self.target_node_id_combo.findData(node_id)
        if idx >= 0 and self.target_node_id_combo.currentIndex() != idx:
            self.target_node_id_combo.blockSignals(True)
            self.target_node_id_combo.setCurrentIndex(idx)
            self.target_node_id_combo.blockSignals(False)

    def _sync_motion_node_to_command(self):
        node_id = self.target_node_id_combo.currentData()
        idx = self.motion_node_combo.findData(node_id)
        if idx >= 0 and self.motion_node_combo.currentIndex() != idx:
            self.motion_node_combo.blockSignals(True)
            self.motion_node_combo.setCurrentIndex(idx)
            self.motion_node_combo.blockSignals(False)
            self.update_motion_node_label() # Manually trigger visualization update

    def create_log_section(self):
        # Deprecated: Logging is now part of Motor Control Box
        return QVBoxLayout()

        self.autoscroll_chk.setChecked(True)

        self.hide_sys_mode_chk = QCheckBox("Hide System Status")
        self.hide_sys_mode_chk.setToolTip("Disable showing periodic 'System Mode Response' logs")
        self.hide_sys_mode_chk.setChecked(False)

    def create_bottom_controls(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)

        test_all_btn = QPushButton("Test All Nodes")
        test_all_btn.clicked.connect(self.test_all_connected_nodes)
        config_btn = QPushButton("Motor Config")
        export_btn = QPushButton("Export Logs")
        export_btn.clicked.connect(self.save_runtime_console_log)

        self.monitor_btn = QPushButton("Serial Monitor")
        self.monitor_btn.clicked.connect(self.monitor_dialog.show)
 
        self.comm_monitor_btn = QPushButton("Comm Monitor")
        self.comm_monitor_btn.clicked.connect(self.comm_monitor.show)
 
        theme_toggle_btn = QPushButton("Theme")
        theme_toggle_btn.clicked.connect(self.toggle_theme)

        buttons = [
            test_all_btn,
            config_btn,
            export_btn,
            self.comm_monitor_btn,
            self.monitor_btn,
            theme_toggle_btn,
        ]
        for index, button in enumerate(buttons):
            layout.addWidget(button, index // 2, index % 2)

        return layout

    def save_runtime_console_log(self) -> None:
        """Save Runtime Console logs to a .csv file."""
        from PyQt6.QtWidgets import QFileDialog
        from PyQt6.QtCore import QDateTime
        import os
        import csv
        import re

        """default_name = QDateTime.currentDateTime().toString("'runtime-log-'yyyyMMdd-HHmmss'.log'")
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Runtime Console Log",
            str(get_runtime_exports_dir() / default_name),
            "Log Files (*.log);;Text Files (*.txt);;All Files (*.*)",
        )
        
        if not selected_path:
            return
            
        try:
            with open(selected_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(self.log_box.toPlainText())
            self.log(f"💾 Runtime console log saved to {os.path.basename(selected_path)}")
            
        except Exception as e:
            self.log(f"❌ Failed to save runtime console log: {e}")"""

        raw_text = self.log_box.toPlainText()
        if not raw_text.strip():
            return

        current_time = QDateTime.currentDateTime().toString("yyyyMMdd-HHmmss")
        default_filename = f"runtime-log-{current_time}.csv"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Sequence Logs as CSV",
            str(get_runtime_exports_dir() / default_filename),
            "CSV Files (*.csv);;All Files (*)"
        )

        if not file_path:
            return

        # --- EMOJI STRIPPING REGEX PATTERN ---
        # This covers standard emojis, transport/map symbols, and miscellaneous pictographs
        emoji_pattern = re.compile(
            r'[\U00010000-\U0010ffff]'  # 4-byte emojis (like 💾, 📅, 🔍, ⚙️)
            r'|[\u2600-\u27BF]'  # 3-byte miscellaneous symbols/dingbats (like ⏱️, ✅, ➡️)
            r'|[\u2300-\u23FF]'  # Technical symbols (like watch faces)
        )

        try:
            with open(file_path, mode='w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                # 1. Write the official headers
                writer.writerow(["Timestamp", "Category", "Target Node", "Action/Cmd", "Data / Message"])
                # 2. Visual Padding Row to stretch columns and prevent clipping in Excel
                writer.writerow([
                    " " * 15,  # Width padding for Timestamp
                    " " * 20,  # Width padding for Category
                    " " * 12,  # Width padding for Target Node
                    " " * 20,  # Width padding for Action/Cmd
                    " " * 65  # Deep width padding for Data / Message payloads
                ])

                for line in raw_text.splitlines():
                    if not line.strip():
                        continue

                    # --- STRIP EMOJIS AND CLEAN WHITESPACE ---
                    # Remove emojis and strip any resulting double/leading spaces
                    line = emoji_pattern.sub('', line).strip()

                    if line.startswith("[") and "]" in line:
                        parts = line.split("]", 1)
                        timestamp = parts[0].replace("[", "").strip()
                        message = parts[1].strip()

                        category = "System"
                        node_id = "N/A"
                        action_cmd = "Info"
                        data_msg = message

                        if message.startswith("TX"):
                            category = "Transmit (TX)"
                            cmd_match = re.search(r"TX\[(.*?)\]", message)
                            action_cmd = cmd_match.group(1) if cmd_match else "TX"
                            node_match = re.search(r"Node\s+([0-9A-Fa-f]+)", message)

                            if node_match:
                                node_id = node_match.group(1)
                            if ":" in message:
                                data_msg = message.split(":", 1)[1].strip()

                        elif message.startswith("RX"):
                            category = "Receive (RX)"
                            action_cmd = "CAN Frame"
                            from_match = re.search(r"From:([0-9A-Fa-f]+)", message)
                            if from_match:
                                node_id = from_match.group(1)
                            cmd_val_match = re.search(r"Cmd:([0-9A-Fa-f]+)", message)
                            params_match = re.search(r"Params:\[(.*?)\]", message)
                            cmd_str = f"Cmd {cmd_val_match.group(1)}" if cmd_val_match else ""
                            param_str = f"Params: [{params_match.group(1)}]" if params_match else ""
                            data_msg = f"{cmd_str} {param_str}".strip()

                        elif message.startswith("Decoded"):
                            category = "Data Decode"
                            type_match = re.search(r"Decoded\s+\[(.*?)\]", message)
                            action_cmd = f"Decoded {type_match.group(1)}" if type_match else "Decode"
                            if "=" in message:
                                data_msg = message.split("=", 1)[1].strip()

                        elif "Node" in message and any(
                            x in message for x in ["timed out", "detected", "responded"]):
                            category = "Node State Change"
                            node_match = re.search(r"Node\s+([0-9A-Fa-f]+)", message)
                            if node_match:
                                node_id = node_match.group(1)
                            action_cmd = "Timeout" if "timed out" in message else "Discovery"

                        elif "Scheduled" in message:
                            category = "Scheduler"
                            node_match = re.search(r"Node\s+([0-9A-Fa-f]+)", message)
                            if node_match:
                                node_id = node_match.group(1)
                            cmd_match = re.search(r"Scheduled\s+([A-Z_]+)", message)
                            action_cmd = cmd_match.group(1) if cmd_match else "Schedule Task"

                        # 3. Forced Alignment Formatting
                        writer.writerow([
                            f'="{timestamp}"',
                            category,
                            f'="{node_id}"',
                            action_cmd,
                            data_msg
                        ])

                    else:
                        # For lines that don't match the standard [timestamp] block
                        writer.writerow(["", "System Log", f'="N/A"', "Console Event", line])

            print(f"Emoji-free CSV log exported to {os.path.basename(file_path)}")

        except Exception as e:
            print(f"Failed to save CSV log: {e}")

    def setup_timers(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_ports)
        self.timer.start(2000)

        self.read_timer = QTimer()
        self.read_timer.timeout.connect(self.read_serial_data)
        self.read_timer.start(5) # Reduced from 50ms to 10ms for faster response

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = self.backend_client.get_available_ports()

        com11_found = False
        com11_index = -1

        # Add ports with indication of which are valid
        for i, port in enumerate(ports):
            if port == "COM11":
                display_text = f"{port} ✅ (Valid)"
                com11_found = True
                com11_index = i
            else:
                display_text = f"{port} ❌ (Invalid)"
            self.port_combo.addItem(display_text, port)  # Store original port as userData

        # Set COM11 as default if found
        if com11_found:
            # Find the COM11 item in the combo box and select it
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == "COM11":
                    self.port_combo.setCurrentIndex(i)
                    break
        # If COM11 not found but we had a previous selection, try to maintain it
        elif current:
            # Extract the original port name from the display text
            original_port = current.split(' ')[0]  # Get "COM11" from "COM11 ✅ (Valid)"
            for i in range(self.port_combo.count()):
                if self.port_combo.itemData(i) == original_port:
                    self.port_combo.setCurrentIndex(i)
                    break

    def toggle_connection(self):
        if self.connect_btn.isChecked():
            self.log("✅ toggle_connection->connect_serial()")
            self.connect_serial()
        else:
            self.disconnect_serial()

    def toggle_theme(self):
        if self.theme == "light":
            self.theme = "dark"
            self.setStyleSheet(get_dark_theme())
        else:
            self.theme = "light"
            self.setStyleSheet(get_light_theme())

    def connect_serial(self):
        # Get the original port name from userData, not display text
        port = self.port_combo.currentData()

        if not port:
            QMessageBox.warning(self, "Warning", "Please select a serial port first.")
            self.connect_btn.setChecked(False)
            return

        # Get selected baud rate
        try:
            baud_rate = int(self.baud_combo.currentText())
        except ValueError:
            self.log("⚠️ Invalid baud rate, using default 115200")
            baud_rate = 115200

        # Validate that only COM11 is allowed to connect
        if port != "COM11":
            QMessageBox.warning(self, "Invalid Port",
                                f"Only COM11 is allowed for connection.\n"
                                f"Selected port '{port}' is not valid.")
            self.connect_btn.setChecked(False)
            return

        if self.backend_client.connect(port, baud_rate):
            self.is_connected = True
            self.log(f"✅ Successfully connected to {port} at {self.backend_client.baudrate} baud")
            self.connect_btn.setText("Disconnect")
            self.port_combo.setEnabled(False)
            self.baud_combo.setEnabled(False)  # Disable baud rate during connection

            # Initialize node detection system
            # Enable ZPOSS controls if available
            try:
                if hasattr(self, 'zposs_plot') and self.zposs_plot:
                    if hasattr(self.zposs_plot, 'start_action'):
                        self.zposs_plot.start_action.setEnabled(True)
                    if hasattr(self.zposs_plot, 'stop_action'):
                        self.zposs_plot.stop_action.setEnabled(True)
            except Exception:
                pass

            # Enable STOP button when connected
            try:
                if hasattr(self, 'stop_btn'):
                    self.stop_btn.setEnabled(True)
                if hasattr(self, 'all_logpos_stop_btn'):
                    self.all_logpos_stop_btn.setEnabled(True)
            except Exception:
                pass

            # Start node detection after a short delay
            QTimer.singleShot(COMMUNICATION_START_DELAY, self.start_communication)
            
            # Start system mode polling
            self.sys_mode_timer.start(1000)
            self.query_sys_mode()


        else:
            self.connect_btn.setChecked(False)
            self.is_connected = False

    def disconnect_serial(self):
        """Disconnect from serial port and stop all activities."""
        try:
            # Set flags to stop all activities FIRST
            self.is_connected = False
            self.scan_active = False
            self._batch_node_scan_active = False

            # Stop all timers
            if hasattr(self, 'node_scan_timeout_timer'):
                self.node_scan_timeout_timer.stop()

            if hasattr(self, 'node_status_timer'):
                self.node_status_timer.stop()
            
            if hasattr(self, 'sys_mode_timer'):
                self.sys_mode_timer.stop()
            
            self.sys_mode = {"text": "Unknown", "color": "#808080", "blink": 0}
            self.update_status_ui()

            # Reset MCU version flag on disconnect
            self.mcu_version_queried = False
            self.mcu_version = None  # clear the MCU version
            self.mcu_version_lbl.setText(f"MCU Firmware Version: ")
            self.node_discovery_coordinator.reset()

            # Disconnect serial
            self.backend_client.disconnect()
            self.log("🔌 Disconnected - all activities stopped")
            self.connect_btn.setText("Connect")
            self.port_combo.setEnabled(True)  # Re-enable port selection
            self.baud_combo.setEnabled(True)  # Re-enable baud rate selection

            # Reset node status display
            if hasattr(self, 'node_status_lbl'):
                self.node_status_lbl.setText("Nodes: --")
                self.node_status_lbl.setStyleSheet("color: red; font-weight: bold;")

            # Clear node status
            if hasattr(self, 'node_status'):
                reset_node_status(self.node_status)
                self.update_node_status_display()

            # Disable ZPOSS controls if available
            try:
                if hasattr(self, 'zposs_plot') and self.zposs_plot:
                    if hasattr(self.zposs_plot, 'start_action'):
                        self.zposs_plot.start_action.setEnabled(False)
                    if hasattr(self.zposs_plot, 'stop_action'):
                        self.zposs_plot.stop_action.setEnabled(False)
            except Exception:
                pass

            # Disable STOP button when disconnected
            try:
                if hasattr(self, 'stop_btn'):
                    self.stop_btn.setEnabled(False)
                if hasattr(self, 'all_logpos_stop_btn'):
                    self.all_logpos_stop_btn.setEnabled(False)
            except Exception:
                pass

        except Exception as e:
            self.log(f"❌ Error during disconnect: {e}")

    def validate_connection_state(self):
        """Check if we're still properly connected."""
        if not self.is_connected:
            return False

        # Check serial connection state
        if not self.backend_client.is_connected():
            self.is_connected = False
            self.scan_active = False
            self._batch_node_scan_active = False
            return False

        return True

    def start_communication(self):
        """Start all communication tasks after connection is stable."""
        try:
            # Clear buffers
            self.backend_client.reset_input_buffer()

            # Query MCU version only if not already queried
            if not self.mcu_version_queried:
                self.mcu_version_queried = True
                QTimer.singleShot(MCU_QUERY_DELAY_MS, self.query_mcu_version)
            else:
                self.log("ℹ️ MCU version already queried, skipping")

            # Start burst node scan after MCU query
            QTimer.singleShot(NODE_SCAN_START_DELAY, self.dispatch_node_scan_batch)


        except Exception as e:
            self.log(f"❌ Communication startup failed: {e}")

    def dispatch_node_scan_batch(self):
        """Send one full 86 3F node scan batch without waiting between nodes."""
        if not self.validate_connection_state():
            self.log("âš ï¸ Serial port not connected, cannot start batch scan")
            self.scan_active = False
            return False

        self.scan_active = True
        self.current_scan_node = 2
        self.detected_nodes.clear()
        self.node_discovery_coordinator.begin_cycle()
        self._batch_node_scan_active = True
        self.node_scan_timeout_timer.stop()
        self.log("ðŸ” Starting node ID scan batch (2â€“17)...")

        try:
            for node_id in range(2, 18):
                payload = self.backend_client.send_node_id_request(node_id)
                self.log(f"TX[SCAN] â†’ Node {node_id:02d}: {' '.join(f'{b:02X}' for b in payload)}")
            self.node_scan_timeout_timer.start(NODE_ADVANCE_DELAY)
            self.update_node_status_display()
            return True
        except Exception as e:
            self.log(f"âŒ Failed to dispatch node scan batch: {e}")
            self.scan_active = False
            self._batch_node_scan_active = False
            return False

    def on_node_scan_timeout(self):
        """Finish the current burst discovery window."""
        if not self.validate_connection_state():
            self.scan_active = False
            return

        self.log("Node scan window elapsed.")
        self._batch_node_scan_active = False
        self.scan_active = False

    def query_mcu_version(self):
        """Query MCU firmware version after connection - WITH DUPLICATE PREVENTION."""
        if self.mcu_version_queried and self.mcu_version:
            self.log(f"ℹ️ MCU version already known: {self.mcu_version}, skipping query")
            return

        if not self.backend_client.is_connected():
            self.log("Cannot query MCU version - serial port not connected")
            return

        try:
            payload = self.backend_client.send_mcu_version_query()
            log_line = f"TX[Auto]: {' '.join(f'{b:02X}' for b in payload)}"
            self.log(log_line)
            self.monitor_dialog.append_tx(log_line)

            self.log("Querying MCU firmware version...")
            self.mcu_version_queried = True  # Mark as queried

        except Exception as e:
            self.log(f"Failed to query MCU version: {e}")

    def setup_node_status_gui(self):
        """Setup the node status table for connected node information."""
        self.target_node_id_combo.clear()

        try:
            self.node_table.clear()

            # --- Define headers for the connected node table ---
            headers = [
                "Node (Connected)",  # 02 ✅ Connected
                "Firmware Version",  # GET_VERSION
                "Serial Number (UUID)",  # GET_UUID
                "Node Type",  # GET_NODETYPE
                "Status",  # GET_INTERRUPT result
            ]

            self.node_table.setColumnCount(len(headers))
            self.node_table.setHorizontalHeaderLabels(headers)
            self.node_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

            # --- Set fixed column widths for readable layout ---
            col_widths = [145, 120, 220, 140, 110]
            for i, w in enumerate(col_widths):
                self.node_table.setColumnWidth(i, w)

            self.node_table.verticalHeader().setVisible(False)
            self.node_table.verticalHeader().setDefaultSectionSize(22)
            self.node_table.horizontalHeader().setFixedHeight(24)
            self.node_table.setAlternatingRowColors(True)
            self.node_table.setStyleSheet("""
                        QTableWidget {
                            background-color: #fafafa;
                            alternate-background-color: #f3f3f3;
                            gridline-color: #cccccc;
                            font-size: 12px;
                        }
                        QHeaderView::section {
                            background-color: #dcdcdc;
                            font-weight: bold;
                            border: 1px solid #b0b0b0;
                        }
                    """)

            self.node_table.setRowCount(0)
            self.node_table.setMinimumHeight(78)
            self.node_table.setMaximumHeight(108)

        except Exception as e:
            self.log(f"❌ setup_node_status_gui failed: {e}")

    def update_node_status_display(self):
        """Update the node status display in the GUI."""
        try:
            if not hasattr(self, 'node_status_lbl') or not self.node_status_lbl:
                return

            if not hasattr(self, 'node_status'):
                return

            # Collect connected node IDs only between 2–12
            connected_nodes = [
                node_id for node_id, status in self.node_status.items()
                if 2 <= node_id <= 17 and status.get('connected', False)
            ]

            # Sort the connected node list
            connected_nodes.sort()


            # Build the display string
            if connected_nodes:
                connected_str = ", ".join(str(n) for n in connected_nodes)
                self.node_status_lbl.setText(f"Connected nodes: {connected_str}")
                self.node_status_lbl.setStyleSheet("color: green; font-weight: bold;")
            else:
                self.node_status_lbl.setText("Connected nodes: None")
                self.node_status_lbl.setStyleSheet("color: red; font-weight: bold;")

            # Update the table
            self.update_node_status_table()
            
            # Update the Test All Dialog if it's open
            if self.test_all_dialog and self.test_all_dialog.isVisible():
                self.test_all_dialog.update_connected_nodes(connected_nodes)

        except Exception as e:
            self.log(f"❌ Node status display update failed: {e}")

    def update_node_status_table(self):
        """Update the node status table with current data."""
        try:
            if not hasattr(self, 'node_table'):
                return

            # Node ID to name mapping
            # Used shared constant NODE_ID_MAPPING

            # Collect connected nodes (2–17 only)
            connected_nodes = [
                node_id for node_id, status in self.node_status.items()
                if 2 <= node_id <= 17 and status.get("connected", False)
            ]

            connected_nodes.sort()

            # Adjust row count
            self.node_table.clearSpans()
            self.node_table.setRowCount(len(connected_nodes))

            # Fill the table with node info
            for row, node_id in enumerate(connected_nodes):
                status = self.node_status[node_id]

                # Apply node ID mapping
                node_name = NODE_ID_MAPPING.get(node_id, "")
                if node_name:
                    node_display = f"{node_name}({node_id:02d}) ✅ Connected"
                else:
                    node_display = f"{node_id:02d} ✅ Connected"

                fw = status.get("firmware", "")
                uuid = status.get("uuid", "")
                node_type = status.get("type", "")

                # Skip Status update for nodes 5, 9, and 10
                if node_id in [5, 9, 10, 16, 17]:
                    interrupt_status = "N/A"  # Or whatever default value you prefer
                    interrupt_data = {}  # Empty data for skipped nodes
                else:
                    interrupt_status = status.get("interrupt", "")
                    interrupt_data = status.get("interrupt_data", {})

                values = [node_display, fw, uuid, node_type, interrupt_status]

                for col, val in enumerate(values):
                    # Always create a fresh QTableWidgetItem for each cell
                    item = QTableWidgetItem(str(val))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                    # Apply colors to interrupt column (column 4)
                    if col == 4 and interrupt_data and isinstance(interrupt_data, dict) and node_id not in [5, 9, 10,  16, 17]:
                        left_ok = interrupt_data.get('left_ok', False)
                        right_ok = interrupt_data.get('right_ok', False)

                        if left_ok and right_ok:
                            # Both OK - Light green
                            item.setBackground(QColor(144, 238, 144))
                        elif not left_ok and not right_ok:
                            # Both Cut - Light red
                            item.setBackground(QColor(255, 182, 193))
                        else:
                            # Mixed - Light yellow
                            item.setBackground(QColor(255, 255, 224))

                    # Insert the freshly created item into the table
                    self.node_table.setItem(row, col, item)

                # If no nodes connected
            if not connected_nodes:
                # Show a single-row message spanning all columns. Create a fresh item.
                self.node_table.setRowCount(1)
                no_item = QTableWidgetItem("No connected nodes")
                no_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                # Clear other cells first to be safe
                for c in range(self.node_table.columnCount()):
                    empty_item = QTableWidgetItem("")
                    empty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.node_table.setItem(0, c, empty_item)
                # Place the message in the first column and span across columns
                self.node_table.setItem(0, 0, no_item)
                try:
                    self.node_table.setSpan(0, 0, 1, self.node_table.columnCount())
                except Exception:
                    # setSpan may fail on some styles/platforms; ignore safely
                    pass

        except Exception as e:
            self.log(f"❌ update_node_status_table failed: {e}")

    def process_node_id_response(self, node_id, params):
        """Handle Node ID response and start info retrieval."""
        try:
            self.log(f"Node {node_id:02d} responded to NodeIDRef")

            if node_id not in self.node_status:
                self.node_status[node_id] = {'connected': True}
            else:
                self.node_status[node_id]['connected'] = True

            if self._batch_node_scan_active:
                self.detected_nodes.add(node_id)
                self._schedule_node_info_requests_for_node(node_id, source="node_id_response")
            self.update_node_status_display()

        except Exception as e:
            self.log(f"Node ID response processing failed: {e}")

    def send_node_info_requests(self, node_id):
        """Send node info queries - FIXED VERSION."""
        try:
            # Check connection before starting
            if not self.validate_connection_state():
                self.log(f"⚠️ Cannot send info requests to Node {node_id:02d}: serial not connected")
                return

            self.log(f"🔧 SENDING info requests to Node {node_id:02d}")

            # Command sequence with delays
            commands = [
                (0, "GET_VERSION", [0xC8, 0x3F]),
                (NODE_CMD_DELAY_1, "GET_NODETYPE", [0xCD, 0x3F]),
                (NODE_CMD_DELAY_2, "GET_INTERRUPT", [0xD8, 0x3F]),
                (NODE_CMD_DELAY_3, "GET_UUID", [0xE0, 0x3F]),  # 3000ms after previous
            ]

            for delay, name, cmd_bytes in commands:
                QTimer.singleShot(delay,
                                  lambda n=name, c=cmd_bytes, nid=node_id:
                                  self._send_single_node_command(nid, n, c))
                self.log(f"📅 Scheduled {name} for Node {node_id:02d} in {delay}ms")

            # Schedule UUID retry after all commands complete
            QTimer.singleShot(UUID_RETRY_CHECK_DELAY, lambda nid=node_id: self.retry_get_uuid_if_missing(nid))

            self.log(f"🕒 Scheduled {len(commands)} commands for Node {node_id:02d}")

        except Exception as e:
            self.log(f"❌ Failed to schedule info requests for node {node_id}: {e}")

    def _schedule_node_info_requests_for_node(self, node_id: int, *, source: str) -> bool:
        """Schedule one node-info burst per node per discovery cycle."""
        if not self.node_discovery_coordinator.request_node_info_once(node_id):
            self.log(
                f"⚠️ Skipping duplicate node info scheduling for Node {int(node_id):02d} "
                f"from {source} in cycle {self.node_discovery_coordinator.cycle_id}"
            )
            return False

        self.log(
            f"⚙️ Scheduling node info for Node {int(node_id):02d} "
            f"from {source} in cycle {self.node_discovery_coordinator.cycle_id}"
        )
        QTimer.singleShot(
            NODE_INFO_REQUEST_DELAY,
            lambda nid=int(node_id): self._dispatch_scheduled_node_info_requests(nid),
        )
        return True

    def _dispatch_scheduled_node_info_requests(self, node_id: int) -> None:
        """Run one scheduled node-info dispatch and clear transient pending state."""
        self.node_discovery_coordinator.mark_dispatch_started(node_id)
        self.send_node_info_requests(node_id)

    def _send_single_node_command(self, node_id, name, cmd_bytes):
        """Send one node info command through the reusable backend client."""
        try:
            if not self.validate_connection_state():
                self.log(f"⚠️ Cannot send {name} to Node {node_id:02d}: serial not connected")
                return

            payload = self.backend_client.send_command_bytes(node_id, cmd_bytes)
            log_line = f"TX[{name}] → Node {node_id:02d}: {' '.join(f'{b:02X}' for b in payload)}"
            self.log(log_line)
            self.monitor_dialog.append_tx(log_line)
        except Exception as e:
            self.log(f"❌ Failed to send {name} to Node {node_id:02d}: {e}")

    def retry_get_uuid_if_missing(self, node_id):
        """Resend GET_UUID if no valid UUID received, with special handling for Node 8."""
        node_info = self.node_status.get(node_id, {})

        # Check if UUID is invalid or missing
        uuid_valid = node_info.get("uuid_valid", False)
        uuid_value = node_info.get("uuid", "")

        if not uuid_valid or uuid_value in ("Invalid", None, ""):
            retry_count = node_info.get("uuid_retry_count", 0)

            if retry_count < 3:  # Maximum 3 retries
                delay = 200 * (retry_count + 1)  # Backoff: 0.2s, 0.4s, 0.6s
                self.log(f"🔁 Retrying GET_UUID for Node {node_id:02d} (attempt {retry_count + 1})...")

                # Store retry count
                self.node_status[node_id]["uuid_retry_count"] = retry_count + 1

                QTimer.singleShot(delay,
                                  lambda nid=node_id: self._send_single_node_command(nid, "GET_UUID", [0xE0, 0x3F]))
            else:
                self.log(f"⚠️ Giving up on Node {node_id:02d} UUID after {retry_count} retries")
                # Mark as permanently invalid
                self.node_status[node_id]["uuid_permanent_fail"] = True


    def update_node_activity(self, node_id):
        """Update runtime connectivity and reuse canonical node-info scheduling."""
        try:
            node_record = ensure_node_status(self.node_status, node_id)

            if not node_record['connected']:
                node_record['connected'] = True
                self.log(f"✅ Node {node_id:02d} detected via incoming packet")

            if self._batch_node_scan_active:
                self._schedule_node_info_requests_for_node(node_id, source="node_activity")

            self.update_node_status_display()

        except Exception as e:
            self.log(f"❌ Node activity update failed: {e}")

    def send_command(self):
        if not self.backend_client.is_connected():
            QMessageBox.warning(self, "Warning", "Serial port not connected.")
            return

        node_id = self.target_node_id_combo.currentData()
        cmd_name = self.command_combo.currentText()

        # Special handling for BCMD_SW_SCAN_CONTINUE: fetch velocity, start, end
        if cmd_name == "BCMD_SW_SCAN_CONTINUE":
            try:
                # Fetch velocity from Motor Initialization box (absolute value)
                velocity = abs(int(self.velocity_input.text()))
                start_val = int(self.start_pos_input.text())
                end_val = int(self.end_pos_input.text())
                
                # Format: [0xB9, '=', velocity(1 byte), start(4 bytes), end(4 bytes)]
                cmd_bytes = [0xB9, ord('='), velocity & 0xFF]
                cmd_bytes.extend(list(start_val.to_bytes(4, byteorder='big', signed=True)))
                cmd_bytes.extend(list(end_val.to_bytes(4, byteorder='big', signed=True)))
                
                # Arm the scanning timer
                self.is_scanning_continue = True
                self.scan_start_reported = False
                self.scan_target_start = start_val
                self.scan_target_end = end_val
                self.scan_target_node = node_id
                self.scan_target_velocity = velocity
                self.scan_start_time = 0.0
                self.log(f"⏱️ Scanning armed for Node {node_id:02d}: Start={start_val}, End={end_val}")
            except ValueError:
                self.log("⚠️ Scan Continue failed: Invalid Velocity, Start or End position value.")
                return
        else:
            cmd_bytes = self.backend_client.get_command_bytes(cmd_name)
        log_line = f"cmd_bytes: {' '.join(f'{b:02X}' for b in cmd_bytes)}"
        self.log(log_line)

        try:
            if cmd_name in ["ROBOT Off", "ROBOT On"]:
                payload = self.backend_client.send_command_bytes(0x01, cmd_bytes)
            else:
                payload = self.backend_client.send_command_bytes(node_id, cmd_bytes)

            log_line = f"TX: {' '.join(f'{b:02X}' for b in payload)}"
            self.log(log_line)
            self.monitor_dialog.append_tx(log_line)

        except Exception as e:
            self.log(f"Send failed: {e}")

    def init_motor(self):
        node_id = self.motion_node_combo.currentData()
        self.init_state[node_id] = 1 # Step 1: Sent C9
        self.init_signals[node_id] = set() # Reset signals
        
        self.init_status_lbl.setText("Initializing...")
        self.init_status_lbl.setStyleSheet("color: blue; font-weight: bold;")
        
        self.log(f"⚙️ Step 1: Sending Initialization command (C9 3D 0B) to Node {node_id:02d}...")
        self._send_single_node_command(node_id, "Init C9", [0xC9, 0x3D, 0x0B])
        
        if node_id in self.motor_panels:
            self.motor_panels[node_id].reset_counters()

    def toggle_log_position(self, state):
        node_id = self.motion_node_combo.currentData()
        if state == 2: # Checked
            try:
                interval = int(self.auto_interval_input.text())
                interval_bytes = list(interval.to_bytes(2, byteorder='big', signed=False))
                self.log(f"📊 Enabling Log Position for Node {node_id:02d} (Interval: {interval}ms)")
                self._send_single_node_command(node_id, "Enable LogPos", [0xE4, 0x3D] + interval_bytes)
            except ValueError:
                self.log("⚠️ Invalid interval for Log Position")
                self.enable_logpos_chk.setChecked(False)
        else:
            self.log(f"📊 Disabling Log Position for Node {node_id:02d}")
            self._send_single_node_command(node_id, "Disable LogPos", [0xE4, 0x3D, 0x00, 0x00])

    def toggle_auto_move(self):
        if self.auto_move_btn.isChecked():
            self.auto_move_btn.setText("Stop Auto Move")
            self.auto_move_btn.setStyleSheet("background-color: #FF4444; color: white;")
            self.start_offset_lbl.setText("0")
            self.end_offset_lbl.setText("0")
            
            # State: 1 = moving to start, 2 = moving to end
            self.auto_move_state = 1
            self.is_first_auto_move_check = True # Skip threshold check for the very first packet
            node_id = self.motion_node_combo.currentData()
            self.m_tpos_done_sent[node_id] = False
            
            self.send_tpos_to_start()
        else:
            self.auto_move_btn.setText("Start Auto Move")
            self.auto_move_btn.setStyleSheet("")
            self.auto_move_state = 0
            self.send_stop_motor()

    def send_tpos_to_start(self):
        node_id = self.motion_node_combo.currentData()
        self.auto_move_state = 1 # Set state ONLY when sending
        self.is_first_auto_move_check = True
        self.waiting_for_s[node_id] = True
        self.move_sent_time[node_id] = time.time()
        self.sys_mode = {"text": "Moving", "val": 0x01} # Clear Ready state
        
        if not self.auto_move_btn.isChecked(): return
        try:
            pos = int(self.start_pos_input.text())
            self.log(f"🔄 Auto-move: Moving to Start ({pos})")
            self.send_tpos_command(node_id, pos)
        except ValueError:
            self.stop_auto_move_with_error("Invalid Start Position")

    def send_tpos_to_end(self):
        node_id = self.motion_node_combo.currentData()
        self.auto_move_state = 2 # Set state ONLY when sending
        self.is_first_auto_move_check = True
        self.waiting_for_s[node_id] = True
        self.move_sent_time[node_id] = time.time()
        self.sys_mode = {"text": "Moving", "val": 0x01} # Clear Ready state
        
        if not self.auto_move_btn.isChecked(): return
        try:
            pos = int(self.end_pos_input.text())
            self.log(f"🔄 Auto-move: Moving to End ({pos})")
            self.send_tpos_command(node_id, pos)
        except ValueError:
            self.stop_auto_move_with_error("Invalid End Position")

    def send_tpos_command(self, node_id, pos):
        # TPOS command (0x81) with 4-byte big-endian position
        pos_bytes = list(pos.to_bytes(4, byteorder='big', signed=True))
        cmd_bytes = [0x81] + pos_bytes
        self._send_single_node_command(node_id, "TPOS", cmd_bytes)

    def send_stop_motor(self):
        """Emergency Stop for the motor and auto-move sequence."""
        node_id = self.motion_node_combo.currentData()
        self.log(f"🛑 Sending STOP command (0xDD) to Node {node_id:02d}...")
        self._send_single_node_command(node_id, "STOP", [0xDD])
        
        # Shutdown auto-move if active
        if self.auto_move_btn.isChecked():
            self.auto_move_btn.blockSignals(True)
            self.auto_move_btn.setChecked(False)
            self.auto_move_btn.blockSignals(False)
            self.auto_move_btn.setText("Start Auto Move")
            self.auto_move_btn.setStyleSheet("")
            
        self.auto_move_state = 0
        self.waiting_for_s[node_id] = False
        self.log("ℹ️ Auto-move state machine reset.")

    def stop_auto_move_with_error(self, msg):
        self.log(f"❌ Auto-move error: {msg}")
        self.auto_move_btn.setChecked(False)
        self.toggle_auto_move()
        QMessageBox.warning(self, "Auto-move Error", msg)

    def send_auto_move_command(self):
        if not self.auto_move_btn.isChecked():
            return

        try:
            node_id = self.motion_node_combo.currentData()
            start_pos = int(self.start_pos_input.text())
            end_pos = int(self.end_pos_input.text())
            interval = int(self.auto_interval_input.text())
            
            # Pack command 0xB8: [start_pos(4), end_pos(4), interval(2)]
            # Note: The command_builder might already handle this if defined in myconfig.constants
            # but let's do it manually for reliability if needed.
            payload = []
            payload.extend(list(start_pos.to_bytes(4, byteorder='little', signed=True)))
            payload.extend(list(end_pos.to_bytes(4, byteorder='little', signed=True)))
            payload.extend(list(interval.to_bytes(2, byteorder='little', signed=False)))
            
            cmd_bytes = [0xB8] + payload
            self._send_single_node_command(node_id, "Auto Move", cmd_bytes)
            
            self.m_tpos_done_sent[node_id] = False
        except Exception as e:
            self.log(f"❌ Auto Move failed: {e}")
            self.auto_move_btn.setChecked(False)
            self.toggle_auto_move()

    def ticks_to_degrees(self, node_id, ticks):
        """Convert encoder ticks to degrees based on GUI configuration."""
        try:
            cpd = float(self.counts_per_degree_input.text())
            if cpd != 0:
                return ticks / cpd
        except ValueError:
            pass
        return 0.0

    def finalize_scan(self):
        """Called 300ms after the last TPOS E near target to confirm scan end."""
        node_id = self.scan_target_node
        elapsed = self.scan_last_elapsed
        start_deg = self.ticks_to_degrees(node_id, self.scan_target_start)
        end_deg = self.ticks_to_degrees(node_id, self.scan_target_end)
        self.log(f"✅ Node {node_id:02d}: Scanning time is {elapsed:.2f}s at velocity {self.scan_target_velocity}% from {start_deg:.2f}(degree) to {end_deg:.2f}(degree).")
        self.is_scanning_continue = False

    def on_tpos_received(self, node_id, tpos_data):
        """Update animation and handle loop logic."""
        if not tpos_data or not isinstance(tpos_data, tuple):
            return
        
        type_char, pos = tpos_data
        
        if node_id not in self.motor_panels:
            return

        panel = self.motor_panels[node_id]
        self.last_positions[node_id] = pos
        
        # Update visual
        panel.set_position(pos)
        
        # Handle Scan Continue Timing
        if self.is_scanning_continue and node_id == self.scan_target_node:
            if not self.scan_start_reported:
                # Trigger on the VERY FIRST 'E' packet from this node after arming
                self.scan_start_time = time.time()
                self.scan_start_reported = True
                self.log(f"⏱️ Scan started for Node {node_id:02d} (Target Start: {self.scan_target_start}, Actual: {pos})")
            else:
                # Check if we are near the end position
                if abs(pos - self.scan_target_end) <= 500:
                    # Capture current elapsed time
                    self.scan_last_elapsed = time.time() - self.scan_start_time
                    # Start/Restart 300ms debounce timer
                    self.scan_finish_timer.start(300)
        
        # Handle Initialization State Machine (Step 4 & 5)
        if node_id in self.init_state and self.init_state[node_id] == 2:
            if type_char in ['Z', 'I']:
                self.init_signals[node_id].add(type_char)
                self.log(f"📥 Received TPOS '{type_char}' from Node {node_id:02d}")
                
                # Step 5: Check if done
                if 'I' in self.init_signals[node_id]: # User said: "if received TPOS 'I' or both TPOS 'Z' and 'I'"
                    self.init_status_lbl.setText("Initialization Done")
                    self.init_status_lbl.setStyleSheet("color: green; font-weight: bold;")
                    self.init_state[node_id] = 0
                    self.log(f"✅ Initialization Done for Node {node_id:02d}")
        
        # Trigger on 'E' (Target Reached), 'N' (Near), or 'G' (GETPOS) if Ready
        is_ready = getattr(self, 'sys_mode', {}).get('text') == "Ready"
        
        # --- New Sophisticated State Machine ---
        # 1. Update Position Buffer
        if type_char == 'G':
            self.pos_buffer[node_id].append(pos)

        # 2. Handle 'S' (Start Moving) Handshake
        if type_char == 'S':
            self.waiting_for_s[node_id] = False
            self.last_s_time[node_id] = time.time()
            self.log(f"🚀 Node {node_id:02d} started moving...")
            return

        # 3. Timeouts and Phase Logic
        now = time.time()
        sent_time = self.move_sent_time.get(node_id, 0)
        s_time = self.last_s_time.get(node_id, 0)
        
        # Check for 'S' timeout (800ms)
        if self.waiting_for_s.get(node_id):
            if now - sent_time > self.auto_move_s_timeout:
                self.log(f"⚠️ Node {node_id:02d} failed to send 'S' within {self.auto_move_s_timeout}s. Forcing move status.")
                self.waiting_for_s[node_id] = False
                self.last_s_time[node_id] = now
            else:
                return # Still waiting for 'S'

        # 4. Completion and Threshold Checks (Only if Auto-Move is Active)
        if not self.auto_move_btn.isChecked():
            return

        # Check for 'E' (completion) signals
        is_ready = getattr(self, 'sys_mode', {}).get('text') == "Ready"
        is_at_target = type_char in ['E', 'N']
        
        # If we didn't get 'E', check if we should trigger a fallback
        if not is_at_target:
            time_since_s = now - s_time
            if time_since_s > self.auto_move_e_timeout:
                # 10s Timeout Reached! Check buffer to see if stationary
                buffer = list(self.pos_buffer[node_id])
                if len(buffer) >= 5 and all(p == buffer[0] for p in buffer):
                    # Motor is NOT moving (last 5 GETPOS identical)
                    self.log(f"⚠️ 10s timeout without 'E'. Motor stationary at {pos}. Recovery triggered.")
                    
                    # Track as missed TPOS E
                    if node_id in self.motor_panels:
                        target_pos = int(self.start_pos_input.text()) if self.auto_move_state == 1 else int(self.end_pos_input.text())
                        offset = pos - target_pos
                        self.motor_panels[node_id].increment_miss_e(offset)
                    
                    is_at_target = True # Force completion logic
                else:
                    # Still moving, reset timeout for another 10s
                    self.log(f"🕒 Node {node_id:02d} still moving (Pos: {pos}). Resetting 10s timeout.")
                    self.last_s_time[node_id] = now
                    return
            else:
                # Not timed out yet, only trigger if Ready state is confirmed
                if type_char == 'G' and is_ready and time_since_s > 1.0:
                    is_at_target = True
                else:
                    return

        if node_id == self.motion_node_combo.currentData():
            try:
                threshold = int(self.threshold_input.text())
                start_pos = int(self.start_pos_input.text())
                end_pos = int(self.end_pos_input.text())
                
                if self.auto_move_state == 1: # Reached Start
                    offset = pos - start_pos
                    self.start_offset_lbl.setText(f"{offset:+d}")
                    
                    if abs(offset) > threshold:
                        if self.is_first_auto_move_check:
                            # Ignore this check, we just started and might be far away
                            self.is_first_auto_move_check = False
                            self.log(f"ℹ️ First packet received ({type_char} at {pos}), waiting for motor to reach Start...")
                            return
                        
                        self.stop_auto_move_with_error(f"Start Offset {offset} exceeds threshold {threshold}!")
                        return
                    
                    self.is_first_auto_move_check = True # Reset IMMEDIATELY before delay
                    self.log(f"✅ Reached Start (Offset: {offset}). Moving to End.")
                    self.auto_move_state = 0 # Transitioning
                    QTimer.singleShot(500, self.send_tpos_to_end) # Small delay before next move
                    
                elif self.auto_move_state == 2: # Reached End
                    offset = pos - end_pos
                    self.end_offset_lbl.setText(f"{offset:+d}")
                    
                    if abs(offset) > threshold:
                        if self.is_first_auto_move_check:
                            self.is_first_auto_move_check = False
                            self.log(f"ℹ️ First packet received ({type_char} at {pos}), waiting for motor to reach End...")
                            return
                            
                        self.stop_auto_move_with_error(f"End Offset {offset} exceeds threshold {threshold}!")
                        return
                    
                    self.is_first_auto_move_check = True # Reset IMMEDIATELY before delay
                    panel.increment_loops()
                    self.log(f"✅ Reached End (Offset: {offset}). Loop {panel.loop_count} complete. Returning to Start.")
                    self.auto_move_state = 0 # Transitioning
                    QTimer.singleShot(500, self.send_tpos_to_start)
                    
            except ValueError:
                self.stop_auto_move_with_error("Invalid threshold or positions")

    def send_stop_motor(self):
        """Send the STOP Motor command (0xDD) to the selected node or broadcast to MCU.
        Placed beside the Send button as an emergency control.
        """
        if not self.backend_client.is_connected():
            QMessageBox.warning(self, "Warning", "Serial port not connected.")
            return

        try:
            # Determine target: for safety, send to selected node unless ROBOT On/Off logic
            node_id = self.target_node_id_combo.currentData()

            # Build and send packet
            payload = self.backend_client.send_stop_motor(node_id)

            log_line = f"TX[STOP] → Node {node_id:02d}: {' '.join(f'{b:02X}' for b in payload)}"
            self.log(log_line)
            self.monitor_dialog.append_tx(log_line)

        except Exception as e:
            self.log(f"❌ Failed to send STOP Motor: {e}")

    def send_all_logpos_stop(self):
        """Send 'Set Log Position Stop' (0xE4,0x3D,0x00,0x00) to nodes [3,4,6,8,12]."""
        if not self.backend_client.is_connected():
            QMessageBox.warning(self, "Warning", "Serial port not connected.")
            return

        try:
            target_nodes = [3, 4, 6, 8, 12]

            for node_id in target_nodes:
                try:
                    payload = self.backend_client.send_log_position_stop(node_id)
                    log_line = f"TX[LogPosStop] → Node {node_id:02d}: {' '.join(f'{b:02X}' for b in payload)}"
                    self.log(log_line)
                    # push to monitor dialog as well
                    try:
                        self.monitor_dialog.append_tx(log_line)
                    except Exception:
                        pass
                    # small pause not required because we schedule sequentially; network/serial handle pacing
                except Exception as inner_e:
                    self.log(f"❌ Failed to send LogPos Stop to Node {node_id}: {inner_e}")

        except Exception as e:
            self.log(f"❌ Failed to send All LogPos Stop: {e}")

    def read_serial_data(self):
        """Read serial data with connection state validation."""
        if not self.validate_connection_state():
            return  # Don't try to read if not connected

        if self.backend_client.is_connected():
            try:
                data = self.backend_client.read_all()
                if data:
                    # Safe performance monitoring (optional)
                    if hasattr(self, '_last_data_time'):
                        current_time = QDateTime.currentDateTime().toMSecsSinceEpoch()
                        time_diff = current_time - self._last_data_time
                        if time_diff > 0 and len(data) > 10:  # Only log for significant data
                            data_rate = (len(data) * 1000) / time_diff
                            if data_rate > 5000:  # Log if high data rate (>5KB/s)
                                self.log("High data rate: {:.0f} B/s".format(data_rate))

                    self._last_data_time = QDateTime.currentDateTime().toMSecsSinceEpoch()

                    rx_line = f"RX: {' '.join(f'{b:02X}' for b in data)}"
                    self.monitor_dialog.append_rx(rx_line)
                    self.log_rx_data(data)

                    self.rx_buffer += data
                    packets, self.rx_buffer = self.backend_client.parse_rx_packets(self.rx_buffer)
                    if self.communication_log_store is not None:
                        self.communication_log_store.record_in(bytes(data), packets=packets)
                    for packet in packets:
                        self.packet_received.emit(packet)
                    events = self.packet_handler.handle_packets(
                        packets,
                        self.node_status,
                        log_sys_mode=not getattr(self, 'hide_sys_mode_chk', None) or not self.hide_sys_mode_chk.isChecked(),
                    )

                    for event in events:
                        self._apply_runtime_packet_event(event)

                    self.update_node_status_display()
                    return
            except Exception as e:
                self.log(f"Read failed: {e}")

    def _apply_runtime_packet_event(self, event: RuntimePacketEvent) -> None:
        """Bridge backend packet events into MainWindow-specific UI updates."""
        if event.kind == "log":
            if event.message:
                self.log(event.message)
            return

        if event.kind == "node_activity" and event.node_id is not None:
            self.update_node_activity(event.node_id)
            return

        if event.kind == "node_id_response" and event.node_id is not None:
            self.process_node_id_response(event.node_id, event.value or [])
            return

        if event.kind == "comm_test_packet" and event.node_id is not None and hasattr(self, "comm_monitor"):
            self.comm_monitor.process_test_packet(event.node_id, event.value)
            return

        if event.kind == "comm_test_finished" and event.node_id is not None and hasattr(self, "comm_monitor"):
            self.comm_monitor.handle_test_finished(event.node_id)
            return

        if event.kind == "node_version" and event.node_id is not None and hasattr(self, "comm_monitor"):
            self.comm_monitor.handle_node_version(event.node_id, event.value)
            return

        if event.kind == "comm_stats" and hasattr(self, "comm_monitor"):
            self.comm_monitor.handle_comm_stats(event.value)
            return

        if event.kind == "sys_mode":
            self.sys_mode = event.value
            self.update_status_ui()
            return

        if event.kind == "emergency_stop":
            self.emergency_stop_active = bool(event.value)
            return

        if event.kind == "zposs_sample":
            try:
                if hasattr(self, "zposs_plot") and self.zposs_plot and event.value:
                    adc_raw, physical_value = event.value
                    self.zposs_plot.update_plot_data(adc_raw, physical_value)
            except Exception as e:
                self.log(f"Failed to update ZPOSS plot: {e}")
            return

        if event.kind == "tof_sample":
            try:
                if hasattr(self, "tof_plot") and self.tof_plot:
                    self.tof_plot.update_plot_data(event.value)
            except Exception as e:
                self.log(f"Failed to update ToF plot: {e}")
            return

        if event.kind == "mcu_version":
            version = event.value or "Unknown"
            if version != self.mcu_version:
                self.mcu_version = version
                self.mcu_version_lbl.setText(f"MCU Firmware Version: {version}")
                self.log(f"MCU Firmware Version: {version}")
            else:
                self.log(f"MCU version already set to: {version}")

    def log(self, msg):
        """Append a message to the log box with timestamp and autoscroll handling."""
        # Filter periodic system mode logs if requested
        if "System Mode Response" in msg:
            if hasattr(self, 'hide_sys_mode_chk') and self.hide_sys_mode_chk.isChecked():
                return

        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        full_msg = f"[{timestamp}] {msg}"
        self.log_box.append(full_msg)
        
        # Handle autoscroll
        if hasattr(self, 'autoscroll_chk') and self.autoscroll_chk.isChecked():
            self.log_box.moveCursor(self.log_box.textCursor().MoveOperation.End)


    def test_all_connected_nodes(self):
        """Handle 'Test All Connected Nodes' button click"""
        # Extract connected nodes information
        connected_nodes = self.get_connected_nodes()  # You need to implement this method

        # Get MCU version (replace with actual implementation)
        mcu_version = getattr(self, 'mcu_version', None)  # Adjust based on your actual variable name

        if not connected_nodes:
            # Show error message box when no connected nodes
            from PyQt6.QtWidgets import QMessageBox
            error_box = QMessageBox()
            error_box.setIcon(QMessageBox.Icon.Warning)
            error_box.setText("No connected nodes")
            error_box.setWindowTitle("Error")
            error_box.exec()
            return

        # Create and show test all dialog if not already created or if closed
        if self.test_all_dialog is None:
            self.test_all_dialog = TestAllDialog(mcu_version, connected_nodes, self)
            # Handle dialog closure to reset the variable
            self.test_all_dialog.finished.connect(self.on_test_all_dialog_closed)
            
            # Position dialog to the right of main window
            main_geometry = self.geometry()
            self.test_all_dialog.move(
                main_geometry.right() + 10,
                main_geometry.top()
            )
            self.test_all_dialog.show()
        else:
            # If already open, just bring it to front and update content if needed
            # For now, we might want to recreate it to update connected nodes, 
            # or just show existing one. 
            # Let's close and recreate to ensure fresh data
            self.test_all_dialog.close()
            self.test_all_dialog = TestAllDialog(mcu_version, connected_nodes, self)
            self.test_all_dialog.finished.connect(self.on_test_all_dialog_closed)
            main_geometry = self.geometry()
            self.test_all_dialog.move(
                main_geometry.right() + 10,
                main_geometry.top()
            )
            self.test_all_dialog.show()
            self.test_all_dialog.raise_()
            self.test_all_dialog.activateWindow()

    def on_test_all_dialog_closed(self):
        """Handle cleanup when TestAllDialog is closed."""
        self.test_all_dialog = None

    def get_connected_nodes(self):
        """
        Return a list of node IDs that are currently marked as connected.
        """
        if not hasattr(self, 'node_status'):
            return []
        return connected_node_ids(self.node_status)

    def setup_logging(self):
        """Create a logs directory and initialize the daily log file."""
        self.rx_log_writer = RxLogWriter.create()
        
        self.log_file_path = str(self.rx_log_writer.log_file_path)
        self.log(f"BioBot Robot Arm Tester Version: {VERSION}")
        self.log(f"📝 Logging Rx data to {self.log_file_path}")

    def log_rx_data(self, data: bytes):
        """Save raw Rx bytes to the log file with a timestamp."""
        try:
            if self.rx_log_writer is None:
                self.setup_logging()
            self.rx_log_writer.write_rx_data(data)
        except Exception as e:
            print(f"Failed to log Rx data: {e}")
    def query_sys_mode(self):
        """Query global system mode from MCU."""
        if not self.is_connected:
            return
        try:
            self.backend_client.send_system_mode_query()
        except Exception as e:
            self.log(f"Failed to query system mode: {e}")

    def update_blink(self):
        """Toggle blink state and update UI."""
        if not self.is_connected:
            return
        
        self.blink_counter = (self.blink_counter + 1) % 12 # Least common multiple for 1Hz and 3Hz at 4Hz tick
        # Wait, 4Hz tick: 1Hz is every 4 ticks. 3Hz is every ~1.3 ticks.
        # Let's use 100ms (10Hz) tick instead.
        # blink_counter at 100ms:
        # 1Hz = 10 ticks cycle (5 on, 5 off) -> flip if counter % 10 == 0 / 5
        # 3Hz = ~3.3 ticks cycle (2 on, 1 off roughly) -> flip if counter % 3 == 0 (actually 3Hz is ~166ms pulse)
        
        # Let's adjust self.blink_timer.start(100) and use simple toggle logic
        self.blink_state = not self.blink_state
        self.update_status_ui()

    def update_status_ui(self):
        """Update system status LED and text."""
        text = self.sys_mode.get("text", "Unknown")
        color = self.sys_mode.get("color", "#808080")
        blink = self.sys_mode.get("blink", 0)
        error_code = self.sys_mode.get("error_code", self.sys_mode.get("code"))
        errors = self.sys_mode.get("errors", self.sys_mode.get("error"))
        error_count = self.sys_mode.get("error_count", 0)
        node_id = self.sys_mode.get("node_id")
        state_value = self.sys_mode.get("state_value")

        self.status_text_lbl.setText(f"System Status: {text}")

        if hasattr(self, "error_code_lbl"):
            self.error_code_lbl.setText(f"Error Code: {error_code if error_code is not None else 'None'}")

        if hasattr(self, "error_detail_lbl"):
            if isinstance(errors, (list, tuple, set)):
                error_list = ", ".join(str(error) for error in errors) if errors else "None"
            elif isinstance(errors, dict):
                error_list = ", ".join(f"{key}: {value}" for key, value in errors.items()) if errors else "None"
            elif errors:
                error_list = str(errors)
            else:
                error_list = "None"
            node_text = f"Node 0x{node_id:02X}" if isinstance(node_id, int) else "Node --"
            state_text = f"State 0x{state_value:02X}" if isinstance(state_value, int) else "State --"
            error_detail = f"{node_text}, {state_text}, Count {error_count}: {error_list}"
            self.error_detail_lbl.setText(f"Error Detail: {error_detail}")
            error_color = "#B00020" if error_code is not None or text == "Fault" else "#666666"
            self.error_code_lbl.setStyleSheet(f"font-weight: bold; color: {error_color};")
            self.error_detail_lbl.setStyleSheet(f"color: {error_color};")
        
        display_color = color
        if blink > 0:
            # Simple blink logic based on global blink_state
            # For 3Hz, it should blink faster, but for now let's just use the 100ms toggle
            if not self.blink_state:
                display_color = "transparent"
        
        self.status_led.setStyleSheet(f"border-radius: 8px; background-color: {display_color};")
