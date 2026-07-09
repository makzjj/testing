from __future__ import annotations

from datetime import datetime

from PyQt6.QtWidgets import QApplication

from serial_conn.commands import CommandBuilder
from gui.workspace.dialogs.communication_log_dialog import CommunicationLogDialog
from services.communication_log_store import (
    CommunicationLogStore,
    format_node_display,
    format_outgoing_frame_decoded_text,
    should_record_communication_frame,
)


def _fixed_time() -> datetime:
    return datetime(2026, 6, 19, 9, 38, 55, 214000)


_APP = QApplication.instance() or QApplication([])


def test_outgoing_and_incoming_raw_format_and_byte_count() -> None:
    store = CommunicationLogStore()
    outgoing = bytes.fromhex("25 A5 01 06 31 04 88 53 FF 42 00 00")
    incoming = bytes.fromhex("C8 24 06 0A 25 A5 06 01 31 02 81 4C")

    store.record_out(
        outgoing,
        decoded_line=format_outgoing_frame_decoded_text(outgoing),
        moment=_fixed_time(),
    )
    store.record_in(
        incoming,
        decoded_lines=["                              [N6:H] TPOS 'L'"],
        moment=_fixed_time(),
    )

    lines = store.to_plain_text().splitlines()
    assert lines[0] == "2026-06-19 09:38:55:214 [OUT] 25 A5 01 06 31 04 88 53 FF 42 00 00 (12)"
    assert lines[1] == "                              [N6:H] RUN 'S' 255 66 (-190)"
    assert lines[3] == "2026-06-19 09:38:55:214 [IN ] C8 24 06 0A 25 A5 06 01 31 02 81 4C (12)"
    assert lines[4] == "                              [N6:H] TPOS 'L'"


def test_periodic_sys_mode_polling_frame_is_filtered_from_store_and_export() -> None:
    store = CommunicationLogStore()
    polling_frame = CommandBuilder.build_can_over_uart_packet(0x01, 0x01, [0xB5, 0x3F])

    assert not should_record_communication_frame("OUT", polling_frame)

    store.record_out(
        polling_frame,
        decoded_line=format_outgoing_frame_decoded_text(polling_frame),
        moment=_fixed_time(),
    )

    assert store.entries() == []
    assert store.to_plain_text() == ""

    export_text = store.export_text(exported_at=_fixed_time())
    assert "B5 3F" not in export_text


def test_meaningful_outgoing_and_incoming_frames_are_kept() -> None:
    store = CommunicationLogStore()
    outgoing = bytes.fromhex("25 A5 01 06 31 04 88 53 FF 42 00 00")
    incoming_sensor = bytes.fromhex("C8 24 03 04 D8 3A 01 00")
    incoming_ack = bytes.fromhex("C8 24 03 04 BE 3A 41 43 4B")

    store.record_out(
        outgoing,
        decoded_line=format_outgoing_frame_decoded_text(outgoing),
        moment=_fixed_time(),
    )
    store.record_in(
        incoming_sensor,
        packets=[
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 3,
                "raw_payload": [0xD8, 0x3A, 0x01, 0x00],
            }
        ],
        moment=_fixed_time(),
    )
    store.record_in(
        incoming_ack,
        packets=[
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 3,
                "raw_payload": [0xBE, 0x3A, 0x41, 0x43, 0x4B],
            }
        ],
        moment=_fixed_time(),
    )

    text = store.to_plain_text()
    assert "[N6:H] RUN 'S' 255 66 (-190)" in text
    assert "[N3:X] INTERRUPT" in text
    assert "COMM_TEST_START ACK" in text


def test_background_rx_sys_mode_response_is_filtered_when_packets_are_supplied() -> None:
    store = CommunicationLogStore()
    raw_chunk = bytes.fromhex("C8 24 01 08 B5 3A 06 02 00 00 00 00")

    store.record_in(
        raw_chunk,
        packets=[
            {
                "status": "ok",
                "type": "direct_uart",
                "node_id": 1,
                "raw_payload": [0xB5, 0x3A, 0x06, 0x02, 0x00, 0x00, 0x00, 0x00],
            }
        ],
        moment=_fixed_time(),
    )

    assert store.entries() == []
    assert "B5 3A" not in store.export_text(exported_at=_fixed_time())


def test_one_in_chunk_with_multiple_packets_renders_one_raw_line_and_multiple_decoded_lines() -> None:
    store = CommunicationLogStore()
    raw_chunk = bytes.fromhex("C8 24 06 0A 25 A5 06 01 31 02 81 4C C8 24 03 09 25 A5 03 01 31 01 D8")

    store.record_in(
        raw_chunk,
        decoded_lines=[
            "                              [N6:H] LFLAG ':' 9 (9)",
            "                              [N3:X] INTERRUPT ':' 1 1 (257)",
        ],
        moment=_fixed_time(),
    )

    lines = store.to_plain_text().splitlines()
    assert lines[0] == f"2026-06-19 09:38:55:214 [IN ] C8 24 06 0A 25 A5 06 01 31 02 81 4C C8 24 03 09 25 A5 03 01 31 01 D8 ({len(raw_chunk)})"
    assert lines[1] == "                              [N6:H] LFLAG ':' 9 (9)"
    assert lines[2] == "                              [N3:X] INTERRUPT ':' 1 1 (257)"


