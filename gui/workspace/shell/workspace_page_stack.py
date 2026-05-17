"""Route-aware page stack for the workspace shell."""

from __future__ import annotations

from PyQt6.QtWidgets import QStackedWidget, QWidget


class WorkspacePageStack(QStackedWidget):
    """Wraps a QStackedWidget with route-id lookup."""

    def __init__(self) -> None:
        super().__init__()
        self._route_to_index: dict[str, int] = {}

    def register_page(self, route_id: str, widget: QWidget) -> None:
        """Register one route-backed page widget."""
        self._route_to_index[route_id] = self.addWidget(widget)

    def show_page(self, route_id: str) -> None:
        """Show one route-backed page."""
        if route_id not in self._route_to_index:
            raise KeyError(f"Unknown workspace route: {route_id}")
        self.setCurrentIndex(self._route_to_index[route_id])
