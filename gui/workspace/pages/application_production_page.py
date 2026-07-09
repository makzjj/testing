"""Plots page hosted on the legacy Application route."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QPushButton

from data.binary_cmd_builders import build_motor_current_query_payload
from ..bridges import WorkspaceRuntimeBridge
from ..dialogs import MotorCurrentPlotDialog
from ..widgets import PanelFrame
from .base_page import BaseWorkspacePage


class PlotsPage(BaseWorkspacePage):
    """Plots page scaffold plus live Motor Current plot launch wiring."""

    console_message = pyqtSignal(str)
    action_requested = pyqtSignal(str)

    def __init__(self, bridge: WorkspaceRuntimeBridge) -> None:
        super().__init__("Plots", "")
        self._bridge = bridge
        self._motor_current_dialog: MotorCurrentPlotDialog | None = None

        self.plot_actions_section = PanelFrame("Plots", "")

        self.motor_current_button = QPushButton("Open Motor Current Plot")
        self.motor_current_button.setProperty("tone", "primary")
        self.motor_current_button.clicked.connect(self._handle_open_motor_current_plot)
        self.plot_actions_section.body_layout.addWidget(self.motor_current_button)

        self.future_plots_section = PanelFrame("Future Plots", "Additional diagnostic views will be added here.")
        self.motor_torque_button = QPushButton("Motor Torque")
        self.motor_speed_button = QPushButton("Motor Speed")
        self.encoder_position_button = QPushButton("Encoder Position")
        for button in (self.motor_torque_button, self.motor_speed_button, self.encoder_position_button):
            button.setEnabled(False)
            self.future_plots_section.body_layout.addWidget(button)

        self.add_row(self.plot_actions_section, self.future_plots_section)

    def refresh(self) -> None:
        if self._motor_current_dialog is not None:
            self._motor_current_dialog.sync_selected_node_from_provider()
            self._motor_current_dialog.refresh_display()

    def _handle_open_motor_current_plot(self) -> None:
        dialog = self._ensure_motor_current_dialog()
        dialog.sync_selected_node_from_provider()
        dialog.refresh_display()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _ensure_motor_current_dialog(self) -> MotorCurrentPlotDialog:
        if self._motor_current_dialog is None:
            self._motor_current_dialog = MotorCurrentPlotDialog(
                self._bridge,
                node_provider=self._default_plot_node_context,
                send_query=self._send_motor_current_query,
                query_payload_builder=build_motor_current_query_payload,
                parent=self,
            )
        return self._motor_current_dialog

    def _default_plot_node_context(self) -> tuple[int | None, str]:
        options = self._bridge.get_plot_node_options(create_if_missing=False)
        if not options:
            return None, "Unknown"
        node_id, node_label = options[0]
        return int(node_id), str(node_label)

    def _send_motor_current_query(self, node_id: int, payload: list[int]) -> None:
        runtime_window = self._bridge.get_runtime_window(create_if_missing=False)
        if runtime_window is None:
            raise RuntimeError("Runtime backend is unavailable.")

        backend_client = getattr(runtime_window, "backend_client", None)
        if backend_client is None or not hasattr(backend_client, "send_command_bytes"):
            raise RuntimeError("Runtime transport does not expose CAN-over-UART send capability.")
        if hasattr(backend_client, "is_connected") and not backend_client.is_connected():
            raise RuntimeError("Runtime transport is not connected.")
        backend_client.send_command_bytes(int(node_id), list(payload))


# Keep the legacy import surface stable while the route/file name remains unchanged.
ApplicationProductionPage = PlotsPage
