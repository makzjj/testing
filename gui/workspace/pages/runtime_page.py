"""Embedded runtime page implementation."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QScrollArea

from ..bridges import WorkspaceRuntimeBridge


class RuntimePage(QWidget):
    """Hosts the shared legacy runtime widget inside the workspace shell."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime_widget: QWidget | None = None
        self._scroll_area: QScrollArea | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

    def refresh(self) -> None:
        """Create and attach the shared runtime widget when the page becomes active."""
        self._ensure_runtime_widget()

    def _ensure_runtime_widget(self) -> QWidget:
        """Attach and return the shared runtime widget lazily to avoid eager native window creation."""
        if self._runtime_widget is None:
            self._runtime_widget = self._bridge.get_runtime_widget(self)
            
            # Create scroll area to wrap the runtime widget
            self._scroll_area = QScrollArea()
            self._scroll_area.setWidget(self._runtime_widget)
            self._scroll_area.setWidgetResizable(True)
            self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            
            # Add scroll area to layout
            self._layout.addWidget(self._scroll_area, 1)
        
        return self._runtime_widget
