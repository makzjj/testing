# gui/zposs_plot.py
"""ZPOSS plotting functionality."""

import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton
from PyQt6.QtGui import QAction  # QAction 应该从 QtGui 导入
from PyQt6.QtCore import QTimer
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.widgets import Button
from myconfig.constants import COMMANDS, BCMD_ZPOSS
from serial_conn.commands import CommandBuilder


class ZPOSSPlotWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ZPOSS: ADC vs Physical Value Mapping")
        self.resize(900, 700)

        self.periodic_interval_ms = 500
        self.sending_periodic = False
        self.periodic_timer = QTimer(self)
        self.periodic_timer.timeout.connect(self._periodic_send)

        self.rx_adc = []
        self.rx_phys = []

        self.command_builder = CommandBuilder()

        self.setup_ui()
        self.setup_plot()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Interval (ms):"))

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(100, 5000)
        self.interval_spinbox.setValue(self.periodic_interval_ms)
        self.interval_spinbox.setSuffix(" ms")
        control_layout.addWidget(self.interval_spinbox)

        # Manual send button for quick testing
        self.send_once_btn = QPushButton("Send once")
        self.send_once_btn.clicked.connect(self._manual_send_once)
        control_layout.addWidget(self.send_once_btn)

        self.periodic_status_label = QLabel("Stopped")
        control_layout.addWidget(self.periodic_status_label)
        control_layout.addStretch()

        main_layout.addLayout(control_layout)

        toolbar = self.addToolBar("Plot Tools")

        self.start_action = QAction('ZPOSS Start', self)
        toolbar.addAction(self.start_action)

        self.stop_action = QAction('ZPOSS Stop', self)
        toolbar.addAction(self.stop_action)

        clear_action = QAction('Clear Data', self)
        toolbar.addAction(clear_action)

        # Connect actions
        self.start_action.triggered.connect(self.start_periodic)
        self.stop_action.triggered.connect(self.stop_periodic)
        clear_action.triggered.connect(self.clear_plot_data)

        self.fig, self.ax = plt.subplots(figsize=(10, 6))
        self.canvas = FigureCanvas(self.fig)
        main_layout.addWidget(self.canvas)

    def setup_plot(self):
        adc_min, adc_max = 647, 1001
        phys_min, phys_max = 36.54, 87.6

        self.ax.scatter([adc_min, adc_max], [phys_min, phys_max],
                        color="red", label="Endpoints")
        self.rx_scatter = self.ax.scatter([], [], color='green',
                                          marker='o', s=30, label="RX Data")

        self.ax.set_xlabel("ADC Raw Value")
        self.ax.set_ylabel("Physical Value")
        self.ax.set_title("ADC Raw vs Physical Value Mapping")
        self.ax.grid(True)
        self.ax.legend()

    def update_plot_data(self, adc_value: int, physical_value: float):
        """Update plot with new data point."""
        self.rx_adc.append(adc_value)
        self.rx_phys.append(physical_value)

        if hasattr(self, 'rx_scatter') and self.rx_scatter:
            points = np.column_stack((self.rx_adc, self.rx_phys))
            self.rx_scatter.set_offsets(points)
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw()

    def clear_plot_data(self):
        """Clear all plot data."""
        self.rx_adc.clear()
        self.rx_phys.clear()

        if hasattr(self, 'rx_scatter') and self.rx_scatter:
            self.rx_scatter.set_offsets(np.empty((0, 2)))
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw()

    def start_periodic(self):
        """Start periodic sending of ZPOSS command to parent serial connection."""
        # Update interval from spinbox
        self.periodic_interval_ms = int(self.interval_spinbox.value())
        self.periodic_timer.setInterval(self.periodic_interval_ms)

        # Ensure we have a parent with a serial connection
        parent = self.parent()
        if parent is None or not hasattr(parent, 'serial_conn'):
            self.periodic_status_label.setText('No serial connection')
            return

        if not parent.serial_conn.is_connected():
            self.periodic_status_label.setText('Serial not connected')
            parent.log('⚠️ ZPOSS start requested but serial not connected')
            return

        # Start timer
        if not self.sending_periodic:
            self.sending_periodic = True
            self.periodic_timer.start()
            self.periodic_status_label.setText('Running')

            # Disable start action and spinbox, enable stop
            try:
                if hasattr(self, 'start_action'):
                    self.start_action.setEnabled(False)
                if hasattr(self, 'stop_action'):
                    self.stop_action.setEnabled(True)
                self.interval_spinbox.setEnabled(False)
            except Exception:
                pass

            parent.log(f"🔁 ZPOSS periodic started ({self.periodic_interval_ms} ms)")

            # Send immediately once
            self._periodic_send()

    def stop_periodic(self):
        """Stop periodic sending."""
        if self.sending_periodic:
            self.sending_periodic = False
            self.periodic_timer.stop()
            self.periodic_status_label.setText('Stopped')

            # Re-enable start action and spinbox, disable stop
            try:
                if hasattr(self, 'start_action'):
                    self.start_action.setEnabled(True)
                if hasattr(self, 'stop_action'):
                    self.stop_action.setEnabled(False)
                self.interval_spinbox.setEnabled(True)
            except Exception:
                pass

            parent = self.parent()
            if parent and hasattr(parent, 'serial_conn') and parent.serial_conn.is_connected():
                parent.log('⏹️ ZPOSS periodic stopped by user')
                # Optionally send ZPOSS stop command if defined
                stop_bytes = COMMANDS.get('ZPOSS_Periodic_Stop', [])
                if stop_bytes:
                    payload = self.command_builder.build_can_over_uart_packet(0x01, 5, stop_bytes)
                    try:
                        parent.serial_conn.write(payload)
                        parent.log(f"TX[ZPOSS Stop] → {' '.join(f'{b:02X}' for b in payload)}")
                    except Exception as e:
                        parent.log(f"❌ Failed to send ZPOSS stop: {e}")

    def _periodic_send(self):
        """Internal: build and send the ZPOSS command to node 5 (ZPOSS node)."""
        parent = self.parent()
        if parent is None or not hasattr(parent, 'serial_conn'):
            return
        if not parent.serial_conn.is_connected():
            # stop if serial disconnected
            parent.log('⚠️ Serial disconnected during ZPOSS sampling, stopping')
            self.stop_periodic()
            return

        # Get command bytes for periodic start (fall back to Get ZPOSS)
        cmd_name = 'ZPOSS_Periodic_Start' if 'ZPOSS_Periodic_Start' in COMMANDS else 'Get ZPOSS'
        cmd_bytes = COMMANDS.get(cmd_name, COMMANDS.get('Get ZPOSS', []))

        if not cmd_bytes:
            parent.log('❌ No ZPOSS command bytes defined')
            return

        # Build CAN-over-UART for node 5 (ZPOSS sensor node)
        try:
            payload = self.command_builder.build_can_over_uart_packet(0x01, 5, cmd_bytes)
            parent.serial_conn.write(payload)
            parent.log(f"TX[ZPOSS] → Node 05: {' '.join(f'{b:02X}' for b in payload)}")
        except Exception as e:
            parent.log(f"❌ Failed to send ZPOSS command: {e}")

    def _manual_send_once(self):
        """User-facing helper to send a single ZPOSS command for testing."""
        # Keep behavior same as periodic single send but without checks that disable UI
        parent = self.parent()
        if parent is None or not hasattr(parent, 'serial_conn'):
            return
        if not parent.serial_conn.is_connected():
            parent.log('⚠️ Cannot send ZPOSS once: serial not connected')
            return
        # Call periodic send logic (it checks connection and commands)
        self._periodic_send()
