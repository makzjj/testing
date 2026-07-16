"""XML-backed store for machine-specific node motion calibration values."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from gui.workspace.models.node_motion_calibration import NodeMotionCalibration
from utils.deployment_paths import get_bundle_resource_path


_SUPPORTED_AXIS_UNITS = {
    "Linear": "mm",
    "Rotational": "deg",
}


class NodeMotionCalibrationStore:
    """Load, validate, and expose read-only node motion calibration records."""

    def __init__(self, calibrations: Iterable[NodeMotionCalibration], source_path: Path) -> None:
        self._source_path = Path(source_path).resolve()
        indexed: dict[int, NodeMotionCalibration] = {}
        for calibration in calibrations:
            indexed[int(calibration.node_id)] = calibration
        self._calibrations_by_node_id = indexed

    @classmethod
    def default_path(cls) -> Path:
        return get_bundle_resource_path("config", "node_motion_calibration.xml").resolve()

    @classmethod
    def load_default(cls) -> "NodeMotionCalibrationStore":
        return cls.load(cls.default_path())

    @classmethod
    def load(cls, path: str | Path) -> "NodeMotionCalibrationStore":
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Node motion calibration XML file does not exist: {source_path}")

        try:
            tree = ElementTree.parse(source_path)
        except ElementTree.ParseError as exc:
            raise ValueError(f"Malformed node motion calibration XML in {source_path}: {exc}") from exc

        root = tree.getroot()
        if root.tag != "NodeMotionCalibration":
            raise ValueError(
                f"Invalid node motion calibration XML in {source_path}: expected root "
                f"'NodeMotionCalibration', got '{root.tag}'."
            )
        if str(root.attrib.get("version", "")).strip() != "1":
            raise ValueError(
                f"Invalid node motion calibration XML in {source_path}: unsupported version "
                f"'{root.attrib.get('version', '')}'."
            )

        calibrations: list[NodeMotionCalibration] = []
        seen_node_ids: set[int] = set()
        seen_node_names: set[str] = set()

        for node_element in root.findall("Node"):
            calibration = cls._parse_node(source_path, node_element)
            if calibration.node_id in seen_node_ids:
                raise ValueError(
                    f"Duplicate node ID {calibration.node_id} in node motion calibration XML file {source_path}."
                )
            if calibration.node_name in seen_node_names:
                raise ValueError(
                    f"Duplicate node name '{calibration.node_name}' in node motion calibration XML file {source_path}."
                )
            seen_node_ids.add(calibration.node_id)
            seen_node_names.add(calibration.node_name)
            calibrations.append(calibration)

        return cls(calibrations, source_path)

    @classmethod
    def _parse_node(cls, source_path: Path, node_element: ElementTree.Element) -> NodeMotionCalibration:
        node_id_text = str(node_element.attrib.get("id", "")).strip()
        node_name = str(node_element.attrib.get("name", "")).strip()
        node_label = f"node id={node_id_text or '?'}"
        if node_name:
            node_label = f"Node {node_id_text or '?'} - {node_name}"

        if not node_id_text:
            raise ValueError(f"Missing required node ID in node motion calibration XML file {source_path}.")
        try:
            node_id = int(node_id_text)
        except ValueError as exc:
            raise ValueError(
                f"Invalid node ID '{node_id_text}' in node motion calibration XML file {source_path}."
            ) from exc
        if node_id <= 0:
            raise ValueError(
                f"Invalid node ID '{node_id_text}' in node motion calibration XML file {source_path}: "
                f"node ID must be greater than zero."
            )
        if not node_name:
            raise ValueError(
                f"Missing required node name for Node {node_id} in node motion calibration XML file {source_path}."
            )

        axis_type = cls._require_child_text(source_path, node_element, node_label, "AxisType")
        unit = cls._require_child_text(source_path, node_element, node_label, "Unit")
        software_range = cls._parse_float_field(source_path, node_element, node_label, "SoftwareRange")
        counts_per_unit = cls._parse_float_field(source_path, node_element, node_label, "CountsPerUnit")

        if axis_type not in _SUPPORTED_AXIS_UNITS:
            raise ValueError(
                f"Unsupported AxisType '{axis_type}' for {node_label} in node motion calibration XML file {source_path}."
            )
        if unit not in {"mm", "deg"}:
            raise ValueError(
                f"Unsupported Unit '{unit}' for {node_label} in node motion calibration XML file {source_path}."
            )
        expected_unit = _SUPPORTED_AXIS_UNITS[axis_type]
        if unit != expected_unit:
            raise ValueError(
                f"AxisType '{axis_type}' must use Unit '{expected_unit}' for {node_label} in node motion "
                f"calibration XML file {source_path}."
            )
        if software_range <= 0:
            raise ValueError(
                f"SoftwareRange must be greater than zero for {node_label} in node motion calibration XML file "
                f"{source_path}."
            )
        if counts_per_unit == 0:
            raise ValueError(
                f"CountsPerUnit must not be zero for {node_label} in node motion calibration XML file {source_path}."
            )

        return NodeMotionCalibration(
            node_id=node_id,
            node_name=node_name,
            axis_type=axis_type,
            unit=unit,
            software_range=software_range,
            counts_per_unit=counts_per_unit,
        )

    @staticmethod
    def _require_child_text(
        source_path: Path,
        node_element: ElementTree.Element,
        node_label: str,
        field_name: str,
    ) -> str:
        element = node_element.find(field_name)
        text = "" if element is None or element.text is None else str(element.text).strip()
        if not text:
            raise ValueError(
                f"Missing required field '{field_name}' for {node_label} in node motion calibration XML file "
                f"{source_path}."
            )
        return text

    @classmethod
    def _parse_float_field(
        cls,
        source_path: Path,
        node_element: ElementTree.Element,
        node_label: str,
        field_name: str,
    ) -> float:
        text = cls._require_child_text(source_path, node_element, node_label, field_name)
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(
                f"Malformed numeric value '{text}' for field '{field_name}' on {node_label} in node motion "
                f"calibration XML file {source_path}."
            ) from exc

    @property
    def source_path(self) -> Path:
        return self._source_path

    def get(self, node_id: int) -> NodeMotionCalibration | None:
        return self._calibrations_by_node_id.get(int(node_id))

    def require(self, node_id: int, node_name: str | None = None) -> NodeMotionCalibration:
        calibration = self.get(node_id)
        if calibration is not None:
            return calibration
        if node_name:
            raise LookupError(f"No motion calibration is configured for Node {int(node_id)} - {node_name}.")
        raise LookupError(f"No motion calibration is configured for Node {int(node_id)}.")

    def all_calibrations(self) -> tuple[NodeMotionCalibration, ...]:
        return tuple(self._calibrations_by_node_id.values())
