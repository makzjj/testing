"""Small labeled control wrapper for form-like section layouts."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LabeledControl(QWidget):
    """Wrap a control with a compact label and consistent spacing."""

    def __init__(self, label_text: str, control: QWidget) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        label = QLabel(label_text)
        label.setObjectName("FieldLabel")
        root.addWidget(label)

        root.addWidget(control)
