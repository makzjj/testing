"""Data-only node motion calibration model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeMotionCalibration:
    """Machine-specific motion reference values for one node."""

    node_id: int
    node_name: str
    axis_type: str
    unit: str
    software_range: float
    counts_per_unit: float

    @property
    def expected_range_counts(self) -> float:
        return float(self.software_range) * abs(float(self.counts_per_unit))
