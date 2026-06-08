"""Launcher for the existing legacy runtime window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt

from myconfig.project_models import ProjectDefinition
from ..constants import WORKSPACE_TITLE_PREFIX

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class LegacyRuntimeLauncher:
    """Creates and reuses one shared runtime widget embedded in the workspace."""

    def __init__(self, project_definition: ProjectDefinition) -> None:
        self._project_definition = project_definition
        self._main_window = None  # The actual MainWindow instance
        self._central_widget = None  # The extracted central widget
        self._window = None  # Backward-compatible alias used by older tests

    def has_window(self) -> bool:
        """Return whether a shared runtime widget instance currently exists."""
        return self._main_window is not None or self._window is not None

    def open_window(self) -> "QWidget":
        """Create or return the shared runtime widget without opening a new top-level window."""
        return self.ensure_runtime_widget()

    def ensure_runtime_widget(self, parent: "QWidget | None" = None) -> "QWidget":
        """Create and attach the shared runtime widget to the workspace when needed.
        
        This method creates a MainWindow and returns its central widget for embedding
        in the workspace. The MainWindow is kept alive as a reference to maintain
        the runtime state and timers.
        """
        if self._main_window is None:
            from gui.main_window import MainWindow

            # Create MainWindow - it will initialize all runtime systems
            main_window = MainWindow()
            main_window.destroyed.connect(self._on_destroyed)
            main_window.selected_project_name = self._project_definition.display_name
            main_window.selected_project_config = str(self._project_definition.config_path)
            main_window.selected_project_definition = self._project_definition
            
            # Hide the MainWindow so it doesn't appear as a separate window
            # We'll use its central widget in the workspace instead
            main_window.hide()
            
            # Get the central widget which contains all the Runtime UI
            self._central_widget = main_window.centralWidget()
            if self._central_widget is None:
                raise RuntimeError("MainWindow failed to create a central widget")
            self._main_window = main_window
            self._window = main_window

        # Return the central widget for embedding in the RuntimePage layout
        return self._central_widget

    def current_window(self):
        """Return the current runtime window when it exists."""
        return self._main_window or self._window

    def update_config_path(self, config_path) -> None:
        """Keep the legacy runtime aligned with the latest active config file."""
        if self._main_window is None:
            return
        self._main_window.selected_project_config = str(config_path)

    def update_project_definition(self, project_definition: ProjectDefinition) -> None:
        """Keep the legacy runtime metadata aligned with the latest active project definition."""
        self._project_definition = project_definition
        if self._main_window is None:
            return

        if hasattr(self._main_window, "selected_project_name"):
            self._main_window.selected_project_name = project_definition.display_name
        if hasattr(self._main_window, "selected_project_definition"):
            self._main_window.selected_project_definition = project_definition
        if hasattr(self._main_window, "selected_project_config"):
            self._main_window.selected_project_config = str(project_definition.config_path)

    def _on_destroyed(self, *_args) -> None:
        """Reset the cached window reference when the runtime closes."""
        self._main_window = None
        self._central_widget = None
        self._window = None
