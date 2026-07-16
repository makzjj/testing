"""Focused tests for node motion calibration XML loading and ownership boundaries."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
import re
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import main as app_main

from gui.workspace.bridges.workspace_runtime_bridge import WorkspaceRuntimeBridge
from gui.workspace.models.node_motion_calibration import NodeMotionCalibration
from myconfig.project_models import ProjectDefinition
from services.node_motion_calibration_store import NodeMotionCalibrationStore


def _xml_document(nodes: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<NodeMotionCalibration version="1">\n'
        f"{nodes}\n"
        "</NodeMotionCalibration>\n"
    )


def _node_entry(
    *,
    node_id: str = "3",
    node_name: str = "X",
    axis_type: str = "Linear",
    unit: str = "mm",
    software_range: str = "32",
    counts_per_unit: str = "88064",
) -> str:
    return dedent(
        f"""
        <Node id="{node_id}" name="{node_name}">
            <AxisType>{axis_type}</AxisType>
            <Unit>{unit}</Unit>
            <SoftwareRange>{software_range}</SoftwareRange>
            <CountsPerUnit>{counts_per_unit}</CountsPerUnit>
        </Node>
        """
    ).strip()


class NodeMotionCalibrationModelTests(unittest.TestCase):
    def test_model_is_immutable_qt_independent_data_only(self) -> None:
        calibration = NodeMotionCalibration(
            node_id=3,
            node_name="X",
            axis_type="Linear",
            unit="mm",
            software_range=32.0,
            counts_per_unit=88064.0,
        )

        self.assertEqual(
            [field.name for field in fields(NodeMotionCalibration)],
            ["node_id", "node_name", "axis_type", "unit", "software_range", "counts_per_unit"],
        )
        self.assertAlmostEqual(calibration.expected_range_counts, 32.0 * 88064.0)
        with self.assertRaises(FrozenInstanceError):
            calibration.node_id = 4  # type: ignore[misc]

        source = Path("gui/workspace/models/node_motion_calibration.py").read_text(encoding="utf-8")
        self.assertNotIn("PyQt6", source)
        self.assertNotIn("ElementTree", source)


class NodeMotionCalibrationStoreTests(unittest.TestCase):
    def test_default_calibration_file_exists_and_loads_all_supplied_nodes(self) -> None:
        default_path = NodeMotionCalibrationStore.default_path()
        self.assertTrue(default_path.exists(), str(default_path))

        store = NodeMotionCalibrationStore.load_default()
        calibrations = store.all_calibrations()

        self.assertEqual(store.source_path, default_path)
        self.assertEqual(len(calibrations), 8)
        self.assertEqual([(item.node_id, item.node_name) for item in calibrations], [
            (3, "X"),
            (4, "Y"),
            (5, "V"),
            (6, "H"),
            (7, "NZ"),
            (8, "RZ"),
            (9, "PZ"),
            (12, "Z"),
        ])
        self.assertEqual(store.require(3).axis_type, "Linear")
        self.assertEqual(store.require(4).unit, "mm")
        self.assertEqual(store.require(5).axis_type, "Rotational")
        self.assertEqual(store.require(8).unit, "deg")
        self.assertEqual(store.require(4).software_range, 29.5)
        self.assertEqual(store.require(5).counts_per_unit, -34117.16)
        self.assertEqual(store.require(6).counts_per_unit, -34117.16)
        self.assertEqual(store.require(7).counts_per_unit, -80058.18)

    def test_expected_range_counts_use_absolute_counts_per_unit_without_rounding(self) -> None:
        store = NodeMotionCalibrationStore.load_default()

        self.assertAlmostEqual(store.require(3).expected_range_counts, 32 * 88064)
        self.assertAlmostEqual(store.require(4).expected_range_counts, 29.5 * 88064)
        self.assertAlmostEqual(store.require(5).expected_range_counts, 49 * abs(-34117.16))
        self.assertAlmostEqual(store.require(6).expected_range_counts, 49 * abs(-34117.16))
        self.assertAlmostEqual(store.require(7).expected_range_counts, 69.5 * abs(-80058.18))
        self.assertAlmostEqual(store.require(8).expected_range_counts, 119 * 19569.78)
        self.assertAlmostEqual(store.require(9).expected_range_counts, 168 * 9784.89)
        self.assertAlmostEqual(store.require(12).expected_range_counts, 50 * 88064)

    def test_missing_file_is_reported_clearly(self) -> None:
        missing_path = Path(tempfile.gettempdir()) / "missing_node_motion_calibration.xml"
        if missing_path.exists():
            missing_path.unlink()

        with self.assertRaisesRegex(FileNotFoundError, re.escape(str(missing_path))):
            NodeMotionCalibrationStore.load(missing_path)

    def test_malformed_xml_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "bad.xml"
            xml_path.write_text("<NodeMotionCalibration>", encoding="utf-8")

            with self.assertRaisesRegex(
                ValueError,
                re.escape(f"Malformed node motion calibration XML in {xml_path.resolve()}"),
            ):
                NodeMotionCalibrationStore.load(xml_path)

    def test_validation_rejects_duplicate_node_id(self) -> None:
        self._assert_invalid_xml(
            _xml_document(f"{_node_entry(node_id='3', node_name='X')}\n{_node_entry(node_id='3', node_name='Y')}"),
            "Duplicate node ID 3",
        )

    def test_validation_rejects_duplicate_node_name(self) -> None:
        self._assert_invalid_xml(
            _xml_document(f"{_node_entry(node_id='3', node_name='X')}\n{_node_entry(node_id='4', node_name='X')}"),
            "Duplicate node name 'X'",
        )

    def test_validation_rejects_missing_field(self) -> None:
        self._assert_invalid_xml(
            _xml_document(
                _node_entry().replace("<CountsPerUnit>88064</CountsPerUnit>", "")
            ),
            "Missing required field 'CountsPerUnit'",
        )

    def test_validation_rejects_invalid_node_id(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(node_id="abc")),
            "Invalid node ID 'abc'",
        )

    def test_validation_rejects_unsupported_axis_type(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(axis_type="Spline")),
            "Unsupported AxisType 'Spline'",
        )

    def test_validation_rejects_unsupported_unit(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(unit="rad")),
            "Unsupported Unit 'rad'",
        )

    def test_validation_rejects_linear_deg_mismatch(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(axis_type="Linear", unit="deg")),
            "AxisType 'Linear' must use Unit 'mm'",
        )

    def test_validation_rejects_rotational_mm_mismatch(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(axis_type="Rotational", unit="mm")),
            "AxisType 'Rotational' must use Unit 'deg'",
        )

    def test_validation_rejects_zero_software_range(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(software_range="0")),
            "SoftwareRange must be greater than zero",
        )

    def test_validation_rejects_negative_software_range(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(software_range="-1")),
            "SoftwareRange must be greater than zero",
        )

    def test_validation_rejects_zero_counts_per_unit(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(counts_per_unit="0")),
            "CountsPerUnit must not be zero",
        )

    def test_validation_rejects_malformed_numeric_values(self) -> None:
        self._assert_invalid_xml(
            _xml_document(_node_entry(software_range="not-a-number")),
            "Malformed numeric value 'not-a-number' for field 'SoftwareRange'",
        )

    def test_negative_counts_per_unit_are_accepted_and_preserved(self) -> None:
        xml = _xml_document(_node_entry(node_id="7", node_name="NZ", counts_per_unit="-80058.18", software_range="69.5"))

        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "negative_counts.xml"
            xml_path.write_text(xml, encoding="utf-8")
            store = NodeMotionCalibrationStore.load(xml_path)

        calibration = store.require(7)
        self.assertEqual(calibration.counts_per_unit, -80058.18)
        self.assertAlmostEqual(calibration.expected_range_counts, 69.5 * abs(-80058.18))

    def test_missing_node_lookup_fails_clearly(self) -> None:
        store = NodeMotionCalibrationStore.load_default()

        self.assertIsNone(store.get(11))
        with self.assertRaisesRegex(LookupError, "No motion calibration is configured for Node 11."):
            store.require(11)
        with self.assertRaisesRegex(LookupError, "No motion calibration is configured for Node 11 - NGActuator."):
            store.require(11, "NGActuator")

    def test_load_default_uses_existing_bundle_path_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "node_motion_calibration.xml"
            xml_path.write_text(_xml_document(_node_entry()), encoding="utf-8")

            with patch("services.node_motion_calibration_store.get_bundle_resource_path", return_value=xml_path):
                store = NodeMotionCalibrationStore.load_default()

        self.assertEqual(store.source_path, xml_path.resolve())

    def _assert_invalid_xml(self, xml_text: str, message_fragment: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            xml_path = Path(temp_dir) / "node_motion_calibration.xml"
            xml_path.write_text(xml_text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, message_fragment):
                NodeMotionCalibrationStore.load(xml_path)


class NodeMotionCalibrationArchitectureTests(unittest.TestCase):
    def test_sampling_and_ui_layers_do_not_parse_calibration_xml(self) -> None:
        for relative_path in (
            "gui/workspace/controllers/sampling_test_controller.py",
            "gui/workspace/dialogs/sampling_test_popup.py",
            "gui/workspace/pages/mechanical_page.py",
        ):
            source = Path(relative_path).read_text(encoding="utf-8")
            self.assertNotIn("ElementTree", source, relative_path)
            self.assertNotIn("xml.etree", source, relative_path)
            self.assertNotIn("node_motion_calibration.xml", source, relative_path)
            self.assertNotIn("CountsPerUnit", source, relative_path)
            self.assertNotIn("SoftwareRange", source, relative_path)

    def test_motion_polarity_ownership_remains_separate_from_calibration_store(self) -> None:
        store_source = Path("services/node_motion_calibration_store.py").read_text(encoding="utf-8")
        polarity_source = Path("services/node_motion_polarity.py").read_text(encoding="utf-8")

        self.assertNotIn("node_motion_polarity", store_source)
        self.assertNotIn("node_motion_calibration_store", polarity_source)

    def test_bridge_exposes_injected_calibration_store_without_reowning_lookup_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "demo.yaml"
            config_path.write_text("project:\n  name: demo\n", encoding="utf-8")
            project = ProjectDefinition(name="demo", display_name="Demo", config_path=config_path)
            store = NodeMotionCalibrationStore.load_default()

            bridge = WorkspaceRuntimeBridge(project, node_motion_calibration_store=store)

        self.assertIs(bridge.node_motion_calibration_store, store)


class NodeMotionCalibrationApplicationIntegrationTests(unittest.TestCase):
    def test_main_loads_default_calibration_store_during_startup(self) -> None:
        fake_store = object()
        fake_app = type(
            "FakeApp",
            (),
            {
                "setApplicationName": lambda self, _value: None,
                "setApplicationDisplayName": lambda self, _value: None,
                "setApplicationVersion": lambda self, _value: None,
                "exec": lambda self: 0,
            },
        )()
        fake_window = type(
            "FakeWindow",
            (),
            {
                "move": lambda self, _x, _y: None,
                "show": lambda self: None,
            },
        )()

        with (
            patch.object(app_main, "ensure_runtime_directories"),
            patch.object(app_main.NodeMotionCalibrationStore, "load_default", return_value=fake_store) as load_default,
            patch.object(app_main, "QApplication", return_value=fake_app),
            patch.object(app_main, "ProgramSelectorWindow", return_value=fake_window) as selector_window,
            patch.object(app_main.sys, "exit"),
        ):
            app_main.main()

        load_default.assert_called_once_with()
        selector_window.assert_called_once_with(node_motion_calibration_store=fake_store)


if __name__ == "__main__":
    unittest.main()
