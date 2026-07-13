"""Reusable backend services for the BioBot tester platform."""

__all__ = [
    "RobotBackendClient",
    "CommunicationLogStore",
    "FirmwareTransportAdapter",
    "RuntimePacketEvent",
    "RuntimePacketHandler",
    "ReleaseWatchHelper",
    "RxLogWriter",
    "SamplingTransportAdapter",
    "build_default_node_status",
    "connected_node_ids",
    "ensure_node_status",
    "NodeDiscoveryCoordinator",
    "reset_node_status",
]


def __getattr__(name: str):
    """Keep lightweight services importable without GUI/runtime dependencies."""
    if name == "RobotBackendClient":
        from .robot_backend_client import RobotBackendClient

        return RobotBackendClient
    if name == "CommunicationLogStore":
        from .communication_log_store import CommunicationLogStore

        return CommunicationLogStore
    if name == "FirmwareTransportAdapter":
        from .firmware_transport_adapter import FirmwareTransportAdapter

        return FirmwareTransportAdapter
    if name == "RuntimePacketEvent":
        from .runtime_packet_handler import RuntimePacketEvent

        return RuntimePacketEvent
    if name == "RuntimePacketHandler":
        from .runtime_packet_handler import RuntimePacketHandler

        return RuntimePacketHandler
    if name == "ReleaseWatchHelper":
        from .release_watch_helper import ReleaseWatchHelper

        return ReleaseWatchHelper
    if name == "RxLogWriter":
        from .rx_log_writer import RxLogWriter

        return RxLogWriter
    if name == "SamplingTransportAdapter":
        from .sampling_transport_adapter import SamplingTransportAdapter

        return SamplingTransportAdapter
    if name == "build_default_node_status":
        from .node_status_store import build_default_node_status

        return build_default_node_status
    if name == "connected_node_ids":
        from .node_status_store import connected_node_ids

        return connected_node_ids
    if name == "ensure_node_status":
        from .node_status_store import ensure_node_status

        return ensure_node_status
    if name == "NodeDiscoveryCoordinator":
        from .node_discovery_coordinator import NodeDiscoveryCoordinator

        return NodeDiscoveryCoordinator
    if name == "reset_node_status":
        from .node_status_store import reset_node_status

        return reset_node_status
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
