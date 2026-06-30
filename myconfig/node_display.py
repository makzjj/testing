"""Shared ML 2.0 node display helpers."""

from __future__ import annotations

ML20_NODE_MAP: dict[int, str] = {
    1: "MCU Master",
    3: "X",
    4: "Y",
    5: "V",
    6: "H",
    7: "NZ",
    8: "RZ",
    9: "PZ",
    10: "HMI",
    11: "NGActuator",
    12: "Z",
}


def get_ml20_node_name(node_id: int | None) -> str | None:
    """Return the ML 2.0 display name for one node id."""
    if node_id is None:
        return None
    try:
        return ML20_NODE_MAP.get(int(node_id))
    except (TypeError, ValueError):
        return None


def format_node_display(node_id: int | None) -> str:
    """Return a company-style node tag such as [N6:H]."""
    if node_id is None:
        return "[N?:?]"
    try:
        resolved_node_id = int(node_id)
    except (TypeError, ValueError):
        return "[N?:?]"
    node_name = get_ml20_node_name(resolved_node_id)
    return f"[N{resolved_node_id}:{node_name if node_name is not None else '?'}]"
