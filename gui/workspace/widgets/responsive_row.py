"""Responsive row container that stacks panels when width is tight."""

from __future__ import annotations

from PyQt6.QtWidgets import QBoxLayout, QSizePolicy, QWidget


class ResponsiveRow(QWidget):
    """Lay out section panels horizontally until the row becomes too narrow."""

    def __init__(self, stack_below_width: int = 820) -> None:
        super().__init__()
        self._stack_below_width = stack_below_width
        self._children: list[QWidget] = []
        self._stretches: list[int] = []

        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

    def add_panel(self, widget: QWidget, *, stretch: int = 1) -> None:
        """Add one section panel to the responsive row."""
        self._children.append(widget)
        self._stretches.append(max(1, int(stretch)))
        self._layout.addWidget(widget)
        self._update_direction()

    def stretch_factors(self) -> tuple[int, ...]:
        """Return configured horizontal stretch factors for each panel."""
        return tuple(self._stretches)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_direction()

    def _update_direction(self) -> None:
        stacked = self.width() < self._stack_below_width and len(self._children) > 1
        direction = QBoxLayout.Direction.TopToBottom if stacked else QBoxLayout.Direction.LeftToRight
        if self._layout.direction() != direction:
            self._layout.setDirection(direction)

        for index, stretch in enumerate(self._stretches):
            self._layout.setStretch(index, 0 if stacked else stretch)
