"""Lightweight non-editable table used by page sections."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem


class SimpleTableWidget(QTableWidget):
    """Styled read-only table for compact workspace data."""

    def __init__(self, headers: list[str], rows: list[list[str]]) -> None:
        super().__init__(len(rows), len(headers))
        self.setObjectName("SimpleTableWidget")
        self.setHorizontalHeaderLabels(headers)
        self.verticalHeader().hide()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.horizontalHeader().setHighlightSections(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        self.setCornerButtonEnabled(False)

        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.setItem(row_index, column_index, item)

        default_row_height = self.fontMetrics().lineSpacing() + 16
        for row_index in range(self.rowCount()):
            self.setRowHeight(row_index, default_row_height)
