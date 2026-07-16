from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from myconfig.project_loader import load_available_projects
from myconfig.project_models import ProjectDefinition, ValidationIssue
from services.node_motion_calibration_store import NodeMotionCalibrationStore


BRAND_IMAGE_PATH = Path(__file__).resolve().parents[1] / "resources" / "Screenshot 2026-04-01 132426.png"


def _make_shadow(color: str, blur: int, y_offset: int) -> QGraphicsDropShadowEffect:
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(QColor(color))
    return shadow


class SelectorBackground(QWidget):
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect())
        bg = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.bottom()))
        bg.setColorAt(0.0, QColor("#FFFDFC"))
        bg.setColorAt(0.55, QColor("#FFF7F1"))
        bg.setColorAt(1.0, QColor("#FFF1E5"))
        painter.fillRect(rect, bg)

        for center, radius, color in (
            (QPointF(rect.left() + 140, rect.top() + 88), 210, QColor(255, 171, 76, 72)),
            (QPointF(rect.right() - 110, rect.top() + 170), 230, QColor(255, 214, 160, 88)),
            (QPointF(rect.right() - 50, rect.bottom() - 28), 250, QColor(255, 234, 210, 120)),
        ):
            glow = QRadialGradient(center, radius)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, radius, radius)

        painter.setPen(QPen(QColor("#F0DFD0"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(18, 18, -18, -18), 34, 34)


class ProgramSelectorWindow(QMainWindow):
    def __init__(self, node_motion_calibration_store: NodeMotionCalibrationStore | None = None) -> None:
        super().__init__()
        self._projects: list[ProjectDefinition] = []
        self._invalid_projects: list[ValidationIssue] = []
        self._workspace_windows: list[QMainWindow] = []
        self._node_motion_calibration_store = node_motion_calibration_store or NodeMotionCalibrationStore.load_default()
        self.setWindowTitle("BioBot Robot Arm Tester")
        self.resize(1120, 680)
        self._setup_ui()
        self._reload_projects()

    def _setup_ui(self) -> None:
        central = SelectorBackground()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(8)
        root.addStretch(1)

        shell = QWidget()
        shell.setFixedSize(1000, 628)
        shell.setStyleSheet(
            """
            QWidget#Shell {
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid #F1E2D5;
                border-radius: 32px;
            }
            QLabel {
                color: #4B3328;
            }
            QLabel#Caption {
                color: #9B7961;
                font-size: 14px;
            }
            QListWidget#ProjectList {
                background: #FFFFFF;
                border: 1px solid #EDC8A8;
                border-radius: 16px;
                padding: 8px;
                outline: none;
            }
            QListWidget#ProjectList::item {
                border: none;
                border-radius: 10px;
                color: #634126;
                padding: 10px 12px;
                margin: 2px 0;
            }
            QListWidget#ProjectList::item:selected {
                background: #FFF0E1;
                color: #8A4A1E;
            }
            QListWidget#ProjectList::item:hover {
                background: #FFF7F1;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 12px;
                margin: 10px 4px 10px 0px;
            }
            QScrollBar::handle:vertical {
                background: #F2B37F;
                border-radius: 6px;
                min-height: 28px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
                border: none;
            }
            QPushButton#PrimaryButton {
                background: #F28A34;
                color: white;
                border: none;
                border-radius: 16px;
                padding: 12px 18px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#PrimaryButton:hover {
                background: #DE7724;
            }
            QPushButton#PrimaryButton:disabled {
                background: #E8C8AC;
                color: #F5F8FA;
            }
            QPushButton#SecondaryButton {
                background: #FFFFFF;
                color: #7A5A44;
                border: 1px solid #EBC9AB;
                border-radius: 16px;
                padding: 12px 18px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#SecondaryButton:hover {
                background: #FFF8F2;
            }
            """
        )
        shell.setObjectName("Shell")
        shell.setGraphicsEffect(_make_shadow("#E8D3C2", 28, 12))

        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(28, 28, 28, 28)
        shell_layout.setSpacing(28)

        brand_column = QVBoxLayout()
        brand_column.setContentsMargins(0, 0, 0, 0)
        brand_column.setSpacing(10)

        self.brand_image = QLabel()
        self.brand_image.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.brand_image.setMinimumHeight(190)
        self._set_brand_pixmap()

        side_title = QLabel("BioBot Robot Arm Tester")
        side_title_font = QFont("Segoe UI", 20)
        side_title_font.setBold(True)
        side_title.setFont(side_title_font)
        side_title.setStyleSheet("color: #4B3328;")

        side_caption = QLabel("Select a project and open its workspace.")
        side_caption.setObjectName("Caption")
        side_caption.setWordWrap(True)

        brand_column.addWidget(self.brand_image)
        brand_column.addWidget(side_title)
        brand_column.addWidget(side_caption)
        brand_column.addStretch(1)

        content = QVBoxLayout()
        content.setContentsMargins(0, 8, 0, 0)
        content.setSpacing(12)

        title = QLabel("Select Project")
        title_font = QFont("Segoe UI", 22)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #6E3E1D;")

        list_caption = QLabel("Project list")
        list_caption.setObjectName("Caption")

        self.project_list = QListWidget()
        self.project_list.setObjectName("ProjectList")
        self.project_list.setMinimumWidth(520)
        self.project_list.setMinimumHeight(388)
        self.project_list.setMaximumHeight(420)
        self.project_list.itemSelectionChanged.connect(self._update_selector_state)
        self.project_list.itemDoubleClicked.connect(lambda *_: self._open_selected_workspace())

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch(1)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("SecondaryButton")
        self.cancel_button.setFixedSize(112, 44)
        self.cancel_button.clicked.connect(self.close)

        self.open_button = QPushButton("Open")
        self.open_button.setObjectName("PrimaryButton")
        self.open_button.setFixedSize(112, 44)
        self.open_button.clicked.connect(self._open_selected_workspace)

        actions.addWidget(self.cancel_button)
        actions.addWidget(self.open_button)

        content.addWidget(title)
        content.addWidget(list_caption)
        content.addWidget(self.project_list, 1)
        content.addLayout(actions)

        shell_layout.addLayout(brand_column, 36)
        shell_layout.addLayout(content, 64)

        root.addWidget(shell, 0, Qt.AlignmentFlag.AlignCenter)
        root.addStretch(1)

    def _set_brand_pixmap(self) -> None:
        pixmap = QPixmap(str(BRAND_IMAGE_PATH))
        if pixmap.isNull():
            self.brand_image.setText("BioBot")
            return

        scaled = pixmap.scaled(
            260,
            190,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.brand_image.setPixmap(scaled)

    def _reload_projects(self) -> None:
        load_result = load_available_projects()
        self._projects = load_result.valid_projects
        self._invalid_projects = load_result.invalid_projects
        self.project_list.clear()

        for project in self._projects:
            item = QListWidgetItem(project.display_name)
            item.setData(Qt.ItemDataRole.UserRole, project)
            self.project_list.addItem(item)

        if not self._projects:
            placeholder_item = QListWidgetItem("No valid projects available")
            placeholder_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.project_list.addItem(placeholder_item)

        invalid_summary = self._build_invalid_project_summary()
        self.project_list.setToolTip(invalid_summary)
        self.open_button.setToolTip(invalid_summary if not self._projects else "")

        if self._projects:
            self.project_list.setCurrentRow(0)

        self._update_selector_state()

    def _update_selector_state(self) -> None:
        item = self.project_list.currentItem()
        project = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self.open_button.setEnabled(isinstance(project, ProjectDefinition))

    def _open_selected_workspace(self) -> None:
        item = self.project_list.currentItem()
        project = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(project, ProjectDefinition):
            QMessageBox.information(self, "No Project Selected", "Please select a project first.")
            return

        from gui.workspace.shell.project_workspace_window import ProjectWorkspaceWindow

        window = ProjectWorkspaceWindow(project, node_motion_calibration_store=self._node_motion_calibration_store)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.destroyed.connect(lambda *_: self._restore_selector(window))
        self._workspace_windows.append(window)
        self.hide()
        window.show()
        window.raise_()
        window.activateWindow()

    def _restore_selector(self, window: QMainWindow) -> None:
        self._workspace_windows = [item for item in self._workspace_windows if item is not window]
        self.show()
        self.raise_()
        self.activateWindow()

    def _build_invalid_project_summary(self) -> str:
        if not self._invalid_projects:
            return ""

        summary_lines = ["Some project configs are invalid:"]
        for issue in self._invalid_projects[:3]:
            summary_lines.append(f"- {issue.path.name}: {issue.message}")
        if len(self._invalid_projects) > 3:
            summary_lines.append(f"- ...and {len(self._invalid_projects) - 3} more issue(s)")
        return "\n".join(summary_lines)
