from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

from gui.workspace.pages import firmware_page as firmware_page_module
from gui.workspace.pages.firmware_page import FirmwarePage


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeBridge:
    def __init__(self) -> None:
        self.raw_config = {}
        self.binary_sends: list[tuple[int, list[int]]] = []
        self.text_sends: list[bytearray] = []
        self.runtime_window = SimpleNamespace(
            mcu_version="v1.2.3.4",
            node_status={
                3: {
                    "connected": True,
                    "firmware": "v1.2.3.4",
                    "uuid": "123456789 (0x00075BCD15)",
                    "type": "MTR (Motor Controller)",
                    "interrupt_state": {
                        "left_cut": False,
                        "right_cut": False,
                    },
                },
                4: {
                    "connected": True,
                    "firmware": "v1.2.3.5",
                    "uuid": "987654321 (0x003ADE68B1)",
                    "type": "MTR (Motor Controller)",
                    "interrupt_state": {
                        "left_cut": True,
                        "right_cut": False,
                    },
                },
                10: {
                    "connected": True,
                    "firmware": "v1.0.0.1",
                    "uuid": "55555 (0x000000D903)",
                    "type": "HMI (Human Interface)",
                    "interrupt_state": {
                        "left_cut": None,
                        "right_cut": None,
                    },
                },
                11: {
                    "connected": True,
                    "firmware": "v1.0.0.2",
                    "uuid": "77777 (0x0000012FD1)",
                    "type": "NGC (Needle Guide Controller)",
                    "interrupt_state": {
                        "left_cut": None,
                        "right_cut": None,
                    },
                },
            },
            detected_nodes={3, 4, 10, 11},
        )

    def get_runtime_window(self, *, create_if_missing: bool = False):
        _ = create_if_missing
        return self.runtime_window

    def send_firmware_binary_command(self, node_id: int, payload: list[int]) -> bytearray:
        self.binary_sends.append((int(node_id), list(payload)))
        return bytearray(payload)

    def send_firmware_text_command(self, payload: bytearray) -> bytearray:
        self.text_sends.append(bytearray(payload))
        return payload

    def get_runtime_mcu_firmware_version(self, *, create_if_missing: bool = False) -> str | None:
        _ = create_if_missing
        return getattr(self.runtime_window, "mcu_version", None)

    def get_runtime_node_system_info(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        _ = create_if_missing
        status = (self.runtime_window.node_status or {}).get(int(node_id), {})
        detected_nodes = set(getattr(self.runtime_window, "detected_nodes", set()) or set())
        return {
            "node_id": int(node_id),
            "detected": bool(status.get("connected", False)) or int(node_id) in detected_nodes,
            "connected": bool(status.get("connected", False)),
            "firmware": status.get("firmware"),
            "uuid": status.get("uuid"),
            "node_type": status.get("type"),
        }

    def get_runtime_node_interrupt_state(self, node_id: int, *, create_if_missing: bool = False) -> dict[str, object]:
        _ = create_if_missing
        interrupt = ((self.runtime_window.node_status or {}).get(int(node_id), {}) or {}).get("interrupt_state", {})
        left_cut = interrupt.get("left_cut")
        right_cut = interrupt.get("right_cut")
        return {
            "node_id": int(node_id),
            "left_cut": left_cut,
            "right_cut": right_cut,
            "left_state": "cut" if left_cut is True else "not_cut" if left_cut is False else "unknown",
            "right_state": "cut" if right_cut is True else "not_cut" if right_cut is False else "unknown",
        }


class FirmwareSystemInformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _panel_titles(self, page: FirmwarePage) -> list[str]:
        titles: list[str] = []
        for index in range(page.content_layout.count()):
            widget = page.content_layout.itemAt(index).widget()
            if widget is None:
                continue
            title = widget.findChild(QLabel, "PanelTitle")
            if title is not None:
                titles.append(title.text())
        return titles

    def _table(self, page: FirmwarePage) -> QTableWidget:
        table = page.findChild(QTableWidget, "FirmwareSystemInfoTable")
        self.assertIsNotNone(table)
        assert table is not None
        return table

    def _drain_refresh(self, page: FirmwarePage, timeout_ms: int = 500) -> None:
        waited = 0
        while page._system_info_refresh_active and waited <= timeout_ms:
            self._app.processEvents()
            QTest.qWait(10)
            waited += 10
        self._app.processEvents()

    def _int_badge(self, table: QTableWidget, row: int) -> QLabel:
        container = table.cellWidget(row, 4)
        self.assertIsNotNone(container)
        assert container is not None
        badge = container.findChild(QLabel, "FirmwareSystemInfoIntBadge")
        self.assertIsNotNone(badge)
        assert badge is not None
        return badge

    def test_firmware_page_contains_only_firmware_integration_and_system_information(self) -> None:
        page = FirmwarePage(_FakeBridge())

        self.assertEqual(self._panel_titles(page), ["Firmware Integration", "System Information"])
        page_text = "\n".join(label.text() for label in page.findChildren(QLabel))
        for removed_title in (
            "UART Protocol Handler",
            "Frame Loss Summary",
            "Motion Command Panel",
            "Command Debug",
            "Sensor Snapshot",
            "Robot Arm Nodes",
        ):
            self.assertNotIn(removed_title, page_text)

    def test_system_information_table_renders_canonical_rows_from_runtime_state(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        table = self._table(page)

        self.assertEqual(
            [table.horizontalHeaderItem(index).text() for index in range(table.columnCount())],
            ["Node", "Firmware", "UUID", "Node Type", "INT Status"],
        )
        self.assertEqual(table.rowCount(), 10)
        self.assertEqual(table.item(0, 0).text(), "X (3)")
        self.assertEqual(table.item(1, 0).text(), "Y (4)")
        self.assertEqual(table.item(7, 0).text(), "HMI (10)")
        self.assertEqual(table.item(8, 0).text(), "NGC (11)")
        self.assertEqual(table.item(9, 0).text(), "Z (12)")
        self.assertEqual(table.item(0, 2).text(), "123456789 (0x00075BCD15)")
        self.assertEqual(table.item(0, 3).text(), "MTR")
        self.assertEqual(table.item(7, 3).text(), "HMI")
        self.assertEqual(table.item(8, 3).text(), "NGC")
        self.assertEqual(table.item(9, 1).text(), "Not Detected")
        self.assertEqual(table.item(9, 2).text(), "—")
        header = table.horizontalHeader()
        self.assertTrue(all(header.sectionResizeMode(index) == header.ResizeMode.Stretch for index in range(table.columnCount())))
        self.assertFalse(table.verticalScrollBar().isVisible())
        self.assertFalse(table.horizontalScrollBar().isVisible())

    def test_system_information_int_status_uses_expected_text_and_colors(self) -> None:
        page = FirmwarePage(_FakeBridge())
        table = self._table(page)

        self.assertEqual(table.item(0, 4).text(), "")
        self.assertIn("#00C853", self._int_badge(table, 0).styleSheet())
        self.assertEqual(table.item(1, 4).text(), "")
        self.assertIn("#FFD600", self._int_badge(table, 1).styleSheet())
        self.assertEqual(table.item(7, 4).text(), "")
        self.assertIn("#FF2800", self._int_badge(table, 7).styleSheet())
        self.assertEqual(table.item(9, 4).text(), "")
        self.assertIn("#FF2800", self._int_badge(table, 9).styleSheet())

    def test_system_information_rerenders_from_runtime_values_without_page_cache(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        table = self._table(page)

        self.assertEqual(table.item(0, 1).text(), "v1.2.3.4")
        bridge.runtime_window.node_status[3]["firmware"] = "v9.9.9.9"
        bridge.runtime_window.node_status[3]["interrupt_state"] = {"left_cut": False, "right_cut": True}
        page.refresh()

        self.assertEqual(table.item(0, 1).text(), "v9.9.9.9")
        self.assertEqual(self._int_badge(table, 0).text(), "L: OK  R: Cut")

    def test_opening_page_sends_nothing_and_update_uses_canonical_builders_for_one_shot_refresh(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        page._REFRESH_STEP_INTERVAL_MS = 0
        page._REFRESH_SETTLE_MS = 0
        update_button = page.findChild(QPushButton, "FirmwareSystemInfoUpdateButton")
        self.assertIsNotNone(update_button)
        assert update_button is not None

        self.assertEqual(bridge.text_sends, [])
        self.assertEqual(bridge.binary_sends, [])

        with (
            patch.object(firmware_page_module, "build_text_command_payload", return_value=bytearray([0xAA, 0x01])) as build_text,
            patch.object(firmware_page_module, "build_getver_query_payload", return_value=[0xB1]) as build_ver,
            patch.object(firmware_page_module, "build_get_uuid_query_payload", return_value=[0xB2]) as build_uuid,
            patch.object(firmware_page_module, "build_get_nodetype_query_payload", return_value=[0xB3]) as build_type,
            patch.object(firmware_page_module, "build_interrupt_query_payload", return_value=[0xB4]) as build_int,
        ):
            update_button.click()
            self._drain_refresh(page)

        build_text.assert_called_once_with("ver?")
        self.assertEqual(build_ver.call_count, 10)
        self.assertEqual(build_uuid.call_count, 10)
        self.assertEqual(build_type.call_count, 10)
        self.assertEqual(build_int.call_count, 8)
        self.assertEqual(bridge.text_sends, [bytearray([0xAA, 0x01])])
        self.assertEqual(len(bridge.binary_sends), 38)
        self.assertEqual([node_id for node_id, payload in bridge.binary_sends if payload == [0xB4]], [3, 4, 5, 6, 7, 8, 9, 12])
        queried_nodes = sorted({node_id for node_id, _payload in bridge.binary_sends})
        self.assertEqual(queried_nodes, [3, 4, 5, 6, 7, 8, 9, 10, 11, 12])

    def test_duplicate_update_does_not_start_overlapping_refresh(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        page._REFRESH_STEP_INTERVAL_MS = 1
        page._REFRESH_SETTLE_MS = 1
        update_button = page.findChild(QPushButton, "FirmwareSystemInfoUpdateButton")
        self.assertIsNotNone(update_button)
        assert update_button is not None

        update_button.click()
        first_binary_count = len(bridge.binary_sends)
        update_button.click()
        self._drain_refresh(page, timeout_ms=1000)

        self.assertEqual(first_binary_count, 0)
        self.assertEqual(len(bridge.text_sends), 1)
        self.assertEqual(len(bridge.binary_sends), 38)

    def test_hiding_page_stops_pending_refresh_timers_and_background_traffic(self) -> None:
        bridge = _FakeBridge()
        page = FirmwarePage(bridge)
        page._REFRESH_STEP_INTERVAL_MS = 50
        page._REFRESH_SETTLE_MS = 50
        page.show()
        self._app.processEvents()
        update_button = page.findChild(QPushButton, "FirmwareSystemInfoUpdateButton")
        self.assertIsNotNone(update_button)
        assert update_button is not None

        update_button.click()
        self.assertEqual(len(bridge.text_sends), 1)
        self.assertEqual(len(bridge.binary_sends), 0)

        page.hide()
        QTest.qWait(160)
        self._app.processEvents()

        self.assertEqual(len(bridge.text_sends), 1)
        self.assertEqual(len(bridge.binary_sends), 0)
        self.assertFalse(page._system_info_refresh_active)
