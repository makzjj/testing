from __future__ import annotations

import inspect
import unittest
from collections import Counter

from data import binary_cmd_builders, binary_cmd_parser
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from tests.helpers.firmware_catalog_fixtures import load_legacy_binary_catalog


class FirmwareBinaryCatalogTests(unittest.TestCase):
    def test_every_legacy_binary_entry_is_represented_with_metadata(self) -> None:
        legacy_catalog = load_legacy_binary_catalog()
        legacy = list(legacy_catalog["entries"])
        controller = FirmwareIntegrationController()
        definitions = controller.manual_binary_command_definitions()
        cases = controller.binary_fit_case_definitions()

        self.assertEqual(len(legacy), 80)
        self.assertEqual(len(definitions), 83)
        self.assertEqual(len(cases), 83)
        self.assertEqual(len({definition.name for definition in definitions}), len(definitions))
        self.assertEqual(len({case.case_id for case in cases}), len(cases))

        legacy_signatures = Counter(
            (int(row["opcode"]) & 0xFF, str(row.get("parameter_type") or ""), str(row.get("name") or ""))
            for row in legacy
        )
        definition_signatures = Counter(
            (
                int(definition.opcode or 0) & 0xFF,
                str((definition.validation or {}).get("params_type") or ""),
                str((definition.validation or {}).get("legacy_name") or ""),
            )
            for definition in definitions
            if (
                int(definition.opcode or 0) & 0xFF,
                str((definition.validation or {}).get("params_type") or ""),
                str((definition.validation or {}).get("legacy_name") or ""),
            )
            in legacy_signatures
        )
        self.assertEqual(definition_signatures, legacy_signatures)

        definition_by_signature = {
            (
                int(definition.opcode or 0) & 0xFF,
                str((definition.validation or {}).get("params_type") or ""),
                str((definition.validation or {}).get("legacy_name") or ""),
            ): definition
            for definition in definitions
        }
        for row in legacy:
            signature = (
                int(row["opcode"]) & 0xFF,
                str(row.get("parameter_type") or ""),
                str(row.get("name") or ""),
            )
            definition = definition_by_signature[signature]
            with self.subTest(signature=signature):
                self.assertEqual(definition.command_form, row["form"])
                self.assertEqual(definition.expected_response_description, row["expected_response"])
                self.assertEqual(definition.manual_prompt, row["manual_verification_prompt"])

        for definition in definitions:
            self.assertEqual(definition.mode, "binary")
            self.assertIsNotNone(definition.opcode)
            self.assertEqual(definition.decoder_name, "decode_command")
            self.assertIsNotNone(definition.builder_name)
            self.assertIsNotNone(definition.parameter_schema)
            self.assertIsNotNone(definition.execution_policy)
            self.assertIsNotNone(definition.category)
            self.assertIsNotNone(definition.command_form)
            self.assertIsNotNone(definition.support_status)

    def test_query_set_duplicate_opcodes_are_distinct(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = controller.manual_binary_command_definitions()
        by_opcode = {}
        for definition in definitions:
            by_opcode.setdefault(definition.opcode, []).append(definition)

        for opcode in (0x86, 0x96, 0xCD, 0xEA):
            variants = by_opcode[opcode]
            forms = {definition.command_form for definition in variants}
            names = {definition.name for definition in variants}
            self.assertIn("query", forms)
            self.assertIn("set", forms)
            self.assertEqual(len(names), len(variants))

    def test_extra_query_display_names_use_bcmd_prefix_without_changing_stable_keys(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = {definition.name: definition for definition in controller.manual_binary_command_definitions()}

        self.assertEqual(definitions["NODECONFIG Query"].display_name, "bcmd_NODECONFIG (Query Node Configuration)")
        self.assertEqual(definitions["INTERRUPT Query"].display_name, "bcmd_INTERRUPT (Query Interrupt State)")
        self.assertEqual(definitions["MOTOR_I Query"].display_name, "bcmd_MOTOR_I (Query Motor Current)")
        self.assertEqual(definitions["NODECONFIG Query"].builder_name, "build_nodeconfig_query_payload")
        self.assertEqual(definitions["INTERRUPT Query"].builder_name, "build_interrupt_query_payload")
        self.assertEqual(definitions["MOTOR_I Query"].builder_name, "build_motor_current_query_payload")
        self.assertEqual(definitions["NODECONFIG Query"].opcode, 0xC4)
        self.assertEqual(definitions["INTERRUPT Query"].opcode, 0xD8)
        self.assertEqual(definitions["MOTOR_I Query"].opcode, 0xCF)

    def test_binary_catalog_uses_numeric_opcode_then_form_ordering(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = controller.manual_binary_command_definitions()

        opcode_form_pairs = [(int(definition.opcode or 0), str(definition.command_form or "")) for definition in definitions]
        self.assertEqual(opcode_form_pairs[0], (0x81, "set"))
        self.assertEqual(opcode_form_pairs[1], (0x82, "query"))
        self.assertEqual(opcode_form_pairs[2], (0x83, "query"))
        self.assertEqual(opcode_form_pairs, sorted(opcode_form_pairs, key=lambda item: (item[0], {"query": 0, "set": 1}.get(item[1], 2))))

        by_name = {definition.name: index for index, definition in enumerate(definitions)}
        self.assertLess(by_name["NODEIDref - Get ID Reference"], by_name["NODEIDref - Set ID Reference"])
        self.assertLess(by_name["EXTINT - Get EXT Interrupt"], by_name["EXTINT - Set EXT Interrupt"])
        self.assertLess(by_name["NODETYPE - Get node type"], by_name["NODETYPE - Set node type"])
        self.assertLess(by_name["POSITION - Get current position"], by_name["POSITION - Set current position"])
        self.assertEqual(definitions[by_name["NODECONFIG Query"]].opcode, 0xC4)
        self.assertEqual(definitions[by_name["MOTOR_I Query"]].opcode, 0xCF)
        self.assertEqual(definitions[by_name["INTERRUPT Query"]].opcode, 0xD8)

    def test_binary_builders_remain_explicit_for_executable_commands(self) -> None:
        self.assertFalse(hasattr(binary_cmd_builders, "build_binary_command_payload"))
        controller = FirmwareIntegrationController()
        definitions = {definition.name: definition for definition in controller.manual_binary_command_definitions()}

        self.assertEqual(controller._build_binary_payload(definitions["GETVER"], None), [0xC8, 0x3F])
        self.assertEqual(controller._build_binary_payload(definitions["GETPOS"], None), [0x82])
        self.assertEqual(controller._build_binary_payload(definitions["VEL Write"], 30), [0x84, 0x00, 0x1E])

    def test_unknown_or_ambiguous_responses_do_not_receive_generic_semantics(self) -> None:
        self.assertEqual(binary_cmd_parser.decode_command(0x86, [0x3A, 0x03]), (None, None))
        self.assertEqual(binary_cmd_parser.decode_command(0x9A, [0x3A, 0x00, 0x01]), (None, None))
        self.assertEqual(binary_cmd_parser.decode_command(0xD4, [0x3A, 0x00, 0x00]), (None, None))
        self.assertEqual(binary_cmd_parser.decode_command(0xEA, [0x3A, 0x00, 0x00, 0x00, 0x10]), (None, None))
        self.assertEqual(binary_cmd_parser.decode_command(0xD3, [0x3A, 0x00, 0x05]), ("log_motor_current_rate", 5))
        self.assertEqual(binary_cmd_parser.decode_command(0xE4, [0x3A, 0x00, 0x05]), ("position_log_rate", 5))

    def test_invalid_binary_values_are_rejected_before_send(self) -> None:
        controller = FirmwareIntegrationController()
        definitions = {definition.name: definition for definition in controller.manual_binary_command_definitions()}

        nodeid_set = next(
            definition
            for definition in definitions.values()
            if definition.opcode == 0x86 and definition.command_form == "set"
        )
        with self.assertRaises(ValueError):
            controller._build_binary_payload(nodeid_set, "01 02")

    def test_no_binary_catalog_or_protocol_logic_is_added_to_ui(self) -> None:
        import gui.workspace.dialogs.binary_fit_config_dialog as config_module
        import gui.workspace.dialogs.manual_binary_command_dialog as manual_module

        for source in (inspect.getsource(config_module), inspect.getsource(manual_module)):
            self.assertNotIn("ALL_BINARY_COMMANDS", source)
            self.assertNotIn("binary_cmd_builders", source)
            self.assertNotIn("binary_cmd_parser", source)
            self.assertNotIn("decode_command", source)


if __name__ == "__main__":
    unittest.main()
