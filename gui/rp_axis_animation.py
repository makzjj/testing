# gui/rp_axis_animation.py
import math
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QColor, QFont

class RpAxisAnimation(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_pos = 0  # in counts
        self.max_pos = 375828
        self.counts_per_degree = 2684.49
        self.setMinimumSize(300, 180)
        
        # Theme colors
        self.track_color = QColor("#D0D0D0")
        self.motor_color = QColor("#0078D7")
        self.home_color = QColor("#FF4500")
        self.text_color = QColor("#333333")

    def set_theme(self, theme):
        if theme == "dark":
            self.track_color = QColor("#444444")
            self.motor_color = QColor("#409EFF")
            self.text_color = QColor("#DCDCDC")
        else:
            self.track_color = QColor("#D0D0D0")
            self.motor_color = QColor("#0078D7")
            self.text_color = QColor("#333333")
        self.update()

    def set_position(self, pos):
        # Handle potential string input or None
        try:
            self.current_pos = float(pos)
        except (ValueError, TypeError):
            return
            
        # self.current_pos = max(0, min(self.current_pos, self.max_pos))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        
        # Center and Radius
        # Moved to top of box to maximize clearance from slider
        cx = width / 2
        cy = height * 0.25
        r = min(width * 0.4, height * 0.5)
        
        # Qt drawArc parameters:
        # Start angle: 200 degrees (approx 7 o'clock)
        # Span angle: 140 degrees (goes to 340 degrees, approx 5 o'clock)
        # This creates a concave-up arc.
        start_angle_deg = 200
        span_angle_deg = 140
        
        # Draw track background
        pen = QPen(self.track_color, 20, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        painter.drawArc(rect, start_angle_deg * 16, span_angle_deg * 16)
        
        # Draw Home Sensor indicator (fixed at 0 degrees, which is our start_angle)
        home_angle_rad = math.radians(start_angle_deg)
        hx = cx + r * math.cos(home_angle_rad)
        hy = cy - r * math.sin(home_angle_rad)
        
        painter.setBrush(self.home_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(hx - 10, hy - 5, 20, 10)) # Small block for sensor
        
        # Home Sensor Label
        painter.setPen(self.text_color)
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(int(hx - 30), int(hy - 15), "Home Sens.")

        # Calculate current position angle
        # 0 counts = start_angle_deg
        # 375828 counts = start_angle_deg + 140
        current_degree = self.current_pos / self.counts_per_degree
        # Constrain for animation if needed, but allow overshoot visualization
        display_degree = max(-10, min(current_degree, 150))
        
        current_angle_deg = start_angle_deg + display_degree
        current_angle_rad = math.radians(current_angle_deg)
        
        px = cx + r * math.cos(current_angle_rad)
        py = cy - r * math.sin(current_angle_rad)
        
        # Draw motor indicator (a simple line)
        painter.save()
        painter.translate(px, py)
        painter.rotate(-current_angle_deg + 90) # Orient line perpendicular to radius
        
        painter.setPen(QPen(self.motor_color, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(0, -15, 0, 15) # Vertical line in local space
        painter.restore()
        
        # Axis Label (Moved closer to arc)
        painter.setPen(self.text_color)
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(int(cx - 30), int(cy + r + 20), "Rp Axis")
        
        painter.end()
