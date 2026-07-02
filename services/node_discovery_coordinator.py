"""Node discovery/info scheduling coordination for legacy runtime migration."""

from __future__ import annotations


class NodeDiscoveryCoordinator:
    """Own one node-info scheduling policy during the legacy runtime phase."""

    def __init__(self) -> None:
        self._cycle_id = 0
        self._scheduled_nodes: set[int] = set()
        self._pending_nodes: set[int] = set()

    def begin_cycle(self) -> int:
        """Start a fresh discovery cycle and clear prior scheduling state."""
        self._cycle_id += 1
        self._scheduled_nodes.clear()
        self._pending_nodes.clear()
        return self._cycle_id

    def reset(self) -> None:
        """Drop all scheduling state when discovery is torn down."""
        self._cycle_id = 0
        self._scheduled_nodes.clear()
        self._pending_nodes.clear()

    def request_node_info_once(self, node_id: int) -> bool:
        """Return True only for the first node-info schedule in the current cycle."""
        node_id = int(node_id)
        if node_id in self._scheduled_nodes:
            return False
        self._scheduled_nodes.add(node_id)
        self._pending_nodes.add(node_id)
        return True

    def mark_dispatch_started(self, node_id: int) -> None:
        """Clear transient pending state once the scheduled dispatch begins."""
        self._pending_nodes.discard(int(node_id))

    def is_pending(self, node_id: int) -> bool:
        return int(node_id) in self._pending_nodes

    def scheduled_nodes(self) -> set[int]:
        return set(self._scheduled_nodes)

    @property
    def cycle_id(self) -> int:
        return self._cycle_id
