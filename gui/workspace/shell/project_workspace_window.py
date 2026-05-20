"""Top-level Phase 2 workspace shell window."""

from __future__ import annotations

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QVBoxLayout, QWidget

from myconfig.project_models import ProjectDefinition

from ..bridges import WorkspaceRuntimeBridge
from ..constants import (
    RESOURCES_DIR,
    ROUTE_APPLICATION,
    ROUTE_FIRMWARE,
    ROUTE_MECHANICAL,
    ROUTE_PRODUCTION,
    ROUTE_PROJECT_CONFIG,
    ROUTE_RUNTIME,
    WORKSPACE_TITLE_PREFIX,
)
from ..pages import ApplicationProductionPage, FirmwarePage, MechanicalPage, ProductionPage, ProjectConfigPage, RuntimePage
from ..widgets import ConsolePanel, LiveSessionPanel, WorkspaceBackdrop, WorkspaceTopBar
from .workspace_page_registry import build_navigation_items, get_route_label
from .workspace_page_stack import WorkspacePageStack


class ProjectWorkspaceWindow(QMainWindow):
    """Shared project workspace shell introduced in Phase 2."""

    def __init__(self, project_definition: ProjectDefinition) -> None:
        super().__init__()
        self._project_definition = project_definition
        self._bridge = WorkspaceRuntimeBridge(project_definition)
        self._navigation_items = build_navigation_items(project_definition)
        self._pages: dict[str, object] = {}
        self._current_route_id = self._resolve_available_route(ROUTE_PRODUCTION)
        self._settings_labels = {
            "auto_node_scan": "Auto node scan",
            "restore_last_project": "Restore last project",
            "write_trace_log": "Write trace log",
        }

        self.setWindowTitle(f"{WORKSPACE_TITLE_PREFIX} - {project_definition.display_name}")
        self.setWindowIcon(QIcon(str(RESOURCES_DIR / "biobot_robot_arm.ico")))
        self.setFont(QFont("Segoe UI", 12))
        self.resize(1560, 940)
        self.setStyleSheet(self._build_stylesheet())

        self._build_ui()
        self._append_boot_messages()
        self._sync_shell_to_project_definition(preferred_route=self._current_route_id, log_route_change=False)

    def _build_ui(self) -> None:
        central = WorkspaceBackdrop()
        central.setObjectName("WorkspaceRoot")
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        center_column = QWidget()
        center_column.setObjectName("CenterColumn")
        center_layout = QVBoxLayout(center_column)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        top_controls = QHBoxLayout()
        top_controls.setContentsMargins(0, 0, 0, 0)
        top_controls.setSpacing(4)

        self.top_bar = WorkspaceTopBar(
            self._project_definition.display_name,
            self._bridge.project_config_path,
            self._navigation_items,
        )
        self.top_bar.route_selected.connect(self.set_active_page)
        self.top_bar.action_requested.connect(self._handle_action)
        self.top_bar.preference_toggled.connect(self._handle_preference_toggle)
        top_controls.addWidget(self.top_bar, 0)
        top_controls.addStretch(1)
        center_layout.addLayout(top_controls)

        self.page_stack = WorkspacePageStack()
        self.page_stack.setObjectName("PageStack")
        center_layout.addWidget(self.page_stack, 1)
        root.addWidget(center_column, 1)

        self.right_column = QWidget()
        self.right_column.setObjectName("RightColumn")
        right_layout = QVBoxLayout(self.right_column)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.console_panel = ConsolePanel()
        right_layout.addWidget(self.console_panel, 1)

        self.live_session_panel = LiveSessionPanel()
        self.live_session_panel.setMaximumHeight(104)
        right_layout.addWidget(self.live_session_panel, 0)

        self._update_shell_widths()

        root.addWidget(self.right_column, 0)

        self._build_pages()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_shell_widths()

    def _build_pages(self) -> None:
        initial_state = self._bridge.get_session_state(get_route_label(self._navigation_items, ROUTE_PROJECT_CONFIG))

        self._pages = {
            ROUTE_PROJECT_CONFIG: ProjectConfigPage(self._bridge, self._handle_action, initial_state),
            ROUTE_PRODUCTION: ProductionPage(self._bridge),
            ROUTE_FIRMWARE: FirmwarePage(self._bridge),
            ROUTE_MECHANICAL: MechanicalPage(self._bridge),
            ROUTE_APPLICATION: ApplicationProductionPage(self._bridge),
            ROUTE_RUNTIME: RuntimePage(self._bridge),
        }

        for route_id, page in self._pages.items():
            self.page_stack.register_page(route_id, page)
            if hasattr(page, "console_message"):
                page.console_message.connect(self.console_panel.append_line)
            if hasattr(page, "config_path_changed"):
                page.config_path_changed.connect(self.top_bar.update_config_path)
            if hasattr(page, "project_definition_changed"):
                page.project_definition_changed.connect(self._handle_project_definition_changed)
            if hasattr(page, "action_requested"):
                page.action_requested.connect(self._handle_action)

    def set_active_page(self, route_id: str, log_route_change: bool = True) -> None:
        """Switch the visible first-level page and refresh shell state."""
        route_id = self._resolve_available_route(route_id)
        self._current_route_id = route_id
        self.page_stack.show_page(route_id)
        self.top_bar.set_active_route(route_id)

        route_label = get_route_label(self._navigation_items, route_id)
        session_state = self._bridge.get_session_state(route_label)
        self.live_session_panel.update_state(session_state)

        page = self._pages[route_id]
        if route_id == ROUTE_PROJECT_CONFIG:
            page.refresh(session_state)
        else:
            page.refresh()

        if log_route_change:
            self.console_panel.append_line(f"Switched workspace route to {route_label}")

    def _handle_action(self, action_id: str) -> None:
        """Handle one page-originated action in a shell-owned way."""
        if action_id in {"open_legacy_runtime", "focus_legacy_runtime"}:
            self.set_active_page(ROUTE_RUNTIME, log_route_change=False)
        message = self._bridge.run_action(action_id)
        self.console_panel.append_line(message)
        if action_id == "refresh_workspace":
            self._sync_shell_to_project_definition(preferred_route=self._current_route_id, log_route_change=False)
            return
        self.set_active_page(self._current_route_id, log_route_change=False)

    def _handle_preference_toggle(self, setting_id: str, checked: bool) -> None:
        """Handle one lightweight settings-menu toggle."""
        label = self._settings_labels.get(setting_id, setting_id.replace("_", " "))
        state_text = "enabled" if checked else "disabled"
        self.console_panel.append_line(f"{label} {state_text} in workspace settings")

    def _append_boot_messages(self) -> None:
        for message in self._bridge.get_boot_messages():
            self.console_panel.append_line(message)

    def _handle_project_definition_changed(self, _project_definition: object) -> None:
        """Refresh shell-wide navigation and identity when the Project Config state changes."""
        self._sync_shell_to_project_definition(preferred_route=self._current_route_id, log_route_change=False)

    def _sync_shell_to_project_definition(self, preferred_route: str | None, log_route_change: bool) -> None:
        """Refresh shell navigation, title, and active route from the latest project definition."""
        self._project_definition = self._bridge.project_definition
        self._navigation_items = build_navigation_items(self._project_definition)
        self.top_bar.update_project_context(
            self._project_definition.display_name,
            self._bridge.project_config_path,
            self._navigation_items,
        )
        self.setWindowTitle(f"{WORKSPACE_TITLE_PREFIX} - {self._project_definition.display_name}")
        self.set_active_page(self._resolve_available_route(preferred_route), log_route_change=log_route_change)

    def _resolve_available_route(self, preferred_route: str | None) -> str:
        """Resolve the best currently enabled route, preferring the requested route and Production."""
        enabled_routes = [item.route_id for item in self._navigation_items if item.enabled]
        if preferred_route in enabled_routes:
            return preferred_route
        if ROUTE_PRODUCTION in enabled_routes:
            return ROUTE_PRODUCTION
        if ROUTE_FIRMWARE in enabled_routes:
            return ROUTE_FIRMWARE
        if enabled_routes:
            return enabled_routes[0]
        return ROUTE_PROJECT_CONFIG

    def _update_shell_widths(self) -> None:
        """Keep the right utility column visibly wide enough for persistent console work."""
        available_width = max(self.width() - 48, 0)
        utility_width = min(460, max(340, int(available_width * 0.285)))
        minimum_center_width = 760
        center_width = available_width - utility_width - 12

        if center_width < minimum_center_width:
            utility_width = max(320, available_width - minimum_center_width - 12)

        if hasattr(self, "right_column"):
            self.right_column.setFixedWidth(max(320, utility_width))

    def _build_stylesheet(self) -> str:
        """Build a shared stylesheet for the workspace shell."""
        return """
        QMainWindow {
            background: #FAF4EE;
        }
        QWidget#WorkspaceRoot {
            background: #FAF4EE;
        }
        QWidget#CenterColumn,
        QWidget#RightColumn,
        QWidget#WorkspaceTopBar,
        QWidget#LiveSessionPanel,
        QWidget#ConsolePanel,
        QStackedWidget#PageStack {
            background: transparent;
        }
        QStackedWidget#PageStack {
            background: #F3F5F8;
            border: 1px solid #ECEFF4;
            border-radius: 22px;
        }
        QWidget#LiveSessionPanel,
        QWidget#ConsolePanel,
        QFrame#WorkspacePanel {
            background: rgba(255, 255, 255, 0.88);
            border: 1px solid rgba(232, 224, 217, 0.92);
            border-radius: 20px;
        }
        QLabel#ToolbarProjectChip {
            color: #A46533;
            background: #FFF0E3;
            border: 1px solid #F3D5BE;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 600;
        }
        QWidget#WorkspaceTopBar {
            background: transparent;
            border: none;
        }
        QWidget#LiveSessionPanel,
        QWidget#ConsolePanel {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid #E8ECEF;
        }
        QPushButton#NavigationButton {
            background: transparent;
            color: #5D4C43;
            border: 1px solid transparent;
            border-radius: 18px;
            font-size: 15px;
            font-weight: 600;
            padding: 9px 14px;
            text-align: left;
        }
        QPushButton#NavigationButton:hover {
            background: rgba(255, 243, 231, 0.78);
            border: 1px solid #F2DECF;
        }
        QPushButton#NavigationButton:checked {
            background: #FFEAD7;
            color: #8F5628;
            border: 1px solid #F0D5C0;
        }
        QPushButton#NavigationButton[variant="toolbar"] {
            border-radius: 10px;
            font-size: 14px;
            padding: 6px 10px;
            min-height: 20px;
        }
        QToolButton#ToolbarSettingsButton {
            background: #FFFFFF;
            color: #5D4C43;
            border: 1px solid #E6D7CB;
            border-radius: 10px;
            padding: 4px;
            min-width: 32px;
            max-width: 32px;
            min-height: 32px;
            max-height: 32px;
        }
        QToolButton#ToolbarSettingsButton:hover {
            background: #FFF7F0;
            border: 1px solid #EBCFB9;
        }
        QToolButton#ToolbarSettingsButton::menu-indicator {
            image: none;
            width: 0px;
        }
        QMenu#WorkspaceSettingsMenu {
            background: #FFFFFF;
            color: #584B43;
            border: 1px solid #E6EAF0;
            border-radius: 14px;
            padding: 8px;
        }
        QMenu#WorkspaceSettingsMenu::item {
            border-radius: 10px;
            padding: 8px 14px;
            margin: 1px 0;
        }
        QMenu#WorkspaceSettingsMenu::item:selected {
            background: #FFF2E5;
            color: #8A5228;
        }
        QMenu#WorkspaceSettingsMenu::separator {
            height: 1px;
            background: #EEF1F5;
            margin: 6px 10px;
        }
        QLabel#LiveSessionTitle {
            color: #54453D;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#SessionMetaLabel {
            color: #A4948B;
            font-size: 14px;
            font-weight: 700;
            text-transform: uppercase;
        }
        QLabel#SessionMetaValue {
            color: #54453D;
            font-size: 15px;
            font-weight: 600;
        }
        QLabel#ConsoleTitle {
            color: #54453D;
            font-size: 17px;
            font-weight: 700;
        }
        QPlainTextEdit#ConsoleOutput {
            background: #F5F7FB;
            color: #5B524C;
            border: 1px solid #E8ECF1;
            border-radius: 16px;
            padding: 10px;
            font-family: Consolas;
            font-size: 15px;
        }
        QPushButton {
            background: #FFFFFF;
            color: #5D4C43;
            border: 1px solid #E6D7CB;
            border-radius: 16px;
            font-size: 14px;
            font-weight: 600;
            padding: 8px 14px;
        }
        QPushButton:hover {
            background: #FFF7F0;
            border: 1px solid #EBCFB9;
        }
        QPushButton[tone="primary"] {
            background: #FF9633;
            color: white;
            border: 1px solid #F18A2B;
        }
        QPushButton[tone="primary"]:hover {
            background: #FA8D24;
            border: 1px solid #EC8119;
        }
        QPushButton[tone="secondary"] {
            background: #FFFFFF;
            color: #6A5B52;
            border: 1px solid #E7D8CC;
        }
        QPushButton[tone="danger"] {
            background: #FFF5F4;
            color: #D16D67;
            border: 1px solid #F0C6C2;
        }
        QLabel#PageTitle {
            color: #554740;
            font-size: 17px;
            font-weight: 700;
        }
        QLabel#PageSubtitle {
            color: #9B8E87;
            font-size: 15px;
        }
        QFrame#ConfigHeaderPanel {
            background: transparent;
            border: none;
        }
        QFrame#ConfigActionCluster {
            background: #FCFDFE;
            border: 1px solid #E8EDF2;
            border-radius: 12px;
        }
        QFrame#ConfigActionCluster QPushButton {
            border-radius: 9px;
            padding: 4px 9px;
            font-size: 13px;
        }
        QLabel#ConfigToolbarTitle {
            color: #584A42;
            font-size: 19px;
            font-weight: 700;
        }
        QLabel#ConfigToolbarMeta,
        QLabel#ConfigMetaValue,
        QLabel#ConfigInlineMeta,
        QLabel#ConfigActionHint {
            color: #756A63;
            font-size: 15px;
        }
        QLabel#ConfigIssueBanner {
            background: #FFF5EA;
            color: #9B5F2A;
            border: 1px solid #F0D4B9;
            border-radius: 12px;
            padding: 6px 8px;
            font-size: 13px;
        }
        QFrame#ConfigContainerFrame {
            background: #FAFBFD;
            border: 1px solid #EEF1F5;
            border-radius: 10px;
        }
        QFrame#ConfigFieldRow {
            background: transparent;
            border: none;
        }
        QFrame#ConfigSummaryField {
            background: transparent;
            border: none;
        }
        QLabel#ConfigKeyLabel {
            color: #5A4C44;
            font-size: 13px;
            font-weight: 700;
        }
        QLabel#ConfigSummaryLabel {
            color: #978A82;
            font-size: 14px;
            font-weight: 700;
        }
        QLabel#ConfigSubsectionLabel {
            color: #8C8178;
            font-size: 15px;
            font-weight: 600;
        }
        QFrame#ConfigAxisHeaderFrame {
            background: #F8FAFC;
            border: 1px solid #EDF1F5;
            border-radius: 12px;
        }
        QComboBox#AxisSelectorCombo {
            background: #FCFDFE;
            color: #594C44;
            border: 1px solid #E7DCCF;
            border-radius: 10px;
            padding: 5px 28px 5px 9px;
            min-width: 88px;
            min-height: 18px;
            font-size: 14px;
        }
        QComboBox#AxisSelectorCombo:hover {
            background: #FFF8F1;
            border: 1px solid #EACDB7;
        }
        QComboBox#AxisSelectorCombo::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 22px;
            border-left: 1px solid #E7DCCF;
            background: #FFF7EE;
            border-top-right-radius: 10px;
            border-bottom-right-radius: 10px;
        }
        QComboBox#AxisSelectorCombo::down-arrow {
            width: 8px;
            height: 8px;
        }
        QFrame#ConfigSubpanelFrame {
            background: #FAFBFD;
            border: 1px solid #EEF2F6;
            border-radius: 12px;
        }
        QFrame#ConfigSubpanelFrame[muted="true"] {
            background: #FBFCFE;
            border: 1px solid #F1F3F7;
        }
        QToolButton#ConfigSubsectionToggle {
            background: transparent;
            color: #6D6159;
            border: none;
            font-size: 15px;
            font-weight: 700;
            padding: 1px 0;
            text-align: left;
        }
        QToolButton#ConfigSubsectionToggle:hover {
            color: #5D5149;
        }
        QLabel#ConfigGroupTitle {
            color: #756962;
            font-size: 15px;
            font-weight: 600;
        }
        QLabel#ConfigMutedHint {
            color: #9F948D;
            font-size: 15px;
        }
        QFrame#ConfigSensorTableFrame {
            background: #FAFBFD;
            border: 1px solid #EEF2F6;
            border-radius: 12px;
        }
        QFrame#ConfigSensorRow,
        QFrame#ConfigCompactNotice {
            background: #FFFFFF;
            border: 1px solid #EEF1F5;
            border-radius: 10px;
        }
        QLabel#ConfigCollectionHeader {
            color: #978A82;
            font-size: 14px;
            font-weight: 700;
        }
        QLabel#ConfigCollectionText {
            color: #5A4C44;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#ConfigLiveValueLabel {
            background: #FFF0E0;
            color: #A15B1D;
            border: 1px solid #F3D2AF;
            border-radius: 8px;
            padding: 4px 6px;
            font-size: 14px;
            font-weight: 600;
        }
        QFrame#ConfigListItemFrame {
            background: #FFFFFF;
            border: 1px solid #E9EDF2;
            border-radius: 10px;
        }
        QLabel#ConfigListItemTitle {
            color: #5A4C44;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#ConfigEmptyLabel {
            color: #9E948D;
            font-size: 15px;
        }
        QFrame#ConfigCompactNotice {
            background: transparent;
            border: none;
        }
        QFrame#WorkspacePanel {
            background: #FFFFFF;
            border: 1px solid #ECEFF4;
            border-radius: 18px;
        }
        QFrame#WorkspacePanel[surfaceTone="config"] {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid #EDF1F5;
            border-radius: 14px;
        }
        QLabel#PanelTitle {
            color: #5A4C44;
            font-size: 15px;
            font-weight: 700;
        }
        QLabel#PanelSubtitle {
            color: #A1938A;
            font-size: 15px;
        }
        QLabel#DetailLabel {
            color: #9F948D;
            font-size: 14px;
            font-weight: 600;
        }
        QLabel#FieldLabel {
            color: #A1938A;
            font-size: 14px;
            font-weight: 700;
            text-transform: uppercase;
        }
        QLabel#DetailValue {
            color: #584A42;
            font-size: 14px;
            font-weight: 600;
        }
        QFrame#DetailRow {
            background: #F8FAFC;
            border: 1px solid #EDF1F5;
            border-radius: 16px;
        }
        QFrame#BulletNoteCard,
        QFrame#StatusRow,
        QFrame#SwitchRow {
            background: #F8FAFC;
            border: 1px solid #EDF1F5;
            border-radius: 16px;
        }
        QFrame#MetricCard {
            background: #FFFFFF;
            border: 1px solid #EDF0F4;
            border-radius: 22px;
        }
        QFrame#MetricCard[tone="warning"] {
            background: #FFF9F5;
            border: 1px solid #F3E2D3;
        }
        QFrame#MetricAccent {
            background: #E6EEF8;
            border: none;
            border-radius: 14px;
        }
        QFrame#MetricAccent[tone="warning"] {
            background: #FCE9DA;
        }
        QLabel#MetricLabel {
            color: #9B9088;
            font-size: 14px;
            font-weight: 600;
        }
        QLabel#MetricValue {
            color: #564840;
            font-size: 28px;
            font-weight: 700;
        }
        QLabel#MetricCaption {
            color: #A4978F;
            font-size: 14px;
        }
        QLabel#StatusChip {
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 14px;
            font-weight: 700;
        }
        QLabel#StatusChip[tone="neutral"] {
            background: #EFF2F7;
            color: #6F7783;
        }
        QLabel#StatusChip[tone="success"] {
            background: #E8F7EE;
            color: #3AA56B;
        }
        QLabel#StatusChip[tone="warning"] {
            background: #FFF0E0;
            color: #D98732;
        }
        QLabel#StatusChip[tone="info"] {
            background: #EAF3FF;
            color: #4E86D8;
        }
        QLabel#StatusChip[tone="muted"] {
            background: #F5F6F9;
            color: #8D95A0;
        }
        QFrame#BulletMarkerDot {
            background: #FF9B46;
            border: none;
            border-radius: 4px;
            margin-top: 4px;
        }
        QLabel#BulletBody {
            color: #5C5048;
            font-size: 14px;
        }
        QLabel#StatusRowText,
        QLabel#SwitchLabel {
            color: #594C44;
            font-size: 14px;
        }
        QLineEdit {
            background: #FAFBFD;
            color: #594C44;
            border: 1px solid #E7DCCF;
            border-radius: 9px;
            padding: 5px 8px;
            min-height: 16px;
            font-size: 14px;
        }
        QPushButton#ConfigInlineActionButton {
            border-radius: 10px;
            font-size: 13px;
            padding: 5px 10px;
        }
        QPushButton#SelectorOptionButton {
            background: #F9FBFD;
            color: #594C44;
            border: 1px solid #E7DCCF;
            border-radius: 14px;
            padding: 8px 10px;
            text-align: left;
        }
        QPushButton#SelectorOptionButton:hover {
            background: #FFF8F1;
            border: 1px solid #EACDB7;
        }
        QPushButton#SelectorOptionButton:checked {
            background: #FFF1E5;
            color: #9D5A25;
            border: 1px solid #F1CCAE;
        }
        QPushButton#SelectorOptionButton[selectorVariant="list"] {
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            min-height: 34px;
            max-height: 34px;
            padding: 4px 10px;
        }
        QScrollArea#VisibleSelectorScroll {
            background: transparent;
            border: none;
        }
        QWidget#VisibleSelectorViewport {
            background: transparent;
        }
        QScrollBar:vertical {
            background: transparent;
            width: 8px;
            margin: 4px 0 4px 0;
        }
        QScrollBar::handle:vertical {
            background: #D8DEE8;
            border-radius: 4px;
            min-height: 28px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            border: none;
            background: transparent;
            height: 0px;
        }
        QListWidget,
        QTableWidget#SimpleTableWidget {
            background: #FCF8F4;
            color: #594C44;
            border: 1px solid #F0E3D6;
            border-radius: 18px;
            padding: 6px;
        }
        QListWidget::item {
            padding: 8px 10px;
            border-bottom: 1px solid #F1E8E0;
        }
        QTableWidget#SimpleTableWidget::item {
            padding: 8px 10px;
            border-bottom: 1px solid #F1E8E0;
        }
        QHeaderView::section {
            background: #FCEEDC;
            color: #8A735F;
            border: none;
            border-radius: 10px;
            padding: 8px 10px;
            font-size: 11px;
            font-weight: 700;
        }
        QProgressBar {
            background: #F6EEE7;
            border: none;
            border-radius: 8px;
            min-height: 10px;
        }
        QProgressBar::chunk {
            background: #FF9633;
            border-radius: 8px;
        }
        QCheckBox#SwitchToggle {
            spacing: 0px;
        }
        QCheckBox#SwitchToggle::indicator {
            width: 38px;
            height: 22px;
            border-radius: 11px;
            background: #E7F4EC;
            border: 1px solid #DBE8E1;
        }
        QCheckBox#SwitchToggle::indicator:unchecked {
            background: #F1ECE8;
            border: 1px solid #E4DCD5;
        }
        QCheckBox#SwitchToggle::indicator:checked {
            background: #E4F5EA;
            border: 1px solid #D2EAD9;
        }
        QPushButton:disabled {
            background: #F7F3EF;
            color: #AA9F97;
            border: 1px solid #E8E1DA;
        }
        QPushButton#ConsoleSaveButton,
        QPushButton#ConsoleClearButton {
            border-radius: 12px;
            font-size: 12px;
            padding: 8px 12px;
        }
        QScrollArea#WorkspacePage {
            background: transparent;
            border: none;
        }
        """
