"""Project Config page implementation."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QMessageBox, QVBoxLayout, QWidget

from myconfig.config_models import ConfigEditorModel, SavePlan, SaveResult

from ..bridges import WorkspaceRuntimeBridge
from ..models import SessionState
from ..sections.project_config import ConfigHeaderPanel, ConfigSectionPanel, VersionChangeDialog
from ..widgets import ResponsiveRow
from ..widgets.layout_utils import clear_layout
from .base_page import BaseWorkspacePage


class ProjectConfigPage(BaseWorkspacePage):
    """YAML-driven Project Config editor for the selected workspace."""

    console_message = pyqtSignal(str)
    config_path_changed = pyqtSignal(object)
    project_definition_changed = pyqtSignal(object)

    def __init__(self, bridge: WorkspaceRuntimeBridge, action_handler: Callable[[str], None], state: SessionState) -> None:
        super().__init__("", "")
        self._bridge = bridge
        self._state = state
        self._action_handler = action_handler
        self._editor_model: ConfigEditorModel | None = None
        self._section_panels: list[ConfigSectionPanel] = []

        self.header_panel = ConfigHeaderPanel()
        self.header_panel.save_requested.connect(self._handle_save_requested)
        self.header_panel.reload_requested.connect(self._handle_reload_requested)
        self.header_panel.reveal_requested.connect(self._handle_reveal_requested)
        self.add_full_width(self.header_panel)

        self._error_label = QLabel("")
        self._error_label.setObjectName("ConfigIssueBanner")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self.add_full_width(self._error_label)

        self._sections_host = QWidget()
        self._sections_layout = QVBoxLayout(self._sections_host)
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(6)
        self.add_full_width(self._sections_host)

        self.refresh(state)

    def refresh(self, state: SessionState) -> None:
        """Refresh the editor model, top summary, and rendered YAML sections."""
        self._state = state
        try:
            self._editor_model = self._bridge.get_config_editor_model()
        except Exception as exc:
            self._editor_model = None
            self.header_panel.set_message(str(exc))
            self._show_error_state(str(exc))
            return

        self._error_label.hide()
        self.header_panel.update_model(self._editor_model)
        self.header_panel.set_message("")
        self._rebuild_section_panels(self._editor_model)

    def _handle_reload_requested(self) -> None:
        try:
            payload = self._collect_payload() if self._editor_model is not None else None
            message = self._bridge.reload_project_config(payload)
        except Exception as exc:
            QMessageBox.warning(self, "Reload Failed", str(exc))
            self.header_panel.set_message(str(exc))
            return

        self.refresh(self._state)
        self.header_panel.set_message(message)
        self.console_message.emit(message)
        self.project_definition_changed.emit(self._bridge.project_definition)

    def _handle_reveal_requested(self) -> None:
        try:
            message = self._bridge.reveal_project_config_file()
        except Exception as exc:
            QMessageBox.warning(self, "Reveal Failed", str(exc))
            self.header_panel.set_message(str(exc))
            return

        self.header_panel.set_message(message)
        self.console_message.emit(message)

    def _handle_save_requested(self) -> None:
        if self._editor_model is None:
            return

        try:
            payload = self._collect_payload()
            result = self._bridge.save_config_changes(payload)
            if isinstance(result, SavePlan) and result.requires_confirmation:
                result = self._save_with_new_version(payload)
                if result is None:
                    self.header_panel.set_message("Save cancelled.")
                    return
            self._finalize_save(result)
        except Exception as exc:
            QMessageBox.warning(self, "Save Failed", str(exc))
            self.header_panel.set_message(str(exc))

    def _save_with_new_version(self, payload: dict) -> SaveResult | None:
        dialog = VersionChangeDialog(self._editor_model.version if self._editor_model is not None else None, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return self._bridge.save_config_changes(
            payload,
            requested_version=dialog.requested_version(),
            confirmed_new_version=True,
        )

    def _finalize_save(self, result: SaveResult | SavePlan) -> None:
        if not isinstance(result, SaveResult):
            raise ValueError(result.warning_text)
        self.console_message.emit(result.message)
        self.config_path_changed.emit(result.saved_path)
        self.refresh(self._state)
        self.header_panel.set_message(result.message)
        self.project_definition_changed.emit(self._bridge.project_definition)

    def _collect_payload(self) -> dict:
        payload: dict = {}
        for panel in self._section_panels:
            payload[panel.section_key] = panel.collect_value()
        return payload

    def _show_error_state(self, message: str) -> None:
        clear_layout(self._sections_layout)
        self._section_panels = []
        self._error_label.setText(message)
        self._error_label.show()

    def _rebuild_section_panels(self, editor_model: ConfigEditorModel) -> None:
        clear_layout(self._sections_layout)
        self._section_panels = []
        compact_row: ResponsiveRow | None = None
        compact_capacity = 0
        compact_count = 0

        def flush_row() -> None:
            nonlocal compact_row, compact_capacity, compact_count
            if compact_row is not None and compact_count:
                self._sections_layout.addWidget(compact_row)
            compact_row = None
            compact_capacity = 0
            compact_count = 0

        for section in editor_model.sections:
            panel = ConfigSectionPanel(section)
            self._section_panels.append(panel)

            compact_slots = self._compact_slot_count(section)
            if compact_slots == 1:
                flush_row()
                self._sections_layout.addWidget(panel)
                continue

            if compact_row is None or compact_capacity != compact_slots:
                flush_row()
                compact_row = self._build_section_row(compact_slots)
                compact_capacity = compact_slots

            compact_row.add_panel(panel)
            compact_count += 1
            if compact_count == compact_capacity:
                flush_row()

        flush_row()

    def _build_section_row(self, compact_slots: int) -> ResponsiveRow:
        stack_below_width = 900
        return ResponsiveRow(stack_below_width=stack_below_width)

    def _compact_slot_count(self, section) -> int:
        if section.section_key == "robot arm configuration":
            return 1
        if section.raw_value_type == "list":
            if section.section_key == "command list" and not section.fields:
                return 2
            return 1
        if len(section.fields) > 6:
            return 1
        return 2
