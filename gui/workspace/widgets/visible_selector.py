"""Visible low-click selector used in place of dropdowns."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..models import SelectionOption
from .layout_utils import clear_layout


class VisibleSelector(QWidget):
    """Render options as exposed rounded choices instead of a hidden dropdown."""

    selection_changed = pyqtSignal(str)

    def __init__(
        self,
        options: list[str] | list[SelectionOption],
        current_value: str | None = None,
        style: str = "auto",
        columns: int | None = None,
        visible_rows: int | None = None,
        max_visible_rows: int = 4,
    ) -> None:
        super().__init__()
        self._style = style
        self._columns = columns
        self._visible_rows = visible_rows
        self._max_visible_rows = max_visible_rows
        self._options = self._normalize_options(options)
        self._current_value = current_value or (self._options[0].value if self._options else "")
        self._buttons: dict[str, QPushButton] = {}
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._build_selector()

    def current_value(self) -> str:
        """Return the value of the currently selected option."""
        return self._current_value

    def set_current_value(self, value: str) -> None:
        """Update the selected option without rebuilding the widget tree."""
        button = self._buttons.get(value)
        if button is None:
            return

        self._current_value = value
        if not button.isChecked():
            button.setChecked(True)

    def _build_selector(self) -> None:
        """Build the selector UI using either a button grid or a scrollable list."""
        for button in self._button_group.buttons():
            self._button_group.removeButton(button)
        clear_layout(self._root)
        self._buttons.clear()

        if self._resolve_style() == "list":
            self._root.addWidget(self._build_list_surface())
        else:
            self._root.addWidget(self._build_segmented_surface())

        self.set_current_value(self._current_value)

    def _build_list_surface(self) -> QWidget:
        """Create a scrollable list surface for longer or denser option sets."""
        scroll = QScrollArea()
        scroll.setObjectName("VisibleSelectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        viewport = QWidget()
        viewport.setObjectName("VisibleSelectorViewport")
        layout = QVBoxLayout(viewport)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for option in self._options:
            layout.addWidget(self._build_option_button(option, "list"))

        layout.addStretch(1)
        scroll.setWidget(viewport)

        visible_rows = self._resolve_visible_rows()
        row_height = 34
        spacing_height = max(0, visible_rows - 1) * 6
        surface_height = (visible_rows * row_height) + spacing_height + 4
        scroll.setFixedHeight(surface_height)
        return scroll

    def _build_segmented_surface(self) -> QWidget:
        """Create a compact segmented surface for short option sets."""
        surface = QWidget()
        surface.setObjectName("VisibleSelectorViewport")
        layout = QGridLayout(surface)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        column_count = self._resolve_columns()
        for index, option in enumerate(self._options):
            layout.addWidget(self._build_option_button(option, "segmented"), index // column_count, index % column_count)

        for column in range(column_count):
            layout.setColumnStretch(column, 1)

        return surface

    def _build_option_button(self, option: SelectionOption, variant: str) -> QPushButton:
        """Create one rounded option button and bind it into the exclusive selector group."""
        button = QPushButton(option.label)
        button.setObjectName("SelectorOptionButton")
        button.setProperty("selectorVariant", variant)
        button.setCheckable(True)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if variant == "list":
            button.setFixedHeight(34)
        else:
            button.setMinimumHeight(40)
        if option.description:
            button.setToolTip(option.description)
        if option.value == self._current_value:
            button.setChecked(True)

        button.clicked.connect(lambda _checked=False, value=option.value: self._select_value(value))
        self._button_group.addButton(button)
        self._buttons[option.value] = button
        return button

    def _resolve_style(self) -> str:
        """Choose the visible selector style for the current option set."""
        if self._style != "auto":
            return self._style
        return "segmented" if len(self._options) <= 3 else "list"

    def _resolve_columns(self) -> int:
        """Choose how many segmented columns to show when the selector is compact."""
        if self._columns is not None:
            return max(1, self._columns)
        return max(1, min(3, len(self._options)))

    def _resolve_visible_rows(self) -> int:
        """Choose how many list rows stay visible before scrolling is used."""
        if self._visible_rows is not None:
            return max(1, self._visible_rows)
        return max(1, min(self._max_visible_rows, len(self._options)))

    def _select_value(self, value: str) -> None:
        """Store one selected value and broadcast the change."""
        if value == self._current_value:
            return

        self._current_value = value
        self.selection_changed.emit(value)

    def _normalize_options(self, options: list[str] | list[SelectionOption]) -> list[SelectionOption]:
        """Convert loose string lists into typed visible-selector options."""
        normalized: list[SelectionOption] = []
        seen_values: set[str] = set()
        for option in options:
            normalized_option = option if isinstance(option, SelectionOption) else SelectionOption(label=option, value=option)
            if normalized_option.value in seen_values:
                continue

            seen_values.add(normalized_option.value)
            normalized.append(normalized_option)
        return normalized
