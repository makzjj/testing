from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QGroupBox, QFormLayout, QTableWidget, QTableWidgetItem, QHeaderView
from myconfig.constants import NODE_ID_MAPPING

class TestAllDialog(QDialog):
    def __init__(self, mcu_version, connected_nodes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Test All Connected Nodes")
        self.resize(700, 420)
        self.mcu_version = mcu_version
        self.connected_nodes = connected_nodes

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        # System Information Group
        sys_group = QGroupBox("System Information")
        sys_layout = QFormLayout()

        # MCU Version
        mcu_label = QLabel(f"{self.mcu_version if self.mcu_version else 'Unknown'}")
        sys_layout.addRow("MCU Version:", mcu_label)

        # Connected Nodes - replaced with a table that mirrors main window
        self.nodes_table = QTableWidget()
        headers = [
            "Node (Connected)",
            "Firmware Version",
            "Serial Number (UUID)",
            "Node Type",
            "Status",
        ]
        self.nodes_table.setColumnCount(len(headers))
        self.nodes_table.setHorizontalHeaderLabels(headers)
        self.nodes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        col_widths = [160, 140, 240, 120, 120]
        for i, w in enumerate(col_widths):
            self.nodes_table.setColumnWidth(i, w)
        self.nodes_table.verticalHeader().setVisible(False)
        self.nodes_table.setAlternatingRowColors(True)
        self.nodes_table.setMinimumHeight(200)
        self.nodes_table.setMaximumHeight(320)

        sys_layout.addRow("Connected Nodes:", self.nodes_table)

        sys_group.setLayout(sys_layout)
        layout.addWidget(sys_group)

        # Sensor Tests Group
        sensor_group = QGroupBox("Sensor Tests")
        sensor_layout = QHBoxLayout()

        zposs_btn = QPushButton("ZPOSS Sensor")
        zposs_btn.clicked.connect(self.open_zposs_plot)
        tof_btn = QPushButton("ToF Sensor")
        tof_btn.clicked.connect(self.open_tof_plot)

        sensor_layout.addWidget(zposs_btn)
        sensor_layout.addWidget(tof_btn)
        sensor_group.setLayout(sensor_layout)

        layout.addWidget(sensor_group)

        # Close Button
        btn_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # Initial fill
        self.update_connected_nodes_display()

    def open_zposs_plot(self):
        """Open ZPOSS plot window and set node to 5."""
        if self.parent():
            # Set target node to 5 (ZPOSS node)
            # Find index for data 5
            index = self.parent().target_node_id_combo.findData(5)
            if index >= 0:
                self.parent().target_node_id_combo.setCurrentIndex(index)

            # Show the plot window
            self.parent().zposs_plot.show()

    def open_tof_plot(self):
        """Open ToF plot window and set node to 5."""
        if self.parent():
            # Set target node to 5 (ToF node)
            index = self.parent().target_node_id_combo.findData(5)
            if index >= 0:
                self.parent().target_node_id_combo.setCurrentIndex(index)

            # Show the ToF plot window
            self.parent().tof_plot.show()

    def update_connected_nodes(self, connected_nodes):
        """Update the list of connected nodes and refresh display."""
        self.connected_nodes = connected_nodes
        self.update_connected_nodes_display()

    def update_connected_nodes_display(self):
        """Refresh the connected nodes table. Use fresh QTableWidgetItem objects and read data from parent.node_status if available."""
        nodes = self.connected_nodes or []

        # Build rows
        rows = []
        parent_status = {}
        if self.parent() and hasattr(self.parent(), 'node_status'):
            parent_status = self.parent().node_status

        for node in nodes:
            status = parent_status.get(node, {}) if parent_status else {}
            name = NODE_ID_MAPPING.get(node, '')
            if name:
                node_display = f"{name}({node:02d}) ✅ Connected"
            else:
                node_display = f"{node:02d} ✅ Connected"

            fw = status.get('firmware', '')
            uuid = status.get('uuid', '')
            node_type = status.get('type', '')
            interrupt = status.get('interrupt', '')

            rows.append([node_display, fw, uuid, node_type, interrupt])

        # Populate the table with fresh items (do not reuse items from parent)
        if not rows:
            self.nodes_table.setRowCount(1)
            no_item = QTableWidgetItem("No connected nodes")
            no_item.setTextAlignment(0x0004)  # Center alignment fallback
            # Clear other cells
            for c in range(self.nodes_table.columnCount()):
                empty_item = QTableWidgetItem("")
                self.nodes_table.setItem(0, c, empty_item)
            self.nodes_table.setItem(0, 0, no_item)
            try:
                self.nodes_table.setSpan(0, 0, 1, self.nodes_table.columnCount())
            except Exception:
                pass
            return

        self.nodes_table.setRowCount(len(rows))
        for r, row_vals in enumerate(rows):
            for c, v in enumerate(row_vals):
                item = QTableWidgetItem(str(v))
                item.setTextAlignment(0x0004)
                self.nodes_table.setItem(r, c, item)
