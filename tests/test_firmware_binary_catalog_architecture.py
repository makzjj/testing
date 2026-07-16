from __future__ import annotations

import inspect
import unittest

import data.binary_cmd_builders as binary_builders
import data.binary_cmd_parser as binary_parser
import gui.workspace.controllers.firmware_integration_controller as firmware_controller_module
import gui.workspace.dialogs.binary_fit_config_dialog as binary_fit_config_dialog_module
import gui.workspace.dialogs.manual_binary_command_dialog as manual_binary_dialog_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from tests.helpers.firmware_catalog_fixtures import load_legacy_binary_catalog


class FirmwareBinaryCatalogArchitectureTests(unittest.TestCase):
    def test_catalog_count_and_extra_definitions_are_explicitly_justified(self) -> None:
        legacy_catalog = load_legacy_binary_catalog()
        legacy = list(legacy_catalog["entries"])
        controller = FirmwareIntegrationController()
        definitions = controller.manual_binary_command_definitions()
        cases = controller.binary_fit_case_definitions()

        legacy_signatures = {
            (int(row["opcode"]) & 0xFF, str(row.get("parameter_type") or ""), str(row.get("name") or ""))
            for row in legacy
        }
        extra = [
            definition
            for definition in definitions
            if (
                int(definition.opcode or 0) & 0xFF,
                str((definition.validation or {}).get("params_type") or ""),
                str((definition.validation or {}).get("legacy_name") or ""),
            )
            not in legacy_signatures
        ]

        self.assertEqual(len(legacy), 80)
        self.assertEqual(len(definitions), 83)
        self.assertEqual(len(cases), 83)
        self.assertEqual(
            sorted(
                (definition.name, definition.display_name, definition.builder_name, definition.expected_response)
                for definition in extra
            ),
            sorted(
                [
                    ("NODECONFIG Query", "bcmd_NODECONFIG (Query Node Configuration)", "build_nodeconfig_query_payload", "nodeconfig"),
                    ("INTERRUPT Query", "bcmd_INTERRUPT (Query Interrupt State)", "build_interrupt_query_payload", "interrupt"),
                    ("MOTOR_I Query", "bcmd_MOTOR_I (Query Motor Current)", "build_motor_current_query_payload", "motor_current_mA"),
                ]
            ),
        )
        self.assertEqual(len({definition.name for definition in definitions}), len(definitions))
        self.assertEqual(len({case.case_id for case in cases}), len(cases))

    def test_executable_commands_use_explicit_builders_only(self) -> None:
        self.assertFalse(hasattr(binary_builders, "build_binary_command_payload"))
        controller = FirmwareIntegrationController()
        definitions = controller.manual_binary_command_definitions()

        supported = [definition for definition in definitions if definition.support_status == "SUPPORTED"]
        self.assertTrue(supported)
        for definition in supported:
            with self.subTest(command=definition.name):
                self.assertNotEqual(definition.builder_name, "unsupported")
                self.assertTrue(hasattr(binary_builders, str(definition.builder_name)))
                if definition.execution_policy != "NO_RESPONSE":
                    self.assertNotEqual(definition.expected_response, None)

        non_sending = [definition for definition in definitions if definition.execution_capability == "CONTRACT_UNKNOWN"]
        for definition in non_sending:
            self.assertEqual(definition.builder_name, "unsupported")
            self.assertEqual(definition.support_status, "UNSUPPORTED")

    def test_parser_has_no_generic_legacy_opcode_success_fallback(self) -> None:
        parser_source = inspect.getsource(binary_parser)
        self.assertNotIn("_GENERIC_BINARY_RESPONSE_KINDS", parser_source)
        self.assertEqual(binary_parser.decode_command(0x86, [0x3A, 0x03]), (None, None))
        self.assertEqual(binary_parser.decode_command(0x9A, [0x3A, 0x00, 0x01]), (None, None))
        self.assertEqual(binary_parser.decode_command(0xEA, [0x3A, 0x00, 0x00, 0x00, 0x01]), (None, None))
        self.assertEqual(binary_parser.decode_command(0xD3, [0x3A, 0x00, 0x05]), ("log_motor_current_rate", 5))

    def test_query_set_duplicate_opcodes_remain_distinct_and_executable(self) -> None:
        controller = FirmwareIntegrationController()
        for opcode in (0x86, 0x96, 0xCD, 0xEA):
            variants = [definition for definition in controller.manual_binary_command_definitions() if definition.opcode == opcode]
            forms = {definition.command_form for definition in variants}
            self.assertIn("query", forms)
            self.assertIn("set", forms)
            self.assertEqual(len({definition.name for definition in variants}), len(variants))
            for definition in variants:
                self.assertNotEqual(definition.builder_name, "unsupported")
                self.assertIn(definition.execution_capability, {"RESPONSE_MATCH", "RESPONSE_DECODE"})

    def test_ui_and_controller_do_not_assemble_packets_locally(self) -> None:
        for source in (
            inspect.getsource(binary_fit_config_dialog_module),
            inspect.getsource(manual_binary_dialog_module),
        ):
            self.assertNotIn("binary_cmd_builders", source)
            self.assertNotIn("decode_command", source)
            self.assertNotIn("bytes([", source)

        controller_source = inspect.getsource(firmware_controller_module.FirmwareIntegrationController)
        self.assertNotIn("build_binary_command_payload", controller_source)
        self.assertNotIn("_GENERIC_BINARY_RESPONSE_KINDS", controller_source)


if __name__ == "__main__":
    unittest.main()
