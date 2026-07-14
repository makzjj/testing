from __future__ import annotations

import ast
from pathlib import Path
import unittest

from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController


def _legacy_text_commands() -> list[dict[str, object]]:
    source = Path("legacy_reference/firmware_integration_test.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "ALL_TEXT_COMMANDS":
                return ast.literal_eval(node.value)
    raise AssertionError("ALL_TEXT_COMMANDS not found")


class FirmwareTextCatalogTests(unittest.TestCase):
    def test_every_legacy_text_command_has_canonical_definition_and_case(self) -> None:
        legacy_commands = _legacy_text_commands()
        controller = FirmwareIntegrationController()
        definitions = controller.manual_text_command_definitions()
        cases = controller.text_fit_case_definitions()

        legacy_command_text = [str(item["cmd"]) for item in legacy_commands]
        definition_command_text = [str(definition.text_command) for definition in definitions]
        case_command_text = [
            str(next(definition for definition in definitions if definition.name == case.command_key).text_command)
            for case in cases
        ]

        self.assertEqual(len(legacy_command_text), 70)
        self.assertEqual(len(definitions), len(legacy_command_text))
        self.assertEqual(len(cases), len(legacy_command_text))
        self.assertEqual(set(definition_command_text), set(legacy_command_text))
        self.assertEqual(set(case_command_text), set(legacy_command_text))
        self.assertEqual(len(set(definition.name for definition in definitions)), len(definitions))
        self.assertEqual(len(set(case.case_id for case in cases)), len(cases))

    def test_every_definition_has_required_metadata(self) -> None:
        controller = FirmwareIntegrationController()
        for definition in controller.manual_text_command_definitions():
            self.assertEqual(definition.mode, "text")
            self.assertIsNotNone(definition.text_command)
            self.assertIsNotNone(definition.parameter_schema)
            self.assertIsNotNone(definition.expected_response)
            self.assertIsNotNone(definition.expected_response_description)
            self.assertIsNotNone(definition.execution_policy)
            self.assertIsNotNone(definition.category)
            self.assertEqual(definition.builder_name, "build_text_command_payload")
            self.assertEqual(definition.decoder_name, "decode_text_command_response")

    def test_default_selection_policy_selects_queries_only(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = {definition.name: definition for definition in controller.manual_text_command_definitions()}
        for case in controller.text_fit_case_definitions():
            command = str(definitions[case.command_key].text_command)
            if command.endswith("?"):
                self.assertTrue(case.selected_by_default, command)
            else:
                self.assertFalse(case.selected_by_default, command)

    def test_execution_policy_classes_are_present(self) -> None:
        controller = FirmwareIntegrationController()
        policies = {str(definition.execution_policy) for definition in controller.manual_text_command_definitions()}

        self.assertIn("QUERY_RESPONSE", policies)
        self.assertIn("SET_RESPONSE", policies)
        self.assertIn("ACTION_ACK", policies)
        self.assertIn("POWER_CONTROL", policies)
        self.assertIn("PERSISTENT_CHANGE", policies)
        self.assertIn("LOGGING_STREAM", policies)
        self.assertIn("MANUAL_VERIFICATION", policies)
        self.assertIn("UNSUPPORTED", policies)
        self.assertIn("REBOOT", policies)

    def test_validation_rejects_known_invalid_values_without_sending(self) -> None:
        class _Backend:
            def __init__(self) -> None:
                self.writes: list[bytearray] = []

            def is_connected(self) -> bool:
                return True

            def write(self, payload: bytearray) -> None:
                self.writes.append(payload)

        class _Runtime:
            def __init__(self) -> None:
                self.backend_client = _Backend()

        class _Bridge:
            def __init__(self) -> None:
                self.runtime = _Runtime()

            def get_runtime_connection_state(self, *, create_if_missing: bool = False):
                _ = create_if_missing
                return True, True

            def get_runtime_window(self, *, create_if_missing: bool = False):
                _ = create_if_missing
                return self.runtime

            def send_firmware_text_command(self, payload: bytearray) -> bytearray:
                self.runtime.backend_client.write(payload)
                return payload

        bridge = _Bridge()
        controller = FirmwareIntegrationController(bridge)

        self.assertFalse(controller.send_manual_text_command("Robot Power Set", "2"))
        self.assertFalse(controller.send_manual_text_command("ONbtndc=", "101"))
        self.assertFalse(controller.send_manual_text_command("mfgdate=", "2026-07-13"))
        self.assertEqual(bridge.runtime.backend_client.writes, [])

    def test_unsupported_commands_are_visible_with_reason(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = {definition.text_command: definition for definition in controller.manual_text_command_definitions()}

        for command in ("factorydef!", "reset!", "commandshutdown="):
            self.assertIn(command, definitions)
            self.assertTrue(definitions[command].unsupported_reason)


if __name__ == "__main__":
    unittest.main()
