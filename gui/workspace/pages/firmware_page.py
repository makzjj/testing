"""Firmware page implementation."""

from __future__ import annotations

from PyQt6.QtCore import QTimer

from data.binary_cmd_builders import (
    build_get_nodetype_query_payload,
    build_get_uuid_query_payload,
    build_getver_query_payload,
    build_interrupt_query_payload,
)
from data.text_cmd_builders import build_text_command_payload
from myconfig.node_display import ML20_NODE_MAP, get_ml20_node_name

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
    FirmwareIntegrationSection,
    SystemInformationSection,
)
from .base_page import BaseWorkspacePage


class FirmwarePage(BaseWorkspacePage):
    """Focused firmware workspace page."""

    _CANONICAL_NODE_IDS = tuple(node_id for node_id in ML20_NODE_MAP if 3 <= int(node_id) <= 12)
    _NON_SENSOR_NODE_IDS = {10, 11}
    _REFRESH_STEP_INTERVAL_MS = 40
    _REFRESH_SETTLE_MS = 250
    _INT_COLOR_OK = "#00C853"
    _INT_COLOR_WARN = "#FFD600"
    _INT_COLOR_NA = "#FF2800"

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Firmware", "Command, protocol, and sensor tools.")
        self._bridge = bridge
        self.fit_controller = FirmwareIntegrationController(bridge)
        self._binary_fit_config_dialog: BinaryFitConfigDialog | None = None
        self._binary_fit_report_dialog: BinaryFitReportDialog | None = None
        self._text_fit_config_dialog: TextFitConfigDialog | None = None
        self._text_fit_report_dialog: TextFitReportDialog | None = None
        self._report_export_dialog: FirmwareReportExportDialog | None = None
        self._manual_binary_dialog: ManualBinaryCommandDialog | None = None
        self._manual_text_dialog: ManualTextCommandDialog | None = None
        self._system_info_refresh_active = False
        self._system_info_query_queue: list[tuple[str, int | None, object]] = []
        self._system_info_step_timer = QTimer(self)
        self._system_info_step_timer.setSingleShot(True)
        self._system_info_step_timer.timeout.connect(self._dispatch_next_system_info_query)
        self._system_info_render_timer = QTimer(self)
        self._system_info_render_timer.setSingleShot(True)
        self._system_info_render_timer.timeout.connect(self._finish_system_info_refresh)
        self.system_info_section = SystemInformationSection(on_update_clicked=self._handle_system_info_update_clicked)
        self.integration_section = FirmwareIntegrationSection(
            self.fit_controller,
            open_manual_binary_dialog=self._open_manual_binary_dialog,
            open_manual_text_dialog=self._open_manual_text_dialog,
            open_binary_fit_dialog=self._open_binary_fit_dialog,
            open_text_fit_dialog=self._open_text_fit_dialog,
            open_reports_dialog=self._open_reports_dialog,
        )

        self.add_full_width(self.integration_section)
        self.add_full_width(self.system_info_section)
        self._render_system_information()

    def refresh(self) -> None:
        self._render_system_information()
        self.integration_section.refresh()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._cancel_system_info_refresh()
        super().hideEvent(event)

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

    def _handle_system_info_update_clicked(self) -> None:
        if self._system_info_refresh_active:
            return
        self._system_info_refresh_active = True
        self.system_info_section.set_refresh_active(True)
        self._system_info_query_queue = self._build_system_info_query_queue()
        self._dispatch_next_system_info_query()

    def _build_system_info_query_queue(self) -> list[tuple[str, int | None, object]]:
        queue: list[tuple[str, int | None, object]] = [("text", None, build_text_command_payload("ver?"))]
        for node_id in self._CANONICAL_NODE_IDS:
            queue.append(("binary", int(node_id), build_getver_query_payload()))
            queue.append(("binary", int(node_id), build_get_uuid_query_payload()))
            queue.append(("binary", int(node_id), build_get_nodetype_query_payload()))
            if int(node_id) not in self._NON_SENSOR_NODE_IDS:
                queue.append(("binary", int(node_id), build_interrupt_query_payload()))
        return queue

    def _dispatch_next_system_info_query(self) -> None:
        if not self._system_info_query_queue:
            self._system_info_render_timer.start(self._REFRESH_SETTLE_MS)
            return

        query_kind, node_id, payload = self._system_info_query_queue.pop(0)
        try:
            if query_kind == "text":
                self._bridge.send_firmware_text_command(bytearray(payload))
            else:
                assert node_id is not None
                self._bridge.send_firmware_binary_command(int(node_id), list(payload))
        except Exception:
            pass

        if self._system_info_query_queue:
            self._system_info_step_timer.start(self._REFRESH_STEP_INTERVAL_MS)
        else:
            self._system_info_render_timer.start(self._REFRESH_SETTLE_MS)

    def _finish_system_info_refresh(self) -> None:
        self._system_info_refresh_active = False
        self.system_info_section.set_refresh_active(False)
        self._render_system_information()

    def _cancel_system_info_refresh(self) -> None:
        self._system_info_step_timer.stop()
        self._system_info_render_timer.stop()
        self._system_info_query_queue.clear()
        self._system_info_refresh_active = False
        self.system_info_section.set_refresh_active(False)

    def _render_system_information(self) -> None:
        self.system_info_section.render(
            mcu_version=self._display_mcu_firmware_version(),
            rows=[self._build_system_information_row(node_id) for node_id in self._CANONICAL_NODE_IDS],
        )

    def _build_system_information_row(self, node_id: int) -> dict[str, object]:
        info = self._read_runtime_node_system_info(node_id)
        detected = bool(info.get("detected", False))
        node_type_display = self._display_node_type(info.get("node_type"))
        int_status, int_color = self._display_interrupt_status(node_id, detected)
        return {
            "node": f"{self._display_node_label(node_id)} ({int(node_id)})",
            "firmware": self._display_node_firmware(info.get("firmware"), detected=detected),
            "uuid": self._display_uuid(info.get("uuid"), detected=detected),
            "node_type": node_type_display,
            "int_status": int_status,
            "int_color": int_color,
            "int_text_color": self._display_interrupt_text_color(int_color),
        }

    def _display_mcu_firmware_version(self) -> str:
        version = self._read_runtime_mcu_firmware_version()
        if version is None:
            return "Unknown"
        return self._normalize_version_text(version)

    def _display_node_firmware(self, value: object, *, detected: bool) -> str:
        text = self._normalize_optional_text(value)
        if text is not None:
            return self._normalize_version_text(text)
        return "Unknown" if detected else "Not Detected"

    def _display_uuid(self, value: object, *, detected: bool) -> str:
        text = self._normalize_optional_text(value)
        if text is not None:
            return text
        return "Unknown" if detected else "—"

    def _display_node_type(self, value: object) -> str:
        text = self._normalize_optional_text(value)
        if text is None:
            return "—"
        for prefix in ("MTR", "NGC", "HMI"):
            if text.upper().startswith(prefix):
                return prefix
        return text

    def _display_interrupt_status(self, node_id: int, detected: bool) -> tuple[str, str]:
        if int(node_id) in self._NON_SENSOR_NODE_IDS:
            return "N/A", self._INT_COLOR_NA
        if not detected:
            return "N/A", self._INT_COLOR_NA
        interrupt_state = self._read_runtime_interrupt_state(node_id)
        left_state = str(interrupt_state.get("left_state", "unknown"))
        right_state = str(interrupt_state.get("right_state", "unknown"))
        if left_state == "unknown" or right_state == "unknown":
            return "N/A", self._INT_COLOR_NA
        if left_state == "not_cut" and right_state == "not_cut":
            return "L: OK  R: OK", self._INT_COLOR_OK
        left_text = "Cut" if left_state == "cut" else "OK"
        right_text = "Cut" if right_state == "cut" else "OK"
        return f"L: {left_text}  R: {right_text}", self._INT_COLOR_WARN

    def _display_interrupt_text_color(self, background: str) -> str:
        if background == self._INT_COLOR_WARN:
            return "#4A3900"
        return "#FFFFFF"

    def _read_runtime_mcu_firmware_version(self) -> str | None:
        getter = getattr(self._bridge, "get_runtime_mcu_firmware_version", None)
        if callable(getter):
            return getter(create_if_missing=False)
        return None

    def _read_runtime_node_system_info(self, node_id: int) -> dict[str, object]:
        getter = getattr(self._bridge, "get_runtime_node_system_info", None)
        if callable(getter):
            return getter(int(node_id), create_if_missing=False)
        return {
            "node_id": int(node_id),
            "detected": False,
            "connected": False,
            "firmware": None,
            "uuid": None,
            "node_type": None,
        }

    def _read_runtime_interrupt_state(self, node_id: int) -> dict[str, object]:
        getter = getattr(self._bridge, "get_runtime_node_interrupt_state", None)
        if callable(getter):
            return getter(int(node_id), create_if_missing=False)
        return {
            "node_id": int(node_id),
            "left_state": "unknown",
            "right_state": "unknown",
        }

    @staticmethod
    def _display_node_label(node_id: int) -> str:
        if int(node_id) == 11:
            return "NGC"
        return str(get_ml20_node_name(int(node_id)) or f"Node {int(node_id)}")

    @staticmethod
    def _normalize_optional_text(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _normalize_version_text(value: object) -> str:
        text = str(value).strip()
        if not text:
            return "Unknown"
        if text.lower().startswith("ver:"):
            text = text.partition(":")[2].strip()
        text = text.replace("_", ".")
        if text.lower().startswith("v"):
            return f"v{text[1:].strip()}"
        return f"v{text}"
