"""Focused tests for communication-monitor firmware/version ownership."""

from __future__ import annotations

import unittest

from PyQt6.QtWidgets import QApplication, QWidget

from gui.comm_monitor import CommMonitorDialog


class CommMonitorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_generate_report_reads_versions_from_runtime_node_status(self) -> None:
        parent = QWidget()
        parent.mcu_version = "2.0.0"
        parent.node_status = {
            3: {"firmware": "v1.0.0"},
            4: {"firmware": "v1.1.0"},
        }

        dialog = CommMonitorDialog(parent)
        dialog.active_nodes = {3, 4}
        dialog.mcu_ver_lbl.setText("2.0.0")
        dialog.stats = {
            3: {"total": 10, "lost": 0, "start_time": 0, "last_time": 100},
            4: {"total": 10, "lost": 0, "start_time": 0, "last_time": 100},
        }
        dialog.mcu_can_rx_lbl.setText("20")

        report = dialog.generate_report()

        self.assertFalse(hasattr(dialog, "node_versions"))
        self.assertIn("MCU Firmware Version: 2.0.0", report)
        self.assertIn("Node Ya(03) Version: v1.0.0", report)
        self.assertIn("Node Yb(04) Version: v1.1.0", report)

    def test_handle_node_version_only_advances_pretest_state(self) -> None:
        parent = QWidget()
        parent.mcu_version = "2.0.0"
        parent.node_status = {3: {"firmware": "v1.0.0"}}

        dialog = CommMonitorDialog(parent)
        dialog.pretest_active = True
        dialog.pretest_nodes_pending = {3}
        triggered: list[bool] = []
        dialog._execute_start_test = lambda: triggered.append(True)

        dialog.handle_node_version(3, "v1.0.0")

        self.assertFalse(hasattr(dialog, "node_versions"))
        self.assertFalse(dialog.pretest_active)
        self.assertEqual(dialog.pretest_nodes_pending, set())
        self.assertEqual(triggered, [True])


if __name__ == "__main__":
    unittest.main()
