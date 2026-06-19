import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QCheckBox, QSpinBox, QFormLayout, QTextEdit, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, QTimer, QDateTime
from myconfig.constants import BCMD_COMM_TEST_START, NODE_ID_MAPPING
from myconfig.version import VERSION
from utils.deployment_paths import get_runtime_exports_dir

class CommMonitorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Communication Data Monitor")
        self.resize(1000, 850)
        self.main_window = parent
        
        self.stats = {}
        
        self.stats_timer = QTimer(self)
        self.stats_timer.setInterval(1000) # Poll every 1s
        self.stats_timer.timeout.connect(self.request_mcu_stats)
        
        self.is_running = False
        self.active_nodes = set()
        
        # Pre-test sequence state
        self.pretest_active = False
        self.pretest_nodes_pending = set()
        self.pretest_nodes_to_query = []
        self.node_versions = {}
        self.pretest_timer = QTimer(self)
        self.pretest_timer.setSingleShot(True)
        self.pretest_timer.timeout.connect(self.on_pretest_timeout)
        
        self.setup_ui()
    
    def showEvent(self, event):
        """Update info labels when the dialog is shown."""
        if self.main_window:
            # Update UART Baudrate
            if hasattr(self.main_window, 'baud_combo'):
                self.uart_baud_lbl.setText(self.main_window.baud_combo.currentText())
            
            # Update MCU Version
            mcu_ver = getattr(self.main_window, 'mcu_version', "Unknown")
            self.mcu_ver_lbl.setText(str(mcu_ver))
        super().showEvent(event)
        
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # --- Configuration Group ---
        config_group = QGroupBox("Test Configuration")
        config_layout = QVBoxLayout()
        
        # Configuration Form
        form_layout = QFormLayout()
        
        # 1st line: MCU version
        self.mcu_ver_lbl = QLabel("Unknown")
        form_layout.addRow("MCU Version:", self.mcu_ver_lbl)
        
        # 2nd line: UART baudRate and CANFD BaudRate
        baud_layout = QHBoxLayout()
        self.uart_baud_lbl = QLabel("Unknown")
        self.canfd_baud_lbl = QLabel("250 Kbps")
        baud_layout.addWidget(QLabel("UART:"))
        baud_layout.addWidget(self.uart_baud_lbl)
        baud_layout.addSpacing(20)
        baud_layout.addWidget(QLabel("CANFD:"))
        baud_layout.addWidget(self.canfd_baud_lbl)
        baud_layout.addStretch()
        form_layout.addRow("Baudrates:", baud_layout)
        
        # 3rd line: Nodes enable /disable (select only sub-nodes)
        node_layout = QHBoxLayout()
        self.node_checkboxes = {}
        target_nodes = [3, 4, 5, 6, 8, 9, 12] # Removed 16, 17 (Y/R Boards)
        for node_id in target_nodes:
            name = NODE_ID_MAPPING.get(node_id, f"{node_id:02x}")
            cb = QCheckBox(f"{name}({node_id})")
            node_layout.addWidget(cb)
            self.node_checkboxes[node_id] = cb
        form_layout.addRow("Nodes Enable/Disable:", node_layout)
        
        # 4th line: Frame count
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 65535)
        self.count_spin.setValue(1000)
        form_layout.addRow("Frame Count:", self.count_spin)
        
        # 5th line: Interval
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 10000)
        self.interval_spin.setValue(500)
        self.interval_spin.setSingleStep(10)
        self.interval_spin.setSuffix(" ms")
        form_layout.addRow("Interval:", self.interval_spin)

        # 6th line: System Status Update Control
        self.status_update_cb = QCheckBox("Enable MCU System Status Updates during test")
        self.status_update_cb.setChecked(True)
        form_layout.addRow("System Status:", self.status_update_cb)
        
        form_layout.addRow("System Status:", self.status_update_cb)
        
        config_layout.addLayout(form_layout)
        
        self.start_btn = QPushButton("Start Communication Test")
        self.start_btn.clicked.connect(self.start_test)
        
        self.fetch_btn = QPushButton("Fetch MCU Stats (0xBC)")
        self.fetch_btn.clicked.connect(self.request_mcu_stats)
        
        self.report_btn = QPushButton("Export Report")
        self.report_btn.clicked.connect(self.export_report)
        self.report_btn.setEnabled(False) # Enable after test
        
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.fetch_btn)
        btn_layout.addWidget(self.report_btn)
        config_layout.addLayout(btn_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        # --- Stats Sections ---
        stats_main_layout = QHBoxLayout()
        
        # Part 1: Target Nodes Stats
        target_group = QGroupBox("Target Nodes Monitoring (0xBF Frames)")
        target_layout = QVBoxLayout()
        
        self.stats_table = QTableWidget()
        headers = ["Node ID", "Total Rx", "Lost", "Rate(%)", "Freq(Hz)"]
        self.stats_table.setColumnCount(len(headers))
        self.stats_table.setHorizontalHeaderLabels(headers)
        self.stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.stats_table.setMinimumHeight(300) # Big enough for 7+ rows
        target_layout.addWidget(self.stats_table)
        target_group.setLayout(target_layout)
        stats_main_layout.addWidget(target_group, 2) # More stretch
        
        # Part 2: MCU Support Stats
        mcu_support_group = QGroupBox("MCU Support Monitoring (0xBC Stats)")
        mcu_support_layout = QVBoxLayout()
        
        mcu_form = QFormLayout()
        self.mcu_can_rx_lbl = QLabel("0")
        self.mcu_uart_tx_lbl = QLabel("0")
        self.mcu_uart_rx_lbl = QLabel("0")
        
        mcu_form.addRow("MCU CAN Rx:", self.mcu_can_rx_lbl)
        mcu_form.addRow("MCU UART Tx:", self.mcu_uart_tx_lbl)
        mcu_form.addRow("MCU UART Rx:", self.mcu_uart_rx_lbl)
        
        mcu_support_layout.addLayout(mcu_form)
        mcu_support_layout.addStretch()
        mcu_support_group.setLayout(mcu_support_layout)
        stats_main_layout.addWidget(mcu_support_group, 1)
        
        layout.addLayout(stats_main_layout)
        
        # --- Log Box ---
        layout.addWidget(QLabel("Frame Loss Log:"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box)
        
        # --- Bottom Buttons ---
        bottom_layout = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Stats")
        self.clear_btn.clicked.connect(self.reset_stats)
        bottom_layout.addWidget(self.clear_btn)
        
        bottom_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close) # Use close() to trigger closeEvent
        bottom_layout.addWidget(close_btn)
        
        layout.addLayout(bottom_layout)
        self.setLayout(layout)

    def closeEvent(self, event):
        """Ensure test is stopped when dialog is closed."""
        if self.is_running:
            self.start_test() # Toggle off
        super().closeEvent(event)

    def start_test(self):
        if not self.main_window or not self.main_window.serial_conn.is_connected():
            self.log("❌ Error: Serial port not connected.")
            return

        if not self.is_running:
            # --- START PRE-TEST VALIDATION ---
            selected_nodes = []
            for node_id, cb in self.node_checkboxes.items():
                if cb.isChecked():
                    selected_nodes.append(node_id)
            
            if not selected_nodes:
                self.log("⚠️ Warning: No nodes selected.")
                return

            self.log(f"🔍 Validating {len(selected_nodes)} nodes (sequential/50ms)...")
            self.pretest_active = True
            self.pretest_nodes_pending = set(selected_nodes)
            self.pretest_nodes_to_query = list(selected_nodes)
            self.node_versions = {}
            self.report_btn.setEnabled(False)
            self.start_btn.setEnabled(False)
            
            # Start the sequential query process
            self._send_next_pretest_query(0)
        else:
            # --- STOP TEST ---
            try:
                # Send 0xBE with mask 0 to stop
                payload = [0, 0, 0, 0, 0, 0, 0, 0, 1] # mask=0, count=0, interval=0, status_enable=1
                cmd_bytes = [0xBE] + payload
                full_packet = self.main_window.command_builder.build_can_over_uart_packet(0x01, 0x01, cmd_bytes)
                self.main_window.serial_conn.write(full_packet)
                
                self.log("🛑 Sent Stop Command (Mask: 0)")
                self.stats_timer.stop()
                self.start_btn.setText("Start Communication Test")
                self.start_btn.setStyleSheet("")
                self.is_running = False
                self.report_btn.setEnabled(True)
                
                # Auto-fetch final stats
                QTimer.singleShot(500, self.request_mcu_stats)
            except Exception as e:
                self.log(f"❌ Failed to stop test: {e}")

    def _send_next_pretest_query(self, index):
        """Send version queries sequentially with a 50ms delay."""
        if not self.pretest_active:
            return
            
        if index < len(self.pretest_nodes_to_query):
            node_id = self.pretest_nodes_to_query[index]
            try:
                # 0xC8 0x3F is Get Version
                full_packet = self.main_window.command_builder.build_can_over_uart_packet(0x01, node_id, [0xC8, 0x3F])
                self.main_window.serial_conn.write(full_packet)
                # self.log(f"   > Node {node_id:02d} query sent")
            except Exception as e:
                self.log(f"❌ Failed to query Node {node_id}: {e}")
                
            # Schedule next query in 50ms
            QTimer.singleShot(50, lambda: self._send_next_pretest_query(index + 1))
        else:
            # All queries sent, start the overall wait timer
            # Increased timeout slightly to account for the sequential spread
            self.pretest_timer.start(2000) 

    def on_pretest_timeout(self):
        """Handle failure of pre-test node validation."""
        if self.pretest_active:
            failed_nodes = ", ".join(str(n) for n in self.pretest_nodes_pending)
            self.log(f"❌ ABORT: Node(s) [{failed_nodes}] did not respond to version query!")
            QMessageBox.critical(self, "Test Aborted", f"The following nodes are not responding:\n{failed_nodes}\n\nPlease check connections.")
            self.pretest_active = False
            self.start_btn.setEnabled(True)

    def handle_node_version(self, node_id, version):
        """Handle version response during pre-test or normal mode."""
        self.node_versions[node_id] = version
        if self.pretest_active and node_id in self.pretest_nodes_pending:
            self.pretest_nodes_pending.remove(node_id)
            if not self.pretest_nodes_pending:
                self.pretest_timer.stop()
                self.pretest_active = False
                self._execute_start_test()

    def _execute_start_test(self):
        """Actually trigger the test after validation."""
        mask = 0
        self.active_nodes = set()
        for node_id, cb in self.node_checkboxes.items():
            if cb.isChecked():
                mask |= (1 << node_id)
                self.active_nodes.add(node_id)
        
        count = self.count_spin.value()
        interval = self.interval_spin.value()
        
        payload = [
            (mask >> 24) & 0xFF, (mask >> 16) & 0xFF, (mask >> 8) & 0xFF, mask & 0xFF,
            (count >> 8) & 0xFF, count & 0xFF,
            (interval >> 8) & 0xFF, interval & 0xFF,
            1 if self.status_update_cb.isChecked() else 0
        ]
        
        try:
            cmd_bytes = [0xBE] + payload
            full_packet = self.main_window.command_builder.build_can_over_uart_packet(0x01, 0x01, cmd_bytes)
            self.main_window.serial_conn.write(full_packet)
            
            self.log(f"🚀 Sent Start Command (Mask: 0x{mask:08X}, Count: {count}, Interval: {interval}ms)")
            self.reset_stats()
            self.stats_timer.start()
            self.start_btn.setText("Stop Communication Test")
            self.start_btn.setStyleSheet("background-color: #FF4444; color: white;")
            self.start_btn.setEnabled(True)
            self.is_running = True
            
            # Store expected count for each node in stats for capping
            for node_id in self.active_nodes:
                if node_id not in self.stats:
                    self.stats[node_id] = {'expected_total': count}
                else:
                    self.stats[node_id]['expected_total'] = count
        except Exception as e:
            self.log(f"❌ Failed to start test: {e}")
            self.start_btn.setEnabled(True)

    def reset_stats(self):
        self.stats = {}
        self.stats_table.setRowCount(0)
        self.log_box.clear()
        self.mcu_can_rx_lbl.setText("0")
        self.mcu_uart_tx_lbl.setText("0")
        self.mcu_uart_rx_lbl.setText("0")
        self.log("🧹 Stats reset.")

    def request_mcu_stats(self):
        """Send 0xBC command to MCU to get latest stats."""
        if self.main_window and self.main_window.serial_conn.is_connected():
            try:
                # 0xBC command (no payload) to MCU (Node 1)
                full_packet = self.main_window.command_builder.build_can_over_uart_packet(0x01, 0x01, [0xBC])
                self.main_window.serial_conn.write(full_packet)
            except Exception:
                pass

    def handle_comm_stats(self, stats):
        """Update MCU stats labels with data from 0xBC response."""
        self.mcu_can_rx_lbl.setText(str(stats.get('can_rx', 0)))
        self.mcu_uart_tx_lbl.setText(str(stats.get('uart_tx', 0)))
        self.mcu_uart_rx_lbl.setText(str(stats.get('uart_rx', 0)))

    def handle_test_finished(self, node_id):
        """Handle 0xBD (Test Finished) notification from a node."""
        if self.is_running and node_id in self.active_nodes:
            self.active_nodes.remove(node_id)
            node_name = f"{NODE_ID_MAPPING.get(node_id, 'Node')}({node_id:02d})"
            self.log(f"✅ {node_name} finished sending test frames.")
            
            if not self.active_nodes:
                self.log("🏁 All target nodes finished. Stopping test.")
                self.start_test() # Toggle stop
                # Auto-fetch final stats again for safety
                QTimer.singleShot(1000, self.request_mcu_stats)

    def process_test_packet(self, node_id, seq):
        current_time = QDateTime.currentDateTime().toMSecsSinceEpoch()
        
        if node_id not in self.stats or 'last_seq' not in self.stats[node_id]:
            expected_total = self.stats.get(node_id, {}).get('expected_total', 1000)
            self.stats[node_id] = {
                'last_seq': 0xFFFF, 
                'total': 0,
                'lost': 0,
                'start_time': current_time,
                'last_time': current_time,
                'expected_total': expected_total,
                'row': self.stats_table.rowCount()
            }
            self.stats_table.insertRow(self.stats[node_id]['row'])
            # Removed return to process first packet normally

        stat = self.stats[node_id]
        stat['total'] += 1
        
        # --- Robust Sequence Parsing (Refined) ---
        # 1. Endianness Detection Heuristic
        # Some nodes might send Little Endian sequence numbers (0x0100 instead of 0x0001)
        seq_be = seq
        seq_le = ((seq & 0xFF) << 8) | (seq >> 8)
        
        expected = (stat['last_seq'] + 1) & 0xFFFF
        
        diff_be = (seq_be - expected) & 0xFFFF
        diff_le = (seq_le - expected) & 0xFFFF
        
        # Decide which sequence to use:
        # If the BE jump is huge (e.g. > 100) but the LE jump is tiny (e.g. 0-2),
        # then it's almost certainly a Little Endian sequence.
        if diff_be > 100 and diff_le <= 2:
            seq = seq_le
            diff = diff_le
        else:
            seq = seq_be
            diff = diff_be
            
        # 2. Sequence Jump Handling
        if diff != 0:
            # Only count as lost if it's a forward jump < 30000 (standard wrap handling)
            if diff < 30000:
                stat['lost'] += diff
                # Only log if it's a small jump to avoid flooding
                if diff < 100:
                    self.log(f"⚠️ Node {node_id:02d}: Frame Loss detected! Expected {expected:04X}, Got {seq:04X} (Lost: {diff})")
            else:
                # diff > 30000 indicates out-of-order or major reset.
                # Do NOT update last_seq backward if it's just out-of-order
                # Unless we are very far behind (likely a node reset)
                if diff > 65000: # Very close behind: likely just out-of-order
                    return # Ignore this packet for sequence tracking, but it was already counted in 'total'
        
        # 3. Physically Believable Capping
        # Ensure reported Lost never makes Total+Lost exceed Expected count
        expected_test_total = stat.get('expected_total', 10000)
        if stat['total'] + stat['lost'] > expected_test_total:
            stat['lost'] = max(0, expected_test_total - stat['total'])

        stat['last_seq'] = seq
        stat['last_time'] = current_time
        
        self.update_table_row(node_id)

    def update_table_row(self, node_id):
        stat = self.stats[node_id]
        row = stat['row']
        
        node_name = f"{NODE_ID_MAPPING.get(node_id, 'Node')}({node_id:02d})"
        
        loss_rate = (stat['lost'] / (stat['total'] + stat['lost'])) * 100 if (stat['total'] + stat['lost']) > 0 else 0
        
        duration = (stat['last_time'] - stat['start_time']) / 1000.0
        freq = stat['total'] / duration if duration > 0 else 0
        
        items = [
            node_name,
            str(stat['total']),
            str(stat['lost']),
            f"{loss_rate:.2f}%",
            f"{freq:.1f}"
        ]
        
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.stats_table.setItem(row, col, item)

    def log(self, msg):
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        self.log_box.append(f"[{timestamp}] {msg}")

    def export_report(self):
        """Generate and save the gTest style testing report."""
        try:
            report_text = self.generate_report()
            
            file_name, _ = QFileDialog.getSaveFileName(
                self, "Save Test Report", 
                str(get_runtime_exports_dir() / f"CommTestReport_{QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.txt"),
                "Text Files (*.txt);;Log Files (*.log)"
            )
            
            if file_name:
                with open(file_name, 'w', encoding='utf-8') as f:
                    f.write(report_text)
                self.log(f"💾 Report saved to {os.path.basename(file_name)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to generate report: {e}")

    def generate_report(self):
        """Build the report string in gTest style."""
        now = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        mcu_ver = self.mcu_ver_lbl.text()
        count = self.count_spin.value()
        interval = self.interval_spin.value()
        
        # Calculate expected vs actual
        num_nodes = len(self.stats)
        total_expected = num_nodes * count
        
        mcu_can_rx = int(self.mcu_can_rx_lbl.text())
        software_rx = sum(s['total'] for s in self.stats.values())
        
        lines = []
        lines.append(f"[==========] Running Communication Test")
        lines.append(f"[----------] Global Test Conditions:")
        lines.append(f"[          ] Tester Software Version: {VERSION}")
        lines.append(f"[          ] Timestamp: {now}")
        lines.append(f"[          ] MCU Firmware Version: {mcu_ver}")
        
        for nid, ver in self.node_versions.items():
            name = NODE_ID_MAPPING.get(nid, f"Node{nid}")
            lines.append(f"[          ] Node {name}({nid:02d}) Version: {ver}")
            
        lines.append(f"[          ] Expected Frames Per Node: {count} | Interval: {interval}ms")
        lines.append(f"[----------]")
        
        passed_count = 0
        for nid, stat in self.stats.items():
            name = f"{NODE_ID_MAPPING.get(nid, 'Node')}({nid:02d})"
            test_name = f"CommTest.{name}"
            lines.append(f"[ RUN      ] {test_name}")
            
            duration = (stat['last_time'] - stat['start_time'])
            if stat['lost'] == 0 and stat['total'] >= count:
                lines.append(f"[       OK ] {test_name} ({duration} ms) | Total: {stat['total']}, Lost: 0, Rate: 0.00%")
                passed_count += 1
            else:
                loss_rate = (stat['lost'] / (stat['total'] + stat['lost'])) * 100 if (stat['total'] + stat['lost']) > 0 else 0
                lines.append(f"[  FAILED  ] {test_name} ({duration} ms) | Total: {stat['total']}, Lost: {stat['lost']}, Rate: {loss_rate:.2f}%")
        
        lines.append(f"[----------]")
        lines.append(f"[==========] {num_nodes} tests ran.")
        lines.append(f"[  PASSED  ] {passed_count} tests.")
        if passed_count < num_nodes:
            lines.append(f"[  FAILED  ] {num_nodes - passed_count} tests.")
        
        lines.append("\nMCU Health & Path Analysis:")
        lines.append(f"- Expected Total Frames: {total_expected}")
        lines.append(f"- MCU CAN Rx Counter: {mcu_can_rx}")
        lines.append(f"- Software Rx Counter: {software_rx}")
        
        is_uart_good = (software_rx == mcu_can_rx)
        is_can_good = (mcu_can_rx == total_expected)
        
        overall_status = "[PASS]" if (is_uart_good and is_can_good and passed_count == num_nodes) else "[FAIL]"
        lines.append(f"- Overall Path Status: {overall_status}")
        
        diagnostic = []
        if is_uart_good:
            diagnostic.append("  - UART Communication: [GOOD] (Software Rx matches MCU CAN Rx)")
        else:
            diff = mcu_can_rx - software_rx
            diagnostic.append(f"  - UART Communication: [LOSS DETECTED] (MCU sent {mcu_can_rx}, PC received {software_rx}. Loss: {diff})")
            
        if is_can_good:
            diagnostic.append("  - CAN Transmission: [GOOD] (MCU CAN Rx matches Expected Frames)")
        elif mcu_can_rx < total_expected:
            diff = total_expected - mcu_can_rx
            diagnostic.append(f"  - CAN Transmission: [LOSS DETECTED] (Target Nodes sent but MCU did not see {diff} frames)")
        else:
            diagnostic.append(f"  - CAN Transmission: [EXTRA DATA] (MCU saw {mcu_can_rx - total_expected} more frames than expected)")
            
        lines.extend(diagnostic)
        
        lines.append(f"\nTerminal Stats:")
        lines.append(f"- MCU UART Tx Bursts: {self.mcu_uart_tx_lbl.text()}")
        lines.append(f"- MCU UART Rx Bytes: {self.mcu_uart_rx_lbl.text()}")
        
        return "\n".join(lines)
