"""Narrow ingress boundary placeholder for future Firmware Integration packets."""

from __future__ import annotations

try:
    from PyQt6.QtCore import QObject
except Exception:  # pragma: no cover - fallback type for non-GUI environments
    class QObject:  # type: ignore
        pass


class FirmwareTransportAdapter(QObject):
    """Inert scaffold for future firmware workflow packet filtering."""

    def __init__(self, controller: object) -> None:
        super().__init__()
        self._controller = controller
        self._runtime_packet_source: object | None = None
        self._attached = False

    @property
    def is_attached(self) -> bool:
        return self._attached

    @property
    def runtime_packet_source(self) -> object | None:
        return self._runtime_packet_source

    def attach(self, runtime_packet_source: object | None) -> None:
        """Remember the future runtime packet source without subscribing yet."""
        self._runtime_packet_source = runtime_packet_source
        self._attached = runtime_packet_source is not None

    def detach(self) -> None:
        self._runtime_packet_source = None
        self._attached = False

    def handle_packet(self, packet: object) -> None:
        """Placeholder packet entrypoint for future filtering."""
        _ = packet
