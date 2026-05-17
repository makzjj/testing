"""Launcher for the existing legacy runtime window."""

from __future__ import annotations

from PyQt6.QtCore import Qt

from myconfig.project_models import ProjectDefinition

from ..constants import WORKSPACE_TITLE_PREFIX


class LegacyRuntimeLauncher:
    """Creates and reuses the current legacy main window on demand."""

    def __init__(self, project_definition: ProjectDefinition) -> None:
        self._project_definition = project_definition
        self._window = None

    def has_window(self) -> bool:
        """Return whether a legacy runtime window is currently alive."""
        return self._window is not None

    def open_window(self):
        """Open or focus the current legacy runtime window."""
        if self._window is None:
            from gui.main_window import MainWindow

            self._window = MainWindow()
            self._window.selected_project_name = self._project_definition.display_name
            self._window.selected_project_config = str(self._project_definition.config_path)
            self._window.selected_project_definition = self._project_definition
            self._window.setWindowTitle(f"{WORKSPACE_TITLE_PREFIX} - {self._project_definition.display_name} (Current Runtime)")
            self._window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._window.destroyed.connect(self._on_destroyed)

        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        return self._window

    def current_window(self):
        """Return the current runtime window when it exists."""
        return self._window

    def update_config_path(self, config_path) -> None:
        """Keep the legacy runtime aligned with the latest active config file."""
        if self._window is None:
            return
        self._window.selected_project_config = str(config_path)

    def update_project_definition(self, project_definition: ProjectDefinition) -> None:
        """Keep the legacy runtime metadata aligned with the latest active project definition."""
        self._project_definition = project_definition
        if self._window is None:
            return

        if hasattr(self._window, "selected_project_name"):
            self._window.selected_project_name = project_definition.display_name
        if hasattr(self._window, "selected_project_definition"):
            self._window.selected_project_definition = project_definition
        if hasattr(self._window, "selected_project_config"):
            self._window.selected_project_config = str(project_definition.config_path)
        if hasattr(self._window, "setWindowTitle"):
            self._window.setWindowTitle(f"{WORKSPACE_TITLE_PREFIX} - {project_definition.display_name} (Current Runtime)")

    def _on_destroyed(self, *_args) -> None:
        """Reset the cached window reference when the runtime closes."""
        self._window = None
