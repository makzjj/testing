"""Embedded runtime page implementation."""

from __future__ import annotations

from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ..bridges import WorkspaceRuntimeBridge


class RuntimePage(QWidget):
    """Hosts the shared legacy runtime widget inside the workspace shell."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__()
        self._bridge = bridge

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._bridge.get_runtime_widget(self), 1)

    def refresh(self) -> None:
        """Ensure the shared runtime widget remains attached to this page."""
        self._bridge.get_runtime_widget(self)
