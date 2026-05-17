"""Reusable backend services for the BioBot tester platform."""

from .node_status_store import build_default_node_status, connected_node_ids, ensure_node_status, reset_node_status
from .runtime_packet_handler import RuntimePacketEvent, RuntimePacketHandler
from .rx_log_writer import RxLogWriter

__all__ = [
    "RobotBackendClient",
    "RuntimePacketEvent",
    "RuntimePacketHandler",
    "RxLogWriter",
    "build_default_node_status",
    "connected_node_ids",
    "ensure_node_status",
    "reset_node_status",
]


def __getattr__(name: str):
    """Keep lightweight services importable without GUI/runtime dependencies."""
    if name == "RobotBackendClient":
        from .robot_backend_client import RobotBackendClient

        return RobotBackendClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
