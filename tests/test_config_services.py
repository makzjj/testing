"""Unit tests for YAML repair and version-aware config save services."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from myconfig.config_editor_service import ConfigEditorService
from myconfig.config_models import ConfigDocument
from myconfig.config_save_service import ConfigSaveService
from myconfig.yaml_repair_service import YamlRepairService


class YamlRepairServiceTests(unittest.TestCase):
    """Verifies the explicit pre-parse repair/diagnostic step."""

    def test_repair_if_needed_fixes_tab_indentation_when_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n\tname: demo\n", encoding="utf-8")

            diagnostic = YamlRepairService().repair_if_needed(config_path)
            repaired_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))

            self.assertTrue(diagnostic.is_valid)
            self.assertTrue(diagnostic.was_repaired)
            self.assertEqual(repaired_data["project"]["name"], "demo")

    def test_config_editor_service_returns_clear_error_for_unrepairable_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "broken.yaml"
            config_path.write_text("project: [\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "YAML syntax error"):
                ConfigEditorService().load_current_config(config_path)


class ConfigSaveServiceTests(unittest.TestCase):
    """Verifies version-aware save planning and file output behavior."""

    def test_prepare_save_requires_new_version_when_version_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "1.0.0"}},
                source_path=Path(temp_dir) / "demo.yaml",
                project_name="demo",
                version="1.0.0",
            )

            save_plan = ConfigSaveService().prepare_save(
                document,
                current_version="1.0.0",
                requested_version=None,
                confirmed_new_version=False,
            )

            self.assertTrue(save_plan.requires_confirmation)
            self.assertIn("Enter a new config version", save_plan.warning_text)

    def test_prepare_save_rejects_existing_config_version_anywhere_in_project_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text("project:\n  name: demo\n  config_version: 1.0.0\n", encoding="utf-8")
            existing_dir = Path(temp_dir) / "archive"
            existing_dir.mkdir()
            existing_target = existing_dir / "demo_1.0.1.yaml"
            existing_target.write_text("project:\n  name: demo\n  config_version: 1.0.1\n", encoding="utf-8")

            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "1.0.1"}},
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )

            with self.assertRaisesRegex(FileExistsError, "Config version 1.0.1 already exists"):
                ConfigSaveService().prepare_save(
                    document,
                    current_version="1.0.0",
                    requested_version="1.0.1",
                    confirmed_new_version=True,
                )

    def test_prepare_save_rejects_existing_config_version_in_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text("project:\n  name: demo\n  config_version: 1.0.0\n", encoding="utf-8")
            existing_target = Path(temp_dir) / "demo_1.0.1.yaml"
            existing_target.write_text("project:\n  name: demo\n  config_version: 1.0.1\n", encoding="utf-8")

            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "1.0.1"}},
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )

            with self.assertRaisesRegex(FileExistsError, "Config version 1.0.1 already exists"):
                ConfigSaveService().prepare_save(
                    document,
                    current_version="1.0.0",
                    requested_version="1.0.1",
                    confirmed_new_version=True,
                )

    def test_prepare_save_rejects_duplicate_identity_from_unversioned_filename_using_yaml_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "working_copy.yaml"
            source_path.write_text("project:\n  name: ACCuESS\n  config_version: 0.0.0.0\n", encoding="utf-8")
            existing_target = Path(temp_dir) / "ACCuESS.yaml"
            existing_target.write_text(
                "project:\n  name: ACCuESS\n  display_name: ACCuESS\n  config_version: 0.0.0.1\n",
                encoding="utf-8",
            )

            document = ConfigDocument(
                raw_data={"project": {"name": "ACCuESS", "config_version": "0.0.0.1"}},
                source_path=source_path,
                project_name="ACCuESS",
                version="0.0.0.1",
            )

            with self.assertRaisesRegex(FileExistsError, "ACCuESS.yaml"):
                ConfigSaveService().prepare_save(
                    document,
                    current_version="0.0.0.0",
                    requested_version="0.0.0.1",
                    confirmed_new_version=True,
                )

    def test_save_document_writes_versioned_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text("project:\n  name: demo\n  config_version: 1.0.0\n", encoding="utf-8")

            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "1.0.1"}},
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )
            service = ConfigSaveService()

            save_plan = service.prepare_save(
                document,
                current_version="1.0.0",
                requested_version=None,
                confirmed_new_version=False,
            )
            save_result = service.save_document(document, save_plan)
            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))

            self.assertEqual(save_result.saved_path.name, "demo_1.0.1.yaml")
            self.assertEqual(saved_data["project"]["config_version"], "1.0.1")

    def test_save_document_preserves_blank_yaml_style_for_empty_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text("project:\n  name: demo\n  config_version: 1.0.0\n", encoding="utf-8")

            document = ConfigDocument(
                raw_data={
                    "project": {"name": "demo", "config_version": "1.0.1"},
                    "command list": None,
                    "robot arm configuration": {
                        "axes": {
                            "rs": {
                                "sw_range_max": None,
                            }
                        }
                    },
                },
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )
            service = ConfigSaveService()

            save_plan = service.prepare_save(
                document,
                current_version="1.0.0",
                requested_version=None,
                confirmed_new_version=False,
            )
            save_result = service.save_document(document, save_plan)
            saved_text = save_result.saved_path.read_text(encoding="utf-8")

            self.assertIn("command list:\n", saved_text)
            self.assertIn("sw_range_max:\n", saved_text)
            self.assertNotIn(": null", saved_text)

    def test_save_document_preserves_explicit_null_style_for_original_explicit_null_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text(
                """
