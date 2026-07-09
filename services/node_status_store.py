"""Reusable node-status helpers shared by legacy and future UI layers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

DEFAULT_NODE_IDS = range(2, 17)
MOTOR_CURRENT_SAMPLE_LIMIT = 300


def build_default_node_state() -> dict[str, Any]:
    """Create one default node status record."""
    return {
        "connected": False,
        "response_time": 0,
        "firmware": "",
        "uuid": "",
        "type": "",
        "interrupt": "",
        "interrupt_state": build_default_interrupt_state(),
        "motor_current": build_default_motor_current_state(),
    }


def build_default_interrupt_state() -> dict[str, Any]:
    """Create the canonical runtime interrupt-state record for one node."""
    return {
        "int0": None,
        "int1": None,
        "left_cut": None,
        "right_cut": None,
        "last_source": None,
    }


def build_default_motor_current_state() -> dict[str, Any]:
    """Create the canonical runtime motor-current record for one node."""
    return {
        "latest_mA": None,
        "samples": [],
        "last_updated": None,
        "next_index": 0,
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


def ensure_motor_current_state(node_record: dict[str, Any]) -> dict[str, Any]:
    """Return one node's canonical runtime motor-current record."""
    motor_current = node_record.get("motor_current")
    if not isinstance(motor_current, dict):
        motor_current = build_default_motor_current_state()
        node_record["motor_current"] = motor_current
        return motor_current

    samples = motor_current.get("samples")
    if not isinstance(samples, list):
        motor_current["samples"] = []
    if not isinstance(motor_current.get("next_index"), int):
        motor_current["next_index"] = int(motor_current.get("last_updated") or 0)
    return motor_current


def append_motor_current_sample(node_record: dict[str, Any], current_mA: int) -> dict[str, Any]:
    """Append one bounded runtime motor-current sample for a node."""
    motor_current = ensure_motor_current_state(node_record)
    next_index = int(motor_current.get("next_index", 0)) + 1
    sample = {
        "index": next_index,
        "current_mA": int(current_mA),
    }
    samples = motor_current["samples"]
    if not isinstance(samples, list):
        samples = []
        motor_current["samples"] = samples
    samples.append(sample)
    if len(samples) > MOTOR_CURRENT_SAMPLE_LIMIT:
        del samples[:-MOTOR_CURRENT_SAMPLE_LIMIT]
    motor_current["latest_mA"] = int(current_mA)
    motor_current["last_updated"] = next_index
    motor_current["next_index"] = next_index
    return motor_current
