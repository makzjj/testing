"""Mismatch-only live hardware overlay helpers for the Project Config page."""

from __future__ import annotations

import logging

from myconfig.config_models import LiveHardwareFieldValue
from myconfig.config_schema_adapter import ConfigSchemaAdapter

from .legacy_runtime_launcher import LegacyRuntimeLauncher


logger = logging.getLogger("gui.workspace.bridges.live_hardware_overlay_provider")


class LiveHardwareOverlayProvider:
    """Reads current runtime state and emits read-only mismatch overlays."""

    def __init__(
        self,
        runtime_launcher: LegacyRuntimeLauncher,
        adapter: ConfigSchemaAdapter | None = None,
    ) -> None:
        self._runtime_launcher = runtime_launcher
        self._adapter = adapter or ConfigSchemaAdapter()

    def collect_live_values(self, raw_config: dict) -> list[LiveHardwareFieldValue]:
        """Collect only the live hardware values that differ from YAML."""
        # 1. Read the currently available live runtime values
        runtime_window = self._runtime_launcher.current_window()
        if runtime_window is None:
            return []
        # 2. Compare live values against their YAML-backed config fields
        overlays = self._build_mcu_version_overlay(runtime_window, raw_config)
        overlays.extend(self._build_node_type_overlays(runtime_window, raw_config))
        # 3. Return mismatch-only overlays for UI presentation
        logger.debug("Collected %d live hardware overlay(s)", len(overlays))
        return overlays

    def _build_mcu_version_overlay(self, runtime_window, raw_config: dict) -> list[LiveHardwareFieldValue]:
        logger.debug("Checking MCU version mismatch overlay")
        live_value = getattr(runtime_window, "mcu_version", None)
        if live_value in (None, "", "Unknown"):
            return []

        yaml_value = self._adapter.lookup_first(
            raw_config,
            [
                ("mcu configuration", "firmware version"),
                ("mcu", "firmware_version"),
            ],
        )
        if yaml_value is None:
            return []

        overlay_path = ("mcu configuration", "firmware version")
        if self._adapter.lookup_path(raw_config, overlay_path, default=None) is None:
            overlay_path = ("mcu", "firmware_version")

        yaml_text = str(yaml_value).strip()
        live_text = str(live_value).strip()
        if live_text == yaml_text:
            return []

        return [
            LiveHardwareFieldValue(
                path=overlay_path,
                label="MCU Version",
                yaml_value=yaml_value,
                live_value=live_text,
                display_text=f"Actual: MCU Version = {live_text}",
            )
        ]

    def _build_node_type_overlays(self, runtime_window, raw_config: dict) -> list[LiveHardwareFieldValue]:
        logger.debug("Checking node type mismatch overlays")
        node_status = getattr(runtime_window, "node_status", None)
        if not isinstance(node_status, dict):
            return []

        overlays: list[LiveHardwareFieldValue] = []
        for axis_name, axis_config in self._adapter.extract_axis_section(raw_config).items():
            if not isinstance(axis_config, dict):
                continue

            node_id = axis_config.get("node_id")
            if not isinstance(node_id, int):
                try:
                    node_id = int(node_id)
                except (TypeError, ValueError):
                    continue

            runtime_record = node_status.get(node_id)
            if not isinstance(runtime_record, dict):
                continue

            live_value = runtime_record.get("type")
            if live_value in (None, "", "Unknown"):
                continue

            yaml_value = axis_config.get("node_type")
            if yaml_value is None:
                continue

            yaml_text = str(yaml_value).strip()
            live_text = str(live_value).strip()
            if live_text == yaml_text:
                continue

            overlay_path = ("robot arm configuration", "axes", axis_name, "node_type")
            if self._adapter.lookup_path(raw_config, overlay_path, default=None) is None:
                overlay_path = ("robot", "axes", axis_name, "node_type")

            overlays.append(
                LiveHardwareFieldValue(
                    path=overlay_path,
                    label=f"{axis_name.upper()} Node Type",
                    yaml_value=yaml_value,
                    live_value=live_text,
                    display_text=f"Actual: {axis_name.upper()} Node Type = {live_text}",
                )
            )

        return overlays
