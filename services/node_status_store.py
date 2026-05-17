"""Reusable node-status helpers shared by legacy and future UI layers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DEFAULT_NODE_IDS = range(2, 17)


def build_default_node_state() -> dict[str, Any]:
    """Create one default node status record."""
    return {
        "connected": False,
        "response_time": 0,
        "firmware": "",
        "uuid": "",
        "type": "",
        "interrupt": "",
        "info_requested": False,
    }


def build_default_node_status(node_ids: Iterable[int] = DEFAULT_NODE_IDS) -> dict[int, dict[str, Any]]:
    """Create the default node-status map used by runtime UIs."""
    return {node_id: build_default_node_state() for node_id in node_ids}


def ensure_node_status(node_status: dict[int, dict[str, Any]], node_id: int) -> dict[str, Any]:
    """Return an existing node record or create one with the standard shape."""
    if node_id not in node_status:
        node_status[node_id] = build_default_node_state()
    return node_status[node_id]


def reset_node_status(node_status: dict[int, dict[str, Any]], node_ids: Iterable[int] = DEFAULT_NODE_IDS) -> None:
    """Reset known node records in-place while preserving external references."""
    node_status.clear()
    node_status.update(build_default_node_status(node_ids))


def connected_node_ids(node_status: dict[int, dict[str, Any]]) -> list[int]:
    """Return connected node ids in stable order."""
    return sorted(node_id for node_id, status in node_status.items() if status.get("connected", False))
