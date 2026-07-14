"""Firmware page implementation."""

from __future__ import annotations

from ..bridges import WorkspaceRuntimeBridge
from ..controllers.firmware_integration_controller import FirmwareIntegrationController
from ..dialogs import (
    BinaryFitConfigDialog,
    BinaryFitReportDialog,
    FirmwareReportExportDialog,
    ManualBinaryCommandDialog,
    ManualTextCommandDialog,
    TextFitConfigDialog,
    TextFitReportDialog,
)
from ..sections.firmware import (
    CommandDebugSection,
    FrameLossSection,
    FirmwareIntegrationSection,
    MotionCommandSection,
    SensorSnapshotSection,
    UartProtocolSection,
)
from .base_page import BaseWorkspacePage


class FirmwarePage(BaseWorkspacePage):
    """Focused firmware workspace page."""

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Firmware", "Command, protocol, and sensor tools.")
        self.fit_controller = FirmwareIntegrationController(bridge)
        self._binary_fit_config_dialog: BinaryFitConfigDialog | None = None
        self._binary_fit_report_dialog: BinaryFitReportDialog | None = None
        self._text_fit_config_dialog: TextFitConfigDialog | None = None
        self._text_fit_report_dialog: TextFitReportDialog | None = None
        self._report_export_dialog: FirmwareReportExportDialog | None = None
        self._manual_binary_dialog: ManualBinaryCommandDialog | None = None
        self._manual_text_dialog: ManualTextCommandDialog | None = None
        self.integration_section = FirmwareIntegrationSection(
            self.fit_controller,
            open_manual_binary_dialog=self._open_manual_binary_dialog,
            open_manual_text_dialog=self._open_manual_text_dialog,
            open_binary_fit_dialog=self._open_binary_fit_dialog,
            open_text_fit_dialog=self._open_text_fit_dialog,
            open_reports_dialog=self._open_reports_dialog,
        )
        self.command_section = CommandDebugSection(bridge)
        self.protocol_section = UartProtocolSection(bridge)
        self.frame_loss_section = FrameLossSection(bridge)
        self.motion_section = MotionCommandSection(bridge)
        self.sensor_section = SensorSnapshotSection(bridge)

        self.add_full_width(self.integration_section)
        self.add_row(self.command_section, self.protocol_section)
        self.add_row(self.frame_loss_section, self.motion_section)
        self.add_full_width(self.sensor_section)

    def refresh(self) -> None:
        self.integration_section.refresh()
        self.command_section.refresh()
        self.protocol_section.refresh()
        self.frame_loss_section.refresh()
        self.motion_section.refresh()
        self.sensor_section.refresh()

    def _open_manual_binary_dialog(self) -> str:
        if self._manual_binary_dialog is None:
            self._manual_binary_dialog = ManualBinaryCommandDialog(self.fit_controller, self)
        self._manual_binary_dialog.show()
        self._manual_binary_dialog.raise_()
        self._manual_binary_dialog.activateWindow()
        return "Opened Manual Binary Command dialog."

    def _open_manual_text_dialog(self) -> str:
        if self._manual_text_dialog is None:
            self._manual_text_dialog = ManualTextCommandDialog(self.fit_controller, self)
        self._manual_text_dialog.show()
        self._manual_text_dialog.raise_()
        self._manual_text_dialog.activateWindow()
        return "Opened Manual Text Command dialog."

    def _open_binary_fit_dialog(self) -> str:
        snapshot = self.fit_controller.binary_fit_status_snapshot()
        if snapshot.running and self._binary_fit_report_dialog is not None:
            self._binary_fit_report_dialog.show()
            self._binary_fit_report_dialog.raise_()
            self._binary_fit_report_dialog.activateWindow()
            return "Opened Binary FIT Report dialog."

        if self._binary_fit_config_dialog is None:
            self._binary_fit_config_dialog = BinaryFitConfigDialog(self.fit_controller, self)
            self._binary_fit_config_dialog.run_requested.connect(self._start_binary_fit_run)
        self._binary_fit_config_dialog.show()
        self._binary_fit_config_dialog.raise_()
        self._binary_fit_config_dialog.activateWindow()
        return "Opened Binary Firmware Integration Test configuration dialog."

    def _start_binary_fit_run(self, node_id: int, case_ids: object) -> None:
        selected_items = list(case_ids)
        self._binary_fit_report_dialog = BinaryFitReportDialog(self.fit_controller, self)
        self._binary_fit_report_dialog.destroyed.connect(self._clear_binary_fit_report_dialog)
        self._binary_fit_report_dialog.show()
        self._binary_fit_report_dialog.raise_()
        self._binary_fit_report_dialog.activateWindow()
        if all(hasattr(item, "case_id") for item in selected_items):
            started = self.fit_controller.start_binary_fit(node_id=int(node_id), cases=selected_items)
        else:
            selected_case_ids = [str(case_id) for case_id in selected_items if str(case_id).strip()]
            started = self.fit_controller.start_binary_fit(node_id=int(node_id), selected_case_ids=selected_case_ids)
        if started is not True:
            self._binary_fit_report_dialog.close()

    def _clear_binary_fit_report_dialog(self, _destroyed: object = None) -> None:
        self._binary_fit_report_dialog = None

    def _open_text_fit_dialog(self) -> str:
        snapshot = self.fit_controller.text_fit_status_snapshot()
        if snapshot.running and self._text_fit_report_dialog is not None:
            self._text_fit_report_dialog.show()
            self._text_fit_report_dialog.raise_()
            self._text_fit_report_dialog.activateWindow()
            return "Opened Text FIT Report dialog."

        if self._text_fit_config_dialog is None:
            self._text_fit_config_dialog = TextFitConfigDialog(self.fit_controller, self)
            self._text_fit_config_dialog.run_requested.connect(self._start_text_fit_run)
        self._text_fit_config_dialog.show()
        self._text_fit_config_dialog.raise_()
        self._text_fit_config_dialog.activateWindow()
        return "Opened Text Firmware Integration Test configuration dialog."

    def _start_text_fit_run(self, case_ids: object) -> None:
        selected_items = list(case_ids)
        self._text_fit_report_dialog = TextFitReportDialog(self.fit_controller, self)
        self._text_fit_report_dialog.destroyed.connect(self._clear_text_fit_report_dialog)
        self._text_fit_report_dialog.show()
        self._text_fit_report_dialog.raise_()
        self._text_fit_report_dialog.activateWindow()
        if selected_items and all(hasattr(item, "case_id") for item in selected_items):
            started = self.fit_controller.start_text_fit(cases=selected_items)
        else:
            selected_case_ids = [str(case_id) for case_id in selected_items if str(case_id).strip()]
            started = self.fit_controller.start_text_fit(selected_case_ids=selected_case_ids)
        if started is not True:
            self._text_fit_report_dialog.close()

    def _clear_text_fit_report_dialog(self, _destroyed: object = None) -> None:
        self._text_fit_report_dialog = None

    def _open_reports_dialog(self) -> str:
        if self._report_export_dialog is None:
            self._report_export_dialog = FirmwareReportExportDialog(self.fit_controller, self)
            self._report_export_dialog.destroyed.connect(self._clear_report_export_dialog)
        self._report_export_dialog.show()
        self._report_export_dialog.raise_()
        self._report_export_dialog.activateWindow()
        return "Opened Firmware Reports / Export dialog."

    def _clear_report_export_dialog(self, _destroyed: object = None) -> None:
        self._report_export_dialog = None
