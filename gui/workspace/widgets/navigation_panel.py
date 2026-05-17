"""Left navigation rail widget."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..constants import BRAND_IMAGE_PATH
from ..models import NavigationItem
from .effects import apply_card_shadow
from .navigation_button import NavigationButton


class NavigationPanel(QWidget):
    """Renders brand identity and first-level route buttons."""

    route_selected = pyqtSignal(str)

    def __init__(self, project_name: str, items: list[NavigationItem]) -> None:
        super().__init__()
        self.setObjectName("NavigationPanel")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        apply_card_shadow(self, blur_radius=36, y_offset=12)
        self._buttons: dict[str, NavigationButton] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 18)
        root.setSpacing(10)

        brand_image = QLabel()
        pixmap = QPixmap(str(BRAND_IMAGE_PATH))
        if not pixmap.isNull():
            brand_image.setPixmap(pixmap.scaledToHeight(36, Qt.TransformationMode.SmoothTransformation))
        else:
            brand_image.setText("BioBot")
        root.addWidget(brand_image)

        product = QLabel("Workspace")
        product.setObjectName("NavProduct")
        root.addWidget(product)

        project = QLabel(project_name)
        project.setObjectName("NavProjectChip")
        root.addWidget(project)

        for item in items:
            button = NavigationButton(item.label, item.description)
            button.setEnabled(item.enabled)
            button.clicked.connect(lambda checked=False, route_id=item.route_id: self.route_selected.emit(route_id))
            root.addWidget(button)
            self._buttons[item.route_id] = button

        root.addStretch(1)

    def set_active_route(self, route_id: str) -> None:
        """Update checked state for all route buttons."""
        for item_route_id, button in self._buttons.items():
            button.setChecked(item_route_id == route_id)
