from __future__ import annotations

import dataclasses
import inspect
import os
import unittest

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QApplication

import gui.workspace.controllers.firmware_integration_controller as firmware_controller_module
import gui.workspace.dialogs.manual_binary_command_dialog as manual_binary_dialog_module
import gui.workspace.dialogs.manual_text_command_dialog as manual_text_dialog_module
import gui.workspace.pages.firmware_page as firmware_page_module
from gui.workspace.controllers.firmware_integration_controller import FirmwareIntegrationController
from gui.workspace.models import FirmwareCommandDefinition, FirmwareTestCase, FirmwareTestResult


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FirmwareWorkflowFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_one_public_firmware_controller_remains(self) -> None:
        class_names = {
            name
            for name, value in vars(firmware_controller_module).items()
            if inspect.isclass(value) and value.__module__ == firmware_controller_module.__name__
        }

        self.assertIn("FirmwareIntegrationController", class_names)
        self.assertNotIn("ManualBinaryController", class_names)
        self.assertNotIn("ManualTextController", class_names)
        self.assertNotIn("BinaryFITController", class_names)
        self.assertNotIn("TextFITController", class_names)
        self.assertNotIn("ReportController", class_names)

    def test_private_workflow_helpers_remain_private_and_data_local(self) -> None:
        binary_helper = firmware_controller_module._ManualBinaryWorkflow()
        text_helper = firmware_controller_module._ManualTextWorkflow()

        self.assertTrue(binary_helper.__class__.__name__.startswith("_"))
        self.assertTrue(text_helper.__class__.__name__.startswith("_"))
        self.assertFalse(hasattr(binary_helper, "_bridge"))
        self.assertFalse(hasattr(text_helper, "_bridge"))
        self.assertFalse(hasattr(binary_helper, "_runtime_window"))
        self.assertFalse(hasattr(text_helper, "_runtime_window"))
        self.assertFalse(hasattr(binary_helper, "_active_operation"))
        self.assertFalse(hasattr(text_helper, "_active_operation"))

        for helper in (binary_helper, text_helper):
            source = inspect.getsource(helper.__class__)
            self.assertNotIn("backend_client", source)
            self.assertNotIn("packet_received", source)
            self.assertNotIn("QWidget", source)

    def test_page_and_dialogs_import_only_public_controller(self) -> None:
        for module in (firmware_page_module, manual_binary_dialog_module, manual_text_dialog_module):
            source = inspect.getsource(module)
            self.assertIn("FirmwareIntegrationController", source)
            self.assertNotIn("_ManualBinaryWorkflow", source)
            self.assertNotIn("_ManualTextWorkflow", source)

    def test_command_definition_test_case_and_test_result_are_data_only_and_distinct(self) -> None:
        command_definition = FirmwareCommandDefinition(
            name="GETVER",
            mode="binary",
            opcode=0xC8,
            expected_response="firmware",
            timeout_ms=1500,
            builder_name="build_getver_query_payload",
            decoder_name="decode_command",
        )
        test_case = FirmwareTestCase(
            case_id="binary-getver",
            name="GETVER responds",
            mode="binary",
            command_key="GETVER",
            expected_response="firmware",
            timeout_ms=1500,
            selected_by_default=True,
        )
        test_result = FirmwareTestResult(
            case_id="binary-getver",
            status="PASS",
            expected="firmware",
            actual="firmware: 3A123001",
            tx_bytes=b"\xC8\x3F",
            rx_bytes=b"\xC8\x3A\x12\x30\x01",
            latency_ms=25.0,
            message="ok",
        )

        for model in (command_definition, test_case, test_result):
            self.assertTrue(dataclasses.is_dataclass(model))
            for field in dataclasses.fields(model):
                value = getattr(model, field.name)
                self.assertNotIsInstance(value, QObject)
                self.assertFalse(hasattr(value, "packet_received"))
                self.assertFalse(hasattr(value, "send_command_bytes"))

        self.assertEqual(command_definition.name, "GETVER")
        self.assertEqual(test_case.command_key, "GETVER")
        self.assertEqual(test_result.case_id, "binary-getver")
        self.assertNotIn("selected_by_default", {field.name for field in dataclasses.fields(command_definition)})
        self.assertIn("selected_by_default", {field.name for field in dataclasses.fields(test_case)})
        self.assertIn("status", {field.name for field in dataclasses.fields(test_result)})

    def test_no_legacy_full_tables_or_automated_execution_are_introduced(self) -> None:
        controller_source = inspect.getsource(firmware_controller_module)
        self.assertNotIn("ALL_BINARY_COMMANDS", controller_source)
        self.assertNotIn("ALL_TEXT_COMMANDS", controller_source)
        self.assertNotIn("BINARY_CMD_EXPECTED_RESP", controller_source)
        self.assertNotIn("TEXT_CMD_EXPECTED_FORMATS", controller_source)
        self.assertNotIn("TestExecutor", controller_source)
        self.assertNotIn("WorkflowManager", controller_source)

        controller = FirmwareIntegrationController()
        self.assertIn("not implemented", controller.start_binary_fit())
        self.assertIn("not implemented", controller.start_text_fit())
        self.assertIn("not implemented", controller.open_reports())
        self.assertFalse(controller.has_pending_firmware_request())


if __name__ == "__main__":
    unittest.main()
