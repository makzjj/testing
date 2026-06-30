"""Centralized node-specific sensor completion profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SensorName = Literal["L", "R"]

_DUAL_SENSOR_NODE_IDS = {3, 4, 7, 8, 9, 12}
_L_ONLY_SENSOR_NODE_IDS = {5, 6}


def _normalize_sensor_list(values: tuple[SensorName, ...]) -> tuple[SensorName, ...]:
    if not values:
        raise ValueError("Sensor profile must define at least one sensor.")
    normalized = tuple("R" if str(value).strip().upper() == "R" else "L" for value in values)
    return normalized


@dataclass(frozen=True)
class NodeSensorProfile:
    """Resolved sensor-event expectations for one node."""

    node_id: int
    hunting_completion_sensors: tuple[SensorName, ...]
    outward_completion_sensors: tuple[SensorName, ...]
    return_completion_sensors: tuple[SensorName, ...]
    profile_name: str

    @classmethod
    def from_node_context(
        cls,
        node_id: int,
        motion_polarity,
    ) -> "NodeSensorProfile":
        node = int(node_id)
        if node in _L_ONLY_SENSOR_NODE_IDS:
            return cls(
                node_id=node,
                hunting_completion_sensors=("L",),
                outward_completion_sensors=("L",),
                return_completion_sensors=("L",),
                profile_name="single_sensor_l",
            )
        if node in _DUAL_SENSOR_NODE_IDS:
            home_sensor = motion_polarity.home_sensor
            opposite_sensor = motion_polarity.opposite_sensor
            return cls(
                node_id=node,
                hunting_completion_sensors=_normalize_sensor_list((home_sensor,)),
                outward_completion_sensors=_normalize_sensor_list((opposite_sensor,)),
                return_completion_sensors=_normalize_sensor_list((home_sensor,)),
                profile_name="dual_sensor_home_opposite",
            )
        raise ValueError(f"Unsupported or missing node sensor profile for Node {node}. Motion blocked for safety.")

    def completion_sensors_for_phase(self, phase: str) -> tuple[SensorName, ...]:
        phase_name = str(phase).strip().lower()
        if phase_name in {"hunt", "hunting", "home"}:
            return self.hunting_completion_sensors
        if phase_name in {"outward", "positive", "forward"}:
            return self.outward_completion_sensors
        if phase_name in {"return", "home_return", "negative"}:
            return self.return_completion_sensors
        raise ValueError(f"Unsupported sensor phase {phase!r}.")

    def completion_sensor_for_phase(self, phase: str) -> SensorName:
        sensors = self.completion_sensors_for_phase(phase)
        if len(sensors) != 1:
            raise ValueError(f"Sensor profile for phase {phase!r} is not singular: {sensors!r}")
        return sensors[0]

    def matches_phase_sensor(self, phase: str, sensor: SensorName) -> bool:
        return sensor in self.completion_sensors_for_phase(phase)

    def format_summary(self) -> str:
        return (
            f"  HUNT completion: {', '.join(self.hunting_completion_sensors)}\n"
            f"  outward completion: {', '.join(self.outward_completion_sensors)}\n"
            f"  return completion: {', '.join(self.return_completion_sensors)}"
        )

