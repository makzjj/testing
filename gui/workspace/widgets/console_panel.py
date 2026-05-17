"""Fixed right-side console widget."""

from __future__ import annotations

from PyQt6.QtCore import QDateTime
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .effects import apply_card_shadow


class ConsolePanel(QWidget):
    """Append-only console visible across all first-level pages."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ConsolePanel")
        apply_card_shadow(self, blur_radius=34, y_offset=12)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        title = QLabel("Console")
        title.setObjectName("ConsoleTitle")
        title.setMinimumWidth(title.fontMetrics().horizontalAdvance("Console") + 16)
        header.addWidget(title)

        header.addStretch(1)

        save_button = QPushButton("Save")
        save_button.setObjectName("ConsoleSaveButton")
        save_button.setProperty("tone", "secondary")
        save_button.setMinimumWidth(save_button.fontMetrics().horizontalAdvance("Save") + 44)
        save_button.clicked.connect(self.save_to_file)
        header.addWidget(save_button)

        clear_button = QPushButton("Clear")
        clear_button.setObjectName("ConsoleClearButton")
        clear_button.setProperty("tone", "secondary")
        clear_button.setMinimumWidth(clear_button.fontMetrics().horizontalAdvance("Clear") + 44)
        clear_button.clicked.connect(self.clear)
        header.addWidget(clear_button)

        root.addLayout(header)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setObjectName("ConsoleOutput")
        root.addWidget(self.output, 1)

    def append_line(self, message: str) -> None:
        """Append one timestamped line to the console."""
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.output.appendPlainText(f"[{timestamp}] {message}")
        scroll_bar = self.output.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def clear(self) -> None:
        """Clear console content."""
        self.output.clear()

    def save_to_file(self) -> None:
        """Save the current console output to a text file."""
        default_name = QDateTime.currentDateTime().toString("'workspace-log-'yyyyMMdd-HHmmss'.log'")
        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Workspace Log",
            default_name,
            "Log Files (*.log);;Text Files (*.txt);;All Files (*.*)",
        )
        if not selected_path:
            return

        with open(selected_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(self.output.toPlainText())

        self.append_line(f"Saved console log to {selected_path}")
