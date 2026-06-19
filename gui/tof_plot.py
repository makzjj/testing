# gui/tof_plot.py
"""Time-of-Flight (ToF) plotting functionality."""

import numpy as np
from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton, QDoubleSpinBox, QTextEdit, QFileDialog
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer
from datetime import datetime
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from myconfig.constants import COMMANDS
from serial_conn.commands import CommandBuilder
from utils.deployment_paths import get_runtime_exports_dir


class ToFPlotWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ToF Sensor: Distance Measurement")
        self.resize(1000, 800)

        self.periodic_interval_ms = 500
        self.sending_periodic = False
        self.periodic_timer = QTimer(self)
        self.periodic_timer.timeout.connect(self._periodic_send)

        self.time_steps = []
        self.rx_data = []
        self.ma_data = []
        self.ma_window_size = 5 # For moving average
        self.log_data_records = []

        self.command_builder = CommandBuilder()

        self.setup_ui()
        self.setup_plot()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        control_layout = QHBoxLayout()
        control_layout.addWidget(QLabel("Reading Interval (ms):"))

        self.interval_spinbox = QSpinBox()
        self.interval_spinbox.setRange(200, 2000)
        self.interval_spinbox.setValue(self.periodic_interval_ms)
        self.interval_spinbox.setSuffix(" ms")
        control_layout.addWidget(self.interval_spinbox)

        # Actual Distance Input for Mapping Chart
        control_layout.addSpacing(20)
        control_layout.addWidget(QLabel("Actual Dist. (mm):"))
        self.actual_dist_input = QDoubleSpinBox()
        self.actual_dist_input.setRange(0, 10000)
        self.actual_dist_input.setValue(0.0)
        self.actual_dist_input.setDecimals(1)
        control_layout.addWidget(self.actual_dist_input)
        
        control_layout.addSpacing(20)

        # Start and Stop Buttons
        self.single_btn = QPushButton("ToF Single Read")
        self.single_btn.clicked.connect(self.single_read)
        control_layout.addWidget(self.single_btn)

        self.start_btn = QPushButton("ToF Read")
        self.start_btn.clicked.connect(self.start_periodic)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("ToF Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_periodic)
        control_layout.addWidget(self.stop_btn)

        self.periodic_status_label = QLabel("Stopped")
        control_layout.addWidget(self.periodic_status_label)
        
        control_layout.addSpacing(10)
        self.raw_val_lbl = QLabel("Raw: --- mm")
        self.raw_val_lbl.setStyleSheet("font-weight: bold; color: blue;")
        control_layout.addWidget(self.raw_val_lbl)
        
        control_layout.addSpacing(10)
        self.filtered_val_lbl = QLabel("Filtered: --- mm")
        self.filtered_val_lbl.setStyleSheet("font-weight: bold; color: red;")
        control_layout.addWidget(self.filtered_val_lbl)
        
        control_layout.addStretch()

        main_layout.addLayout(control_layout)

        toolbar = self.addToolBar("Plot Tools")

        clear_action = QAction('Clear Data', self)
        toolbar.addAction(clear_action)
        clear_action.triggered.connect(self.clear_plot_data)

        extract_action = QAction('Extract Log Data (Excel)', self)
        toolbar.addAction(extract_action)
        extract_action.triggered.connect(self.extract_log_data)

        # 2 Subplots
        self.fig, (self.ax_realtime, self.ax_mapping) = plt.subplots(1, 2, figsize=(12, 6))
        self.canvas = FigureCanvas(self.fig)
        main_layout.addWidget(self.canvas, stretch=3)

        # Log Window
        main_layout.addWidget(QLabel("Log: Timestamp | Actual Position (mm) | Raw value(mm) | filted distance(mm)"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        main_layout.addWidget(self.log_box, stretch=1)

    def setup_plot(self):
        """Configure both subplots."""
        # --- Chart 1: Real-time Data ---
        self.line_raw, = self.ax_realtime.plot([], [], label="Raw Distance", color="blue", alpha=0.5)
        self.line_ma, = self.ax_realtime.plot([], [], label="Moving Average", color="red", linewidth=2, linestyle=':')
        
        self.ax_realtime.set_xlabel("Time (samples)")
        self.ax_realtime.set_ylabel("Distance (mm)")
        self.ax_realtime.set_title("Real-Time ToF Distance")
        self.ax_realtime.set_ylim(0, 300)
        self.ax_realtime.grid(True)
        self.ax_realtime.legend()

        # --- Chart 2: Reading vs Actual Distance Mapping ---
        # Draw a placeholder baseline 1:1 mapping reference line
        self.ax_mapping.plot([0, 300], [0, 300], 'k--', alpha=0.3, label="Ideal 1:1")
        
        self.scatter_mapping = self.ax_mapping.scatter([], [], color='green', marker='o', s=30, label="Current Readings")
        
        self.ax_mapping.set_xlabel("Sensor Reading (mm)")
        self.ax_mapping.set_ylabel("Actual Physical Distance (Future)")
        self.ax_mapping.set_title("Reading vs. Actual Mapping")
        self.ax_mapping.set_xlim(0, 300)
        self.ax_mapping.set_ylim(0, 300)
        self.ax_mapping.grid(True)
        self.ax_mapping.legend()
        
        self.fig.tight_layout()

    def update_plot_data(self, tof_data: dict):
        """Update both plots with new data point."""
        if not isinstance(tof_data, dict):
            return

        raw_mm = tof_data.get("raw", 0.0)
        filtered_mm = tof_data.get("filtered", 0.0)

        # Update UI labels
        self.raw_val_lbl.setText(f"Raw: {raw_mm:.1f} mm")
        self.filtered_val_lbl.setText(f"Filtered: {filtered_mm:.1f} mm")

        current_time = len(self.time_steps)
        self.time_steps.append(current_time)
        self.rx_data.append(raw_mm)
        self.ma_data.append(filtered_mm)

        # Update Chart 1 lines
        self.line_raw.set_data(self.time_steps, self.rx_data)
        self.line_ma.set_data(self.time_steps, self.ma_data)
        
        self.ax_realtime.relim()
        self.ax_realtime.autoscale(enable=True, axis='x') 
        self.ax_realtime.set_ylim(bottom=0, top=300)

        # Update Chart 2 scatter
        # Use user-provided actual distance for mapping
        actual_dist = self.actual_dist_input.value()
        points = np.column_stack((self.rx_data, [actual_dist]*len(self.rx_data)))
        self.scatter_mapping.set_offsets(points)
        # We explicitly set limits to 0-300 so we don't need autoscale here

        # Logging Data
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        record = {
            'timestamp': timestamp_str,
            'actual_mm': actual_dist,
            'raw_mm': raw_mm,
            'filtered_mm': filtered_mm
        }
        self.log_data_records.append(record)

        log_line = f"[{timestamp_str}] Actual: {actual_dist:.1f} | Raw: {raw_mm:.1f} mm | Filtered: {filtered_mm:.1f} mm"
        self.log_box.append(log_line)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

        self.canvas.draw()

    def clear_plot_data(self):
        """Clear all plot data."""
        self.time_steps.clear()
        self.rx_data.clear()
        self.ma_data.clear()
        self.log_data_records.clear()
        self.log_box.clear()

        self.line_raw.set_data([], [])
        self.line_ma.set_data([], [])
        
        self.scatter_mapping.set_offsets(np.empty((0, 2)))
        
        self.ax_realtime.relim()
        self.ax_realtime.autoscale(enable=True, axis='x')
        self.ax_realtime.set_ylim(bottom=0, top=300)
        
        # Mapping chart takes fixed limits
        
        self.canvas.draw()

    def start_periodic(self):
        """Start periodic sending of ToF command (0xAB) to parent serial connection."""
        self.periodic_interval_ms = int(self.interval_spinbox.value())
        self.periodic_timer.setInterval(self.periodic_interval_ms)

        parent = self.parent()
        if parent is None or not hasattr(parent, 'serial_conn'):
            self.periodic_status_label.setText('No serial connection')
            return

        if not parent.serial_conn.is_connected():
            self.periodic_status_label.setText('Serial not connected')
            parent.log('⚠️ ToF start requested but serial not connected')
            return

        # Explicitly check if node 5 is available in system
        if 5 not in getattr(parent, 'node_status', {}):
            parent.log('⚠️ Node 5 (ToF) not found in connected nodes')

        if not self.sending_periodic:
            # Warning if actual distance is 0
            if self.actual_dist_input.value() == 0:
                self.log_box.append("⚠️ WARNING: Actual distance is 0. Please input an actual distance value for mapping.")

            self.sending_periodic = True
            self.periodic_timer.start()
            self.periodic_status_label.setText('Running')

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.interval_spinbox.setEnabled(False)

            parent.log(f"🔁 ToF periodic reading started ({self.periodic_interval_ms} ms)")
            self._periodic_send()

    def stop_periodic(self):
        """Stop periodic reading."""
        if self.sending_periodic:
            self.sending_periodic = False
            self.periodic_timer.stop()
            self.periodic_status_label.setText('Stopped')

            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.interval_spinbox.setEnabled(True)

            parent = self.parent()
            if parent:
                parent.log('⏹️ ToF periodic reading stopped by user')

    def _periodic_send(self):
        """Build and send the ToF command (0xAB) to Node 5."""
        parent = self.parent()
        if parent is None or not hasattr(parent, 'serial_conn'):
            return
        if not parent.serial_conn.is_connected():
            parent.log('⚠️ Serial disconnected during ToF sampling, stopping')
            self.stop_periodic()
            return

        # Fetch byte payload for Get_TOF (0xAB)
        cmd_bytes = COMMANDS.get("Get_TOF", [0xAB])

        try:
            # Assuming ToF sensor is Node 5
            payload = self.command_builder.build_can_over_uart_packet(0x01, 5, cmd_bytes)
            parent.serial_conn.write(payload)
            # parent.log(f"TX[ToF] → Node 05: {' '.join(f'{b:02X}' for b in payload)}")
        except Exception as e:
            parent.log(f"❌ Failed to send ToF command: {e}")

    def single_read(self):
        """Trigger a one-time ToF read."""
        parent = self.parent()
        if parent and hasattr(parent, 'serial_conn') and parent.serial_conn.is_connected():
            self._periodic_send()
            parent.log('🔘 ToF Single Read triggered')
        else:
            self.periodic_status_label.setText('Serial not connected')

    def extract_log_data(self):
        """Save log data in xlsx format."""
        if not getattr(self, 'log_data_records', None):
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Warning", "No log data to extract.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Save ToF Log Data",
            str(get_runtime_exports_dir() / "tof_log_data.csv"),
            "CSV Excel Files (*.csv);;All Files (*)"
        )
        
        if not filepath:
            return

        if not filepath.endswith('.csv'):
            filepath += '.csv'

        try:
            import csv
            with open(filepath, mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                # Write Headers
                writer.writerow(["Timestamp", "Actual Position (mm)", "Raw value(mm)", "filted distance(mm)"])
                
                # Write Records
                for record in self.log_data_records:
                    writer.writerow([
                        record['timestamp'],
                        f"{record['actual_mm']:.1f}",
                        f"{record['raw_mm']:.1f}",
                        f"{record['filtered_mm']:.1f}"
                    ])
            
            parent = self.parent()
            if parent:
                parent.log(f"✅ ToF Log Data saved to {filepath}")
        except Exception as e:
            parent = self.parent()
            if parent:
                parent.log(f"❌ Failed to save ToF Log Data: {e}")