def test_node_mapping_known_and_unknown() -> None:
    assert format_node_display(6) == "[N6:H]"
    assert format_node_display(7) == "[N7:NZ]"
    assert format_node_display(99) == "[N99:?]"


def test_capacity_limit_keeps_newest_entries() -> None:
    store = CommunicationLogStore(max_entries=2)
    store.record_out(b"\x25\xA5\x01\x06\x31\x03\x88\x00\x64", moment=_fixed_time())
    store.record_out(b"\x25\xA5\x01\x06\x31\x03\x88\x00\x50", moment=_fixed_time())
    store.record_out(b"\x25\xA5\x01\x06\x31\x03\x88\x00\x3C", moment=_fixed_time())

    text = store.to_plain_text()
    assert "00 64" not in text
    assert "00 50" in text
    assert "00 3C" in text


def test_export_uses_company_style_header_and_entries() -> None:
    store = CommunicationLogStore()
    store.record_out(
        bytes.fromhex("25 A5 01 06 31 04 88 53 FF 42 00 00"),
        decoded_line="[N6:H] RUN 255 66 (-190)",
        moment=_fixed_time(),
    )

    export_text = store.export_text(
        exported_at=_fixed_time(),
        current_page="Production",
        selected_node="Node 6 - H",
    )

    assert export_text.startswith(
        "IPQC Communication Log\n"
        "Exported: 2026-06-19 09:38:55:214\n"
        "Current Page: Production\n"
        "Selected Node: Node 6 - H\n\n"
    )
    assert "2026-06-19 09:38:55:214 [OUT] 25 A5 01 06 31 04 88 53 FF 42 00 00 (12)" in export_text


def test_filtered_plain_text_hides_polling_packets_but_keeps_entries_recorded() -> None:
    store = CommunicationLogStore()
    polling_frame = CommandBuilder.build_can_over_uart_packet(0x01, 0x07, [0xCF, 0x3F])
    logpos_disable_frame = CommandBuilder.build_can_over_uart_packet(0x01, 0x07, [0xE4, 0x3D, 0x00, 0x00])
    getpos_frame = CommandBuilder.build_can_over_uart_packet(0x01, 0x07, [0x82, 0x3F])
    run_frame = CommandBuilder.build_can_over_uart_packet(0x01, 0x06, [0x88, 0x53, 0x00, 0x32])

    store.record_out(polling_frame, decoded_line="                              [N7:NZ] MOTOR_I 1234 mA", moment=_fixed_time())
    store.record_out(logpos_disable_frame, moment=_fixed_time())
    store.record_out(getpos_frame, decoded_line="                              [N7:NZ] GETPOS 0 0 0 1 (1)", moment=_fixed_time())
    store.record_out(run_frame, decoded_line="                              [N6:H] RUN 'S' 0 50 (50)", moment=_fixed_time())

    assert len(store.entries()) == 4
    unfiltered = store.to_plain_text()
    filtered = store.to_plain_text(hide_polling_packets=True)

    assert "MOTOR_I 1234 mA" in unfiltered
    assert "GETPOS 0 0 0 1 (1)" in unfiltered
    assert "RUN 'S' 0 50 (50)" in unfiltered
    assert "CF 3F" in unfiltered
    assert "E4 3D 00 00" in unfiltered
    assert "82 3F" in unfiltered
    assert "MOTOR_I 1234 mA" not in filtered
    assert "GETPOS 0 0 0 1 (1)" not in filtered
    assert "CF 3F" not in filtered
    assert "E4 3D 00 00" not in filtered
    assert "82 3F" not in filtered
    assert "RUN 'S' 0 50 (50)" in filtered


def test_communication_log_dialog_hide_polling_packets_filters_visible_text_only() -> None:
    store = CommunicationLogStore()
    store.record_out(
        CommandBuilder.build_can_over_uart_packet(0x01, 0x07, [0xCF, 0x3F]),
        decoded_line="                              [N7:NZ] MOTOR_I 345 mA",
        moment=_fixed_time(),
    )
    store.record_out(
        CommandBuilder.build_can_over_uart_packet(0x01, 0x06, [0x88, 0x53, 0x00, 0x32]),
        decoded_line="                              [N6:H] RUN 'S' 0 50 (50)",
        moment=_fixed_time(),
    )

    dialog = CommunicationLogDialog(store)
    dialog._sync_from_store()
    assert "MOTOR_I 345 mA" in dialog.log_output.toPlainText()
    assert "RUN 'S' 0 50 (50)" in dialog.log_output.toPlainText()

    dialog.hide_polling_checkbox.setChecked(True)
    dialog._sync_from_store()

    assert "MOTOR_I 345 mA" not in dialog.log_output.toPlainText()
    assert "CF 3F" not in dialog.log_output.toPlainText()
    assert "RUN 'S' 0 50 (50)" in dialog.log_output.toPlainText()
    assert len(store.entries()) == 2
    dialog.close()
