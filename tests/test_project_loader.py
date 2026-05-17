"""Unit tests for project discovery, YAML parsing, and validation logic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from myconfig import project_loader


class ProjectLoaderTests(unittest.TestCase):
    """Verifies Phase 1 project-loading behavior."""

    def test_load_available_projects_returns_valid_project_from_yaml_metadata(self) -> None:
        # 1. Arrange a temporary project config directory
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(
                config_dir / "access.yaml",
                """
project:
  name: access_internal
  display_name: ACCuESS
system:
  axes: 5
features:
  firmware_tools: true
ui:
  workspace: main_window
""".strip(),
            )

            # 2. Load project configs from the temporary directory
            load_result = self._load_projects_from_dir(config_dir)

            # 3. Verify the valid project definition
            self.assertEqual(len(load_result.valid_projects), 1)
            self.assertEqual(len(load_result.invalid_projects), 0)
            project = load_result.valid_projects[0]
            self.assertEqual(project.name, "access_internal")
            self.assertEqual(project.display_name, "ACCuESS")
            self.assertEqual(project.system_axes, 5)
            self.assertTrue(project.features.firmware_tools)

    def test_build_project_definition_falls_back_to_project_name_for_display_name(self) -> None:
        # 1. Arrange raw YAML data without display_name
        raw_config = {
            "project": {"name": "ml20"},
            "system": {"axes": 10},
        }

        # 2. Build the typed project definition
        project = project_loader.build_project_definition(raw_config, Path("ml20.yaml"))

        # 3. Verify display name fallback
        self.assertEqual(project.name, "ml20")
        self.assertEqual(project.display_name, "ml20")
        self.assertEqual(project.system_axes, 10)

    def test_build_project_definition_supports_accuess_schema_metadata(self) -> None:
        raw_config = {
            "project": {
                "name": "ACCuESS",
                "display_name": "ACCuESS",
                "config_version": "0.0.0.1",
            },
            "robot system configuration": {
                "axes number": 5,
            },
            "features": {
                "firmware_tools": True,
                "mechanical_tools": True,
            },
            "ui": {
                "workspace": "main_window",
            },
        }

        project = project_loader.build_project_definition(raw_config, Path("ACCuESS.yaml"))

        self.assertEqual(project.name, "ACCuESS")
        self.assertEqual(project.display_name, "ACCuESS")
        self.assertEqual(project.config_version, "0.0.0.1")
        self.assertEqual(project.system_axes, 5)
        self.assertTrue(project.features.firmware_tools)
        self.assertTrue(project.features.mechanical_tools)

    def test_validate_project_yaml_accepts_updated_accuess_schema(self) -> None:
        raw_config = {
            "project": {
                "name": "ACCuESS",
                "display_name": "ACCuESS",
                "config_version": "0.0.0.1",
            },
            "features": {
                "firmware_tools": True,
            },
            "ui": {
                "workspace": "main_window",
            },
            "robot system configuration": {
                "axes number": 5,
                "mcu": True,
            },
            "communication configuration": None,
            "serial_port": {
                "name": "COM11",
                "baudrate": 115200,
            },
            "mcu configuration": {
                "firmware version": "0.0.1.6",
            },
            "robot arm configuration": {
                "axes": {
                    "ya": {
                        "node_id": 3,
                    }
                }
            },
        }

        issues = project_loader.validate_project_yaml(raw_config, Path("ACCuESS.yaml"))

        self.assertEqual(issues, [])

    def test_validate_project_yaml_flags_non_integer_axis_count_in_new_schema(self) -> None:
        raw_config = {
            "project": {
                "name": "ACCuESS",
            },
            "robot system configuration": {
                "axes number": "five",
            },
        }

        issues = project_loader.validate_project_yaml(raw_config, Path("ACCuESS.yaml"))

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].field, "robot system configuration.axes number")

    def test_load_available_projects_records_invalid_yaml_without_crashing(self) -> None:
        # 1. Arrange a temporary config directory with malformed YAML
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(config_dir / "broken.yaml", "project: [")

            # 2. Load project configs from the temporary directory
            load_result = self._load_projects_from_dir(config_dir)

            # 3. Verify the invalid config is reported cleanly
            self.assertEqual(len(load_result.valid_projects), 0)
            self.assertEqual(len(load_result.invalid_projects), 1)
            self.assertIn("Failed to parse YAML", load_result.invalid_projects[0].message)

    def test_discover_project_files_ignores_non_yaml_files(self) -> None:
        # 1. Arrange a temporary directory with mixed file types
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(config_dir / "valid.yaml", "project:\n  name: demo\n")
            self._write_file(config_dir / "notes.txt", "ignore me")

            # 2. Discover project files
            with patch.object(project_loader, "PROJECT_CONFIG_DIR", config_dir):
                project_files = project_loader.discover_project_files()

            # 3. Verify only YAML files are returned
            self.assertEqual(len(project_files), 1)
            self.assertEqual(project_files[0].name, "valid.yaml")

    def test_load_available_projects_allows_extended_sections_for_future_project_growth(self) -> None:
        # 1. Arrange a YAML file with extra sections inspired by a legacy XML config
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(
                config_dir / "access.yaml",
                """
