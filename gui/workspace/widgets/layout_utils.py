"""Small layout helpers for rebuilding section content."""

from __future__ import annotations


def clear_layout(layout) -> None:
    """Remove all child items from a Qt layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        if child_layout is not None:
            clear_layout(child_layout)
