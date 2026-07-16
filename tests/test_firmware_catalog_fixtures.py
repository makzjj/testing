from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.helpers import firmware_catalog_fixtures as fixture_loader


class FirmwareCatalogFixturesTests(unittest.TestCase):
    def test_binary_fixture_exists_and_has_expected_shape(self) -> None:
        self.assertTrue(fixture_loader.LEGACY_BINARY_CATALOG_PATH.exists())
        catalog = fixture_loader.load_legacy_binary_catalog()
        entries = list(catalog["entries"])

        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["mode"], "binary")
        self.assertEqual(len(entries), 80)
        self.assertEqual(len({entry["legacy_index"] for entry in entries}), 80)
        self.assertEqual(
            len(
                {
                    (entry["name"], entry["opcode"], entry["form"], entry["parameter_type"])
                    for entry in entries
                }
            ),
            80,
        )

        for entry in entries:
            with self.subTest(entry=entry["legacy_index"]):
                self.assertIsInstance(entry["name"], str)
                self.assertTrue(entry["name"])
                self.assertIsInstance(entry["opcode"], int)
                self.assertGreaterEqual(entry["opcode"], 0)
                self.assertLessEqual(entry["opcode"], 0xFF)
                self.assertIn(entry["form"], {"query", "set", "action", "raw"})
                self.assertIsInstance(entry["parameter_type"], str)
                self.assertIsInstance(entry["expected_response"], str)

    def test_text_fixture_exists_and_has_expected_shape(self) -> None:
        self.assertTrue(fixture_loader.LEGACY_TEXT_CATALOG_PATH.exists())
        catalog = fixture_loader.load_legacy_text_catalog()
        entries = list(catalog["entries"])

        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["mode"], "text")
        self.assertEqual(len(entries), 70)
        self.assertEqual(len({entry["legacy_index"] for entry in entries}), 70)
        self.assertEqual(len({(entry["command"], entry["type"]) for entry in entries}), 70)

        for entry in entries:
            with self.subTest(entry=entry["legacy_index"]):
                self.assertIsInstance(entry["command"], str)
                self.assertTrue(entry["command"])
                self.assertIn(entry["type"], {"query", "set", "action"})
                self.assertIsInstance(entry["expected_prefix"], str)
                self.assertTrue(entry["expected_prefix"])
                self.assertIsInstance(entry["expected_response"], str)
                self.assertTrue(entry["expected_response"])

    def test_fixture_json_is_data_only_and_non_executable(self) -> None:
        for path in (
            fixture_loader.LEGACY_BINARY_CATALOG_PATH,
            fixture_loader.LEGACY_TEXT_CATALOG_PATH,
        ):
            with self.subTest(path=path.name):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("entries", payload)
                raw = path.read_text(encoding="utf-8")
                self.assertNotIn("def ", raw)
                self.assertNotIn("class ", raw)
                self.assertNotIn("import ", raw)

    def test_fixture_loader_is_test_only_and_production_code_does_not_import_it(self) -> None:
        controller_source = Path(
            "gui/workspace/controllers/firmware_integration_controller.py"
        ).read_text(encoding="utf-8")
        model_source = Path(
            "gui/workspace/models/firmware_command_definition.py"
        ).read_text(encoding="utf-8")
        runtime_sources = (controller_source, model_source)

        for source in runtime_sources:
            self.assertNotIn("tests.helpers.firmware_catalog_fixtures", source)
            self.assertNotIn("legacy_binary_catalog.json", source)
            self.assertNotIn("legacy_text_catalog.json", source)
            self.assertNotIn("tests/fixtures/firmware_catalogs", source)


if __name__ == "__main__":
    unittest.main()
