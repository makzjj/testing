"""Embedded runtime page implementation."""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..bridges import WorkspaceRuntimeBridge


class RuntimePage(QWidget):
    """Hosts the shared legacy runtime widget inside the workspace shell."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__()
        self._bridge = bridge
        self._runtime_widget: QWidget | None = None

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

        if self._layout.indexOf(self._runtime_widget) == -1:
            self._layout.addWidget(self._runtime_widget, 1)
        return self._runtime_widget
