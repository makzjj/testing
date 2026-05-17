"""Compact rounded status chip used across the workspace shell."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy


class StatusChip(QLabel):
    """Small rounded badge with a semantic tone."""

    def __init__(self, text: str, tone: str = "neutral") -> None:
        super().__init__(text)
        self.setObjectName("StatusChip")
        self.setProperty("tone", tone)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
