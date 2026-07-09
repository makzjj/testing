"""Popup viewer for the shared company-style communication log."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QDialog, QWidget, QCheckBox

from services.communication_log_store import CommunicationLogStore
from utils.deployment_paths import get_runtime_exports_dir


class CommunicationLogDialog(QDialog):
    """Read-only popup for the application-wide communication log."""

    def __init__(
        self,
        store: CommunicationLogStore,
        parent: QWidget | None = None,
        *,
        context_provider: Callable[[], tuple[str, str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Communication Logs")
        self.setModal(False)

        self.setMinimumSize(860, 520)
        self._apply_initial_size()

        self._store = store
        self._context_provider = context_provider or (lambda: ("-", "-"))
        self._last_rendered_text = ""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        title_label = QLabel("Communication Logs")
        title_label.setObjectName("PanelTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)

        self.save_button = QPushButton("Save Logs")
        self.save_button.setProperty("tone", "secondary")
        self.save_button.clicked.connect(self._handle_save_clicked)
        header_row.addWidget(self.save_button)

        self.clear_button = QPushButton("Clear")
        self.clear_button.setProperty("tone", "secondary")
        self.clear_button.clicked.connect(self._handle_clear_clicked)
        header_row.addWidget(self.clear_button)

        self.hide_polling_checkbox = QCheckBox("Hide polling packets")
        self.hide_polling_checkbox.toggled.connect(lambda _checked: self._sync_from_store())
        header_row.addWidget(self.hide_polling_checkbox)

        root_layout.addLayout(header_row)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.log_output.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_output.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        root_layout.addWidget(self.log_output, 1)

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.addStretch(1)

        self.close_button = QPushButton("Close")
        self.close_button.setProperty("tone", "secondary")
        self.close_button.clicked.connect(self.hide)
        footer_row.addWidget(self.close_button)
        root_layout.addLayout(footer_row)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self._sync_from_store)
        self._refresh_timer.start()

        self._sync_from_store()

    def showEvent(self, event) -> None:  # noqa: N802
        self._sync_from_store()
        super().showEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()

    def _sync_from_store(self) -> None:
        text = self._store.to_plain_text(hide_polling_packets=self.hide_polling_checkbox.isChecked())
        if text == self._last_rendered_text and self.log_output.toPlainText() == text:
            return

        scrollbar = self.log_output.verticalScrollBar()
        was_at_bottom = scrollbar.value() >= max(0, scrollbar.maximum() - 2)
        previous_value = scrollbar.value()
        self.log_output.setPlainText(text)

        if was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(min(previous_value, scrollbar.maximum()))

        self._last_rendered_text = text

    def _handle_clear_clicked(self) -> None:
        self._store.clear()
        self._sync_from_store()

    def _handle_save_clicked(self) -> None:
        current_page, selected_node = self._resolve_context()
        default_name = datetime.now().strftime("%Y%m%d_%H%M%S_communication.log")
        file_path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Communication Logs",
            str(get_runtime_exports_dir() / default_name),
            "Log Files (*.log);;All Files (*)",
        )
        if not file_path:
            return
        self._store.save(
            file_path,
            exported_at=datetime.now(),
            current_page=current_page,
            selected_node=selected_node,
        )

    def _apply_initial_size(self) -> None:
        screen = self.screen()
        if screen is None:
            screen = QApplication.primaryScreen()

        if screen is None:
            self.resize(1080, 680)
            return

        available = screen.availableGeometry()
        width_cap = int(available.width() * 0.8)
        height_cap = int(available.height() * 0.68)
        width = min(1120, width_cap)
        height = min(700, height_cap)
        self.resize(max(self.minimumWidth(), width), max(self.minimumHeight(), height))

    def _resolve_context(self) -> tuple[str, str]:
        try:
            current_page, selected_node = self._context_provider()
        except Exception:
            return "-", "-"
        return str(current_page or "-"), str(selected_node or "-")
