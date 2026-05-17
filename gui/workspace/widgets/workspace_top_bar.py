"""Compact top toolbar for workspace navigation and settings."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSizePolicy, QToolButton, QWidget

from ..models import NavigationItem
from .navigation_button import NavigationButton
from .layout_utils import clear_layout


class WorkspaceTopBar(QWidget):
    """Slim developer-tool-like toolbar for route switching and lightweight settings."""

    route_selected = pyqtSignal(str)
    action_requested = pyqtSignal(str)
    preference_toggled = pyqtSignal(str, bool)

    def __init__(self, project_name: str, config_path: Path, items: list[NavigationItem]) -> None:
        super().__init__()
        self.setObjectName("WorkspaceTopBar")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

        self._project_name = project_name
        self._buttons: dict[str, NavigationButton] = {}
        self._toggle_actions: dict[str, QAction] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        brand = self._build_brand_block(project_name)
        root.addWidget(brand, 0)

        self._navigation_host = QWidget()
        self._navigation_layout = QHBoxLayout(self._navigation_host)
        self._navigation_layout.setContentsMargins(0, 0, 0, 0)
        self._navigation_layout.setSpacing(6)
        root.addWidget(self._navigation_host, 0)

        self.settings_button = QToolButton()
        self.settings_button.setObjectName("ToolbarSettingsButton")
        self.settings_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.settings_button.setIcon(self._build_settings_icon())
        self.settings_button.setToolTip("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        self.settings_menu = QMenu(self)
        self.settings_menu.setObjectName("WorkspaceSettingsMenu")
        self.settings_button.setMenu(self.settings_menu)
        root.addWidget(self.settings_button, 0)

        self._rebuild_navigation_buttons(items)
        self._build_settings_menu(project_name, config_path)

    def _build_brand_block(self, project_name: str) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._project_chip = QLabel(project_name)
        self._project_chip.setObjectName("ToolbarProjectChip")
        layout.addWidget(self._project_chip)

        return container

    def _build_settings_icon(self) -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(8, 8)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5D4C43"))

        for _ in range(8):
            painter.drawRoundedRect(QRectF(4.6, -1.0, 2.6, 2.0), 0.8, 0.8)
            painter.rotate(45)

        painter.setPen(QPen(QColor("#5D4C43"), 1.35))
        painter.setBrush(QColor("#FFF7F0"))
        painter.drawEllipse(QRectF(-4.4, -4.4, 8.8, 8.8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5D4C43"))
        painter.drawEllipse(QRectF(-1.4, -1.4, 2.8, 2.8))

        painter.end()
        return QIcon(pixmap)

    def _rebuild_navigation_buttons(self, items: list[NavigationItem]) -> None:
        clear_layout(self._navigation_layout)
        self._buttons = {}

        for item in items:
            button = NavigationButton(item.label, item.description, variant="toolbar")
            button.setEnabled(item.enabled)
            button.clicked.connect(lambda checked=False, route_id=item.route_id: self.route_selected.emit(route_id))
            self._navigation_layout.addWidget(button, 0)
            self._buttons[item.route_id] = button

    def _build_settings_menu(self, project_name: str, config_path: Path) -> None:
        self.settings_menu.clear()

        for label in ("Workspace settings", project_name, f"Config: {config_path.name}"):
            title_action = QAction(label, self)
            title_action.setEnabled(False)
            self.settings_menu.addAction(title_action)

        self.settings_menu.addSeparator()

        for action_id, label in (
            ("open_legacy_runtime", "Open runtime"),
            ("refresh_workspace", "Refresh shell"),
            ("log_project_context", "Log context"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, value=action_id: self.action_requested.emit(value))
            self.settings_menu.addAction(action)

        self.settings_menu.addSeparator()

        for setting_id, label, checked in (
            ("auto_node_scan", "Auto node scan", True),
            ("restore_last_project", "Restore last project", True),
            ("write_trace_log", "Write trace log", False),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(checked)
            action.toggled.connect(lambda value, key=setting_id: self.preference_toggled.emit(key, value))
            self.settings_menu.addAction(action)
            self._toggle_actions[setting_id] = action

    def set_active_route(self, route_id: str) -> None:
        """Update checked state for all top-nav buttons."""
        for item_route_id, button in self._buttons.items():
            button.setChecked(item_route_id == route_id)

    def set_preference_state(self, setting_id: str, checked: bool) -> None:
        """Synchronize one dropdown toggle without re-emitting its signal."""
        action = self._toggle_actions.get(setting_id)
        if action is None or action.isChecked() == checked:
            return

        action.blockSignals(True)
        action.setChecked(checked)
        action.blockSignals(False)

    def update_config_path(self, config_path: Path) -> None:
        """Refresh the settings menu metadata after a versioned save."""
        self._build_settings_menu(self._project_name, config_path)

    def update_project_context(
        self,
        project_name: str,
        config_path: Path,
        items: list[NavigationItem] | None = None,
    ) -> None:
        """Refresh the current project identity, config path, and optional navigation state."""
        self._project_name = project_name
        self._project_chip.setText(project_name)
        if items is not None:
            self._rebuild_navigation_buttons(items)
        self._build_settings_menu(project_name, config_path)
