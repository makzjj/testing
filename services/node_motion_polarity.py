"""Canonical NODECONFIG-driven motion polarity model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SensorName = Literal["L", "R"]


def _opposite_sensor(sensor: SensorName) -> SensorName:
    return "L" if sensor == "R" else "R"


@dataclass(frozen=True)
class NodeMotionPolarity:
    """Resolved motion polarity for one node."""

    nodeconfig_raw: int
    home_sensor: SensorName
    opposite_sensor: SensorName
    hunting_sign: int
    outward_sign: int
    return_home_sign: int
    negative_run_sensor: SensorName
    positive_run_sensor: SensorName

    @classmethod
    def from_nodeconfig(cls, raw_value: int, *, allow_unvalidated: bool = False) -> "NodeMotionPolarity":
        """Build the motion model from raw NODECONFIG bits.

        Safety policy:
        - bit0 selects the home sensor
        - bit1 selects the hunting sign
        - only 0x00 and 0x02 are currently validated for live motion
        - 0x01 and 0x03 are derivable but remain blocked until validated on real hardware
        """
        raw = int(raw_value) & 0xFF
        home_sensor: SensorName = "R" if raw & 0x01 else "L"
        hunting_sign = 1 if raw & 0x02 else -1
        opposite_sensor = _opposite_sensor(home_sensor)
        outward_sign = -hunting_sign
        return_home_sign = hunting_sign
        negative_run_sensor = home_sensor if hunting_sign < 0 else opposite_sensor
        positive_run_sensor = opposite_sensor if hunting_sign < 0 else home_sensor

        model = cls(
            nodeconfig_raw=raw,
            home_sensor=home_sensor,
            opposite_sensor=opposite_sensor,
            hunting_sign=hunting_sign,
            outward_sign=outward_sign,
            return_home_sign=return_home_sign,
            negative_run_sensor=negative_run_sensor,
            positive_run_sensor=positive_run_sensor,
        )

        if allow_unvalidated or raw in {0x00, 0x02}:
            return model
        raise ValueError(f"Unsupported or missing NODECONFIG 0x{raw:02X}. Motion blocked for safety.")

    def sign_to_sensor(self, sign: int) -> SensorName:
        return self.positive_run_sensor if int(sign) > 0 else self.negative_run_sensor

    def sign_to_home(self) -> int:
        return self.return_home_sign

    def sign_to_opposite(self) -> int:
        return self.outward_sign

    def format_motion_summary(self) -> str:
        """Return a concise human-readable summary for logs."""
        return (
            f"home sensor: {self.home_sensor}\n"
            f"  opposite sensor: {self.opposite_sensor}\n"
            f"  HUNT sign: {self._format_sign(self.hunting_sign)}\n"
            f"  outward RUN sign: {self._format_sign(self.outward_sign)}\n"
            f"  return RUN sign: {self._format_sign(self.return_home_sign)}"
        )

    @staticmethod
    def _format_sign(value: int) -> str:
        return "+" if int(value) > 0 else "-"
