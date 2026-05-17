# gui/motor_animation_module.py
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSlider, QGroupBox
from PyQt6.QtCore import Qt
from .rp_axis_animation import RpAxisAnimation

class MotorAnimationModule(QWidget):
    """
    Modular animation container that displays different visuals 
    based on the selected Node ID.
    """
    def __init__(self, node_id, parent=None):
        super().__init__(parent)
        self.node_id = node_id
        
        # Internal State
        self.miss_e_count = 0
        self.last_miss_offset = 0
        self.loop_count = 0
        self.current_pos = 0
        self.cpd = 2684.49 # Default for Rp
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.group_box = QGroupBox(f"Motor Visualization [Node {node_id:02d}]")
        self.group_layout = QVBoxLayout()
        self.group_layout.setSpacing(2)
        self.group_layout.setContentsMargins(4, 4, 4, 4)
        
        # Combined Info Row: Pos, Angle, Miss E, Miss Off, Loops
        info_row = QHBoxLayout()
        self.pos_lbl = QLabel("Pos: 0")
        self.angle_lbl = QLabel("Angle: 0.0\u00b0")
        self.miss_e_lbl = QLabel("Miss E: 0")
        self.miss_off_lbl = QLabel("Off: 0")
        self.loop_lbl = QLabel("Loops: 0")
        
        # Styles
        lbl_style = "font-size: 11px; font-weight: bold;"
        self.pos_lbl.setStyleSheet(lbl_style)
        self.angle_lbl.setStyleSheet(lbl_style)
        self.miss_e_lbl.setStyleSheet(lbl_style + " color: #D32F2F;")
        self.miss_off_lbl.setStyleSheet(lbl_style + " color: #D32F2F;")
        self.loop_lbl.setStyleSheet(lbl_style + " color: #2E7D32;")
        
        info_row.addWidget(self.pos_lbl)
        info_row.addWidget(self.angle_lbl)
        info_row.addStretch()
        info_row.addWidget(self.miss_e_lbl)
        info_row.addWidget(self.miss_off_lbl)
        info_row.addWidget(self.loop_lbl)
        self.group_layout.addLayout(info_row)

        # Specialized animations
        self.rp_animation = RpAxisAnimation()
        self.rp_animation.setMinimumSize(300, 140) # Smaller min height
        self.group_layout.addWidget(self.rp_animation, 1)
        
        # Slider Bar Section (More compact)
        slider_container = QHBoxLayout()
        slider_container.setContentsMargins(0, 0, 0, 0)
        
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(-10000, 400000)
        self.pos_slider.setFixedHeight(20)
        self.pos_slider.setStyleSheet("""
            QSlider::groove:horizontal { border: 1px solid #bbb; background: #eee; height: 4px; border-radius: 2px; }
            QSlider::handle:horizontal { background: #0078D7; border: 1px solid #005a9e; width: 4px; margin: -8px 0; border-radius: 2px; }
        """)
        
        slider_container.addWidget(QLabel("0"))
        slider_container.addWidget(self.pos_slider, 1)
        self.max_lbl = QLabel("375828")
        slider_container.addWidget(self.max_lbl)
        
        self.group_layout.addLayout(slider_container)
        
        self.group_box.setLayout(self.group_layout)
        self.layout.addWidget(self.group_box)
        
        self.current_node_id = None

    def set_node_id(self, node_id):
        """Update the animation type based on the Node ID."""
        # Visual type check
        if node_id == 8: # Rp
            self.rp_animation.setVisible(True)
            self.pos_slider.setRange(-10000, 400000)
            self.max_lbl.setText("375828")
        else:
            self.pos_slider.setRange(-100000, 500000)
            self.max_lbl.setText("Max")

    def set_position(self, pos):
        """Update both the visual animation and the slider."""
        self.current_pos = pos
        self.rp_animation.set_position(pos)
        self.pos_slider.setValue(int(pos))
        
        # Update text readouts
        self.pos_lbl.setText(f"Pos: {int(pos)}")
        if self.cpd != 0:
            current_degree = pos / self.cpd
        else:
            current_degree = 0.0
        self.angle_lbl.setText(f"Angle: {current_degree:.1f}\u00b0")

    def set_counts_per_degree(self, cpd):
        self.cpd = cpd
        self.set_position(self.current_pos) # Refresh display

    def increment_miss_e(self, offset):
        self.miss_e_count += 1
        self.last_miss_offset = offset
        self.update_ui()

    def increment_loops(self):
        self.loop_count += 1
        self.update_ui()

    def reset_counters(self):
        self.miss_e_count = 0
        self.last_miss_offset = 0
        self.loop_count = 0
        self.update_ui()

    def update_ui(self):
        """Update the UI labels from internal state."""
        self.miss_e_lbl.setText(f"Miss TPOS E: {self.miss_e_count}")
        self.miss_off_lbl.setText(f"Miss Off: {self.last_miss_offset}")
        self.loop_lbl.setText(f"Loops: {self.loop_count}")

    def set_theme(self, theme):
        self.rp_animation.set_theme(theme)