project:
  name: demo
  config_version: 1.0.0
typed fields:
  explicit_null: null
  blank_value:
""".strip(),
                encoding="utf-8",
            )
            document = ConfigEditorService().load_current_config(source_path)

            save_plan = ConfigSaveService().prepare_save(
                document,
                current_version="1.0.0",
                requested_version="1.0.1",
                confirmed_new_version=True,
            )
            save_result = ConfigSaveService().save_document(document, save_plan)
            saved_text = save_result.saved_path.read_text(encoding="utf-8")

            self.assertIn("explicit_null: null", saved_text)
            self.assertIn("blank_value:\n", saved_text)

    def test_save_document_round_trips_empty_string_empty_list_and_structured_list_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_path.write_text("project:\n  name: demo\n  config_version: 1.0.0\n", encoding="utf-8")

            document = ConfigDocument(
                raw_data={
                    "project": {
                        "name": "demo",
                        "display_name": "Demo",
                        "config_version": "1.0.1",
                    },
                    "typed fields": {
                        "string_value": "alpha",
                        "empty_string": "",
                        "int_value": 7,
                        "float_value": 2.5,
                        "bool_value": True,
                        "null_value": None,
                    },
                    "command list": [
                        {"name": "GET_VERSION", "target": "mcu"},
                        "PING",
                    ],
                    "empty list section": [],
                },
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )
            service = ConfigSaveService()

            save_plan = service.prepare_save(
                document,
                current_version="1.0.0",
                requested_version=None,
                confirmed_new_version=False,
            )
            save_result = service.save_document(document, save_plan)
            saved_data = yaml.safe_load(save_result.saved_path.read_text(encoding="utf-8"))
            saved_text = save_result.saved_path.read_text(encoding="utf-8")

            self.assertEqual(saved_data["typed fields"]["string_value"], "alpha")
            self.assertEqual(saved_data["typed fields"]["empty_string"], "")
            self.assertEqual(saved_data["typed fields"]["int_value"], 7)
            self.assertEqual(saved_data["typed fields"]["float_value"], 2.5)
            self.assertTrue(saved_data["typed fields"]["bool_value"])
            self.assertIsNone(saved_data["typed fields"]["null_value"])
            self.assertEqual(saved_data["command list"][0], {"name": "GET_VERSION", "target": "mcu"})
            self.assertEqual(saved_data["command list"][1], "PING")
            self.assertEqual(saved_data["empty list section"], [])
            self.assertIn("null_value:\n", saved_text)
            self.assertIn("empty list section: []", saved_text)

    def test_prepare_save_rejects_invalid_config_version_format(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "release candidate 1"}},
                source_path=Path(temp_dir) / "demo.yaml",
                project_name="demo",
                version="release candidate 1",
            )

            with self.assertRaisesRegex(ValueError, "Config version must use digits separated by dots"):
                ConfigSaveService().prepare_save(
                    document,
                    current_version="1.0.0",
                    requested_version="release candidate 1",
                    confirmed_new_version=True,
                )

    def test_save_document_cleans_temp_file_and_preserves_existing_files_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "demo.yaml"
            source_text = "project:\n  name: demo\n  config_version: 1.0.0\n"
            source_path.write_text(source_text, encoding="utf-8")

            document = ConfigDocument(
                raw_data={"project": {"name": "demo", "config_version": "1.0.1"}},
                source_path=source_path,
                project_name="demo",
                version="1.0.1",
            )
            service = ConfigSaveService()
            save_plan = service.prepare_save(
                document,
                current_version="1.0.0",
                requested_version="1.0.1",
                confirmed_new_version=True,
            )
            target_path = save_plan.target_path
            temp_output_path = target_path.with_suffix(f"{target_path.suffix}.tmp")

            with patch("myconfig.config_save_service.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    service.save_document(document, save_plan)

            self.assertEqual(source_path.read_text(encoding="utf-8"), source_text)
            self.assertFalse(target_path.exists())
            self.assertFalse(temp_output_path.exists())


if __name__ == "__main__":
    unittest.main()
