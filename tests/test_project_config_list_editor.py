"""UI tests for repeatable Project Config list editors."""

from __future__ import annotations

import os
import unittest

from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton, QWidget

from gui.workspace.sections.project_config import ConfigSectionPanel
from myconfig.config_models import ConfigFieldModel, ConfigSectionModel


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class ProjectConfigListEditorTests(unittest.TestCase):
    """Verifies list-style config sections render as repeatable editors."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_empty_command_list_uses_clean_empty_state_and_repeatable_controls(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="command list",
                title="command list",
                raw_value_type="list",
                preserve_empty_as_null=True,
                fields=[],
            )
        )

        panel.show()
        self._app.processEvents()

        self.assertIn("No commands configured", [label.text() for label in panel.findChildren(QLabel)])

        add_button = next(button for button in panel.findChildren(QPushButton) if button.text() == "Add Command")
        add_button.click()
        self._app.processEvents()

        line_edit = panel.findChild(QLineEdit)
        self.assertIsNotNone(line_edit)
        line_edit.setText("GET_VERSION")

        self.assertEqual(panel.collect_value(), ["GET_VERSION"])

        remove_button = next(button for button in panel.findChildren(QPushButton) if button.text() == "Remove")
        remove_button.click()
        self._app.processEvents()

        self.assertIsNone(panel.collect_value())
        self.assertIn("No commands configured", [label.text() for label in panel.findChildren(QLabel)])

    def test_command_object_list_renders_and_collects_structured_items(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="command list",
                title="command list",
                raw_value_type="list",
                fields=[
                    ConfigFieldModel(
                        path=("command list", 0),
                        label="Command 1",
                        value=None,
                        value_type="mapping",
                        editable=False,
                        children=[
                            ConfigFieldModel(
                                path=("command list", 0, "name"),
                                label="name",
                                value="GET_VERSION",
                                value_type="string",
                                editable=True,
                            ),
                            ConfigFieldModel(
                                path=("command list", 0, "target"),
                                label="target",
                                value="mcu",
                                value_type="string",
                                editable=True,
                            ),
                        ],
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        self.assertEqual(panel.collect_value(), [{"name": "GET_VERSION", "target": "mcu"}])

        add_button = next(button for button in panel.findChildren(QPushButton) if button.text() == "Add Command")
        add_button.click()
        self._app.processEvents()

        self.assertEqual(
            panel.collect_value(),
            [
                {"name": "GET_VERSION", "target": "mcu"},
                {"name": "", "target": ""},
            ],
        )

    def test_axis_selector_uses_shared_layout_and_keeps_per_axis_values(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="robot arm configuration",
                title="robot arm configuration",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("robot arm configuration", "axes"),
                        label="axes",
                        value=None,
                        value_type="mapping",
                        editable=False,
                        children=[
                            ConfigFieldModel(
                                path=("robot arm configuration", "axes", "ya"),
                                label="ya",
                                value=None,
                                value_type="mapping",
                                editable=False,
                                children=[
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", "ya", "node_id"),
                                        label="node_id",
                                        value=3,
                                        value_type="int",
                                        editable=True,
                                    ),
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", "ya", "node_config"),
                                        label="node_config",
                                        value="02",
                                        value_type="code",
                                        editable=True,
                                    ),
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", "ya", "fw_version"),
                                        label="fw_version",
                                        value=None,
                                        value_type="version",
                                        editable=True,
                                    ),
                                ],
                            ),
                            ConfigFieldModel(
                                path=("robot arm configuration", "axes", "rp"),
                                label="rp",
                                value=None,
                                value_type="mapping",
                                editable=False,
                                children=[
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", "rp", "node_id"),
                                        label="node_id",
                                        value=8,
                                        value_type="int",
                                        editable=True,
                                    ),
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", "rp", "fw_version"),
                                        label="fw_version",
                                        value="0.0.1.6",
                                        value_type="version",
                                        editable=True,
                                    ),
                                ],
                            ),
                        ],
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        axis_selector = panel.findChild(QComboBox, "AxisSelectorCombo")
        self.assertIsNotNone(axis_selector)
        self.assertEqual(axis_selector.count(), 2)
        self.assertEqual(axis_selector.itemText(0), "ya")
        self.assertEqual(axis_selector.itemText(1), "rp")

        axis_editor = next(widget for widget in panel._field_widgets if hasattr(widget, "set_current_axis"))
        scalar_widgets = list(axis_editor.iter_scalar_widgets())
        ya_fw_widget = next(widget for widget in scalar_widgets if widget._field.path[-2:] == ("ya", "fw_version"))
        rp_fw_widget = next(widget for widget in scalar_widgets if widget._field.path[-2:] == ("rp", "fw_version"))
        ya_node_config = next(widget for widget in scalar_widgets if widget._field.path[-2:] == ("ya", "node_config"))
        self.assertEqual(ya_node_config._line_edit.text(), "02")

        axis_editor.set_current_axis("ya")
        self._app.processEvents()
        ya_fw_widget._line_edit.setText("0.0.1.61")
        axis_editor.set_current_axis("rp")
        self._app.processEvents()
        rp_fw_widget._line_edit.setText("0.0.1.62")

        self.assertEqual(
            panel.collect_value(),
            {
                "axes": {
                    "ya": {"node_id": 3, "node_config": "02", "fw_version": "0.0.1.61"},
                    "rp": {"node_id": 8, "fw_version": "0.0.1.62"},
                }
            },
        )

    def test_axis_selector_scales_from_yaml_order_without_hardcoded_axis_list(self) -> None:
        axis_names = ["ya", "yb", "rs", "rp", "rn", "extra_axis"]
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="robot arm configuration",
                title="robot arm configuration",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("robot arm configuration", "axes"),
                        label="axes",
                        value=None,
                        value_type="mapping",
                        editable=False,
                        children=[
                            ConfigFieldModel(
                                path=("robot arm configuration", "axes", axis_name),
                                label=axis_name,
                                value=None,
                                value_type="mapping",
                                editable=False,
                                children=[
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "axes", axis_name, "node_id"),
                                        label="node_id",
                                        value=index + 1,
                                        value_type="int",
                                        editable=True,
                                    ),
                                ],
                            )
                            for index, axis_name in enumerate(axis_names)
                        ],
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        axis_selector = panel.findChild(QComboBox, "AxisSelectorCombo")
        self.assertIsNotNone(axis_selector)
        self.assertEqual([axis_selector.itemText(index) for index in range(axis_selector.count())], axis_names)

    def test_communication_configuration_renders_nested_serial_port_without_null_placeholder(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="communication configuration",
                title="communication configuration",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("communication configuration", "serial_port"),
                        label="serial_port",
                        value=None,
                        value_type="mapping",
                        editable=False,
                        children=[
                            ConfigFieldModel(
                                path=("communication configuration", "serial_port", "name"),
                                label="name",
                                value="COM11",
                                value_type="string",
                                editable=True,
                            ),
                            ConfigFieldModel(
                                path=("communication configuration", "serial_port", "baudrate"),
                                label="baudrate",
                                value=115200,
                                value_type="int",
                                editable=True,
                            ),
                        ],
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        self.assertEqual(
            panel.collect_value(),
            {"serial_port": {"name": "COM11", "baudrate": 115200}},
        )
        self.assertIn("Serial Port", [label.text() for label in panel.findChildren(QLabel)])
        self.assertNotIn("null", [line_edit.text().strip().lower() for line_edit in panel.findChildren(QLineEdit)])

    def test_empty_yaml_scalars_use_clean_not_set_placeholder(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="robot arm configuration",
                title="robot arm configuration",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("robot arm configuration", "sw_range_max"),
                        label="sw_range_max",
                        value=None,
                        value_type="null",
                        editable=True,
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        line_edit = panel.findChild(QLineEdit)
        self.assertIsNotNone(line_edit)
        self.assertEqual(line_edit.text(), "")
        self.assertEqual(line_edit.placeholderText(), "Not set")

    def test_boolean_rows_render_as_standard_checkboxes_without_type_badges(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="features",
                title="features",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("features", "firmware_tools"),
                        label="firmware_tools",
                        value=True,
                        value_type="bool",
                        editable=True,
                    ),
                    ConfigFieldModel(
                        path=("features", "mechanical_tools"),
                        label="mechanical_tools",
                        value=False,
                        value_type="bool",
                        editable=True,
                    ),
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        checkboxes = panel.findChildren(QCheckBox)
        self.assertEqual(len(checkboxes), 2)
        self.assertFalse(any(label.objectName() == "ConfigTypeLabel" for label in panel.findChildren(QLabel)))

    def test_scalar_fields_use_one_stacked_layout_pattern_without_inline_metadata_tags(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="project",
                title="project",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("project", "name"),
                        label="name",
                        value="ACCuESS",
                        value_type="string",
                        editable=True,
                    ),
                    ConfigFieldModel(
                        path=("project", "display_name"),
                        label="display_name",
                        value="ACCuESS",
                        value_type="string",
                        editable=True,
                    ),
                    ConfigFieldModel(
                        path=("project", "config_version"),
                        label="config_version",
                        value="0.0.0.1",
                        value_type="version",
                        editable=True,
                    ),
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        scalar_widgets = [widget for widget in panel._field_widgets if getattr(widget, "_line_edit", None) is not None]
        self.assertEqual(len(scalar_widgets), 3)
        self.assertTrue(all(widget._uses_stacked_control for widget in scalar_widgets))
        self.assertFalse(any(label.objectName() == "ConfigInlineHint" for label in panel.findChildren(QLabel)))

    def test_sensor_rows_render_as_compact_table_like_rows(self) -> None:
        panel = ConfigSectionPanel(
            ConfigSectionModel(
                section_key="robot arm configuration",
                title="robot arm configuration",
                raw_value_type="mapping",
                fields=[
                    ConfigFieldModel(
                        path=("robot arm configuration", "sensors"),
                        label="sensors",
                        value=None,
                        value_type="mapping",
                        editable=False,
                        children=[
                            ConfigFieldModel(
                                path=("robot arm configuration", "sensors", "tof"),
                                label="tof",
                                value=None,
                                value_type="mapping",
                                editable=False,
                                children=[
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "sensors", "tof", "node_id"),
                                        label="node_id",
                                        value=9,
                                        value_type="int",
                                        editable=True,
                                    ),
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "sensors", "tof", "reverse"),
                                        label="reverse",
                                        value=True,
                                        value_type="bool",
                                        editable=True,
                                    ),
                                ],
                            ),
                            ConfigFieldModel(
                                path=("robot arm configuration", "sensors", "zposs"),
                                label="zposs",
                                value=None,
                                value_type="mapping",
                                editable=False,
                                children=[
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "sensors", "zposs", "node_id"),
                                        label="node_id",
                                        value=5,
                                        value_type="int",
                                        editable=True,
                                    ),
                                    ConfigFieldModel(
                                        path=("robot arm configuration", "sensors", "zposs", "reverse"),
                                        label="reverse",
                                        value=False,
                                        value_type="bool",
                                        editable=True,
                                    ),
                                ],
                            ),
                        ],
                    )
                ],
            )
        )

        panel.show()
        self._app.processEvents()

        self.assertIn("tof", [label.text() for label in panel.findChildren(QLabel)])
        self.assertIn("zposs", [label.text() for label in panel.findChildren(QLabel)])
        self.assertNotIn("node_id", [label.text() for label in panel.findChildren(QLabel)])
        self.assertNotIn("reverse", [label.text() for label in panel.findChildren(QLabel)])
        self.assertEqual(len(panel.findChildren(QWidget, "ConfigSensorPairRow")), 1)
        self.assertEqual(
            panel.collect_value(),
            {
                "sensors": {
                    "tof": {"node_id": 9, "reverse": True},
                    "zposs": {"node_id": 5, "reverse": False},
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
