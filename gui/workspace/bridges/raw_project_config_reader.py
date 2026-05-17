"""Reader for raw project YAML used by workspace summaries."""

from __future__ import annotations

from pathlib import Path

from myconfig.project_loader import load_project_yaml
from myconfig.project_models import ProjectDefinition


class RawProjectConfigReader:
    """Loads raw project YAML and caches the result for workspace use."""

    def __init__(self, project_definition: ProjectDefinition) -> None:
        self._project_definition = project_definition
        self._active_path = project_definition.config_path.resolve()
        self._cached_raw_config: dict | None = None

    def load(self) -> dict:
        """Return the raw YAML mapping for the selected project."""
        if self._cached_raw_config is None:
            self._cached_raw_config = load_project_yaml(self._active_path)
        return self._cached_raw_config

    def invalidate(self) -> None:
        """Clear the cached raw YAML document after a save or reload."""
        self._cached_raw_config = None

    def set_active_path(self, path: Path) -> None:
        """Replace the active project config path after a versioned save."""
        self._active_path = path.resolve()
        self.invalidate()

    def set_cached_raw_config(self, raw_config: dict) -> None:
        """Promote one in-memory config snapshot as the current active workspace config."""
        self._cached_raw_config = raw_config

    def current_path(self) -> Path:
        """Return the currently active project config path."""
        return self._active_path