project:
  name: ACCuESS
  display_name: ACCuESS
system:
  axes: 5
features:
  firmware_tools: true
  mechanical_tools: true
ui:
  workspace: main_window
mcu:
  serial_port:
    name: COM11
    baudrate: 115200
robot:
  axes:
    ya:
      node_id: 3
geometry:
  ya_min_y: 15.3
calibration:
  origin_y: -5.0
""".strip(),
            )

            # 2. Load and validate the config
            load_result = self._load_projects_from_dir(config_dir)

            # 3. Verify the loader accepts the extended config while still building the minimal model
            self.assertEqual(len(load_result.valid_projects), 1)
            self.assertEqual(len(load_result.invalid_projects), 0)
            self.assertEqual(load_result.valid_projects[0].display_name, "ACCuESS")

    def test_load_available_projects_disambiguates_duplicate_display_names_with_config_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(
                config_dir / "access_v1.yaml",
                """
project:
  name: ACCuESS
  display_name: ACCuESS
  config_version: 0.0.0.1
""".strip(),
            )
            self._write_file(
                config_dir / "access_v2.yaml",
                """
project:
  name: ACCuESS
  display_name: ACCuESS
  config_version: 0.0.0.2
""".strip(),
            )

            load_result = self._load_projects_from_dir(config_dir)
            display_names = [project.display_name for project in load_result.valid_projects]

            self.assertEqual(display_names, ["ACCuESS (0.0.0.1)", "ACCuESS (0.0.0.2)"])

    def test_load_available_projects_allows_malformed_optional_sections_for_graceful_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            self._write_file(
                config_dir / "weird.yaml",
                """
project:
  name: weird
  display_name: Weird
features: bad
ui: 123
serial_port: COM11
robot arm configuration: unexpected
""".strip(),
            )

            load_result = self._load_projects_from_dir(config_dir)

            self.assertEqual(len(load_result.valid_projects), 1)
            self.assertEqual(len(load_result.invalid_projects), 0)
            self.assertEqual(load_result.valid_projects[0].display_name, "Weird")

    def test_real_repo_project_yaml_files_still_load_and_validate(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        for file_name in ("ACCuESS.yaml", "ML2.0.yaml"):
            config_path = repo_root / "project_configs" / file_name
            raw_config = project_loader.load_project_yaml(config_path)
            issues = project_loader.validate_project_yaml(raw_config, config_path)
            project = project_loader.build_project_definition(raw_config, config_path)

            self.assertEqual(issues, [], msg=file_name)
            self.assertTrue(project.name)
            self.assertTrue(project.display_name)

    def _write_file(self, path: Path, content: str) -> None:
        """Write one temporary test file with UTF-8 encoding."""
        path.write_text(content, encoding="utf-8")

    def _load_projects_from_dir(self, config_dir: Path):
        """Load projects while temporarily redirecting the config directory."""
        with patch.object(project_loader, "PROJECT_CONFIG_DIR", config_dir):
            return project_loader.load_available_projects()


if __name__ == "__main__":
    unittest.main()
