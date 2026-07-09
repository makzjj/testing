"""Shared company-style communication log store and formatters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Sequence

from data.binary_cmd_parser import decode_command
from myconfig.node_display import format_node_display

_DECODER_INDENT = " " * 30
_DEFAULT_MAX_ENTRIES = 2000
_SYS_MODE_QUERY_BYTES = (0xB5, 0x3F)
_SYS_MODE_RESPONSE_BYTES = (0xB5, 0x3A)
_POLLING_DECODE_MARKERS = (" MOTOR_I ",)
_POLLING_CONTROL_RAW_HEX_MARKERS = (" CF 3F ", " D3 3D ", " E4 3D ", " 82 3F ")

_COMMAND_LABELS: dict[int, str] = {
    0x84: "VEL",
    0x88: "RUN",
    0x81: "TPOS",
    0x82: "GETPOS",
    0xC3: "HUNTING",
    0xC4: "NODECONFIG",
    0xC8: "FW",
    0xC9: "LFLAG",
    0xCA: "RFLAG",
    0xAB: "TOF",
    0xBC: "COMM_STATS",
    0xBF: "COMM_TEST",
    0xCD: "TYPE",
    0xCF: "MOTOR_I",
    0xD8: "INTERRUPT",
    0xE0: "UUID",
    0xB5: "SYS_MODE",
}


def format_comm_timestamp(moment: datetime | None = None) -> str:
    """Return the company timestamp format with colon-separated milliseconds."""
    stamp = moment or datetime.now()
    return stamp.strftime("%Y-%m-%d %H:%M:%S:%f")[:-3]


def format_raw_bytes(data: bytes | bytearray | memoryview | Sequence[int]) -> str:
    """Render bytes as uppercase hex separated by spaces."""
    return " ".join(f"{int(value) & 0xFF:02X}" for value in bytes(data))


def format_raw_line(direction: str, data: bytes | bytearray | memoryview | Sequence[int], *, moment: datetime | None = None) -> str:
    """Render one raw company-style communication line."""
    timestamp = format_comm_timestamp(moment)
    payload = bytes(data)
    return f"{timestamp} [{direction}] {format_raw_bytes(payload)} ({len(payload)})"


def format_decoded_line(node_id: int | None, text: str) -> str:
    """Render one indented decoded line."""
    return f"{_DECODER_INDENT}{format_node_display(node_id)} {text}"


def _signed_from_bytes(data: Sequence[int]) -> int:
    payload = bytes(int(value) & 0xFF for value in data)
    if not payload:
        return 0
    return int.from_bytes(payload, byteorder="big", signed=True)


def _decimal_bytes(data: Sequence[int]) -> str:
    return " ".join(str(int(value) & 0xFF) for value in data)


def _format_velocity_like(label: str, params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if not values:
        return label
    marker = None
    if len(values) >= 3 and values[0] == 0x53:
        marker = "'S'"
        values = values[1:]
    if len(values) < 2:
        return None
    signed = _signed_from_bytes(values[:2])
    parts = [label]
    if marker is not None:
        parts.append(marker)
    parts.append(_decimal_bytes(values[:2]))
    parts.append(f"({signed})")
    return " ".join(parts)


def _format_tpos(params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if not values:
        return "TPOS"

    first = values[0]
    if len(values) == 1 and 32 <= first <= 126:
        return f"TPOS '{chr(first)}'"

    marker = None
    position_bytes: list[int]
    if len(values) >= 6 and 32 <= first <= 126 and values[1] == 0x82:
        marker = f"'{chr(first)}'"
        position_bytes = values[2:6]
    elif len(values) >= 5 and 32 <= first <= 126:
        marker = f"'{chr(first)}'"
        position_bytes = values[1:5]
    elif len(values) >= 4:
        position_bytes = values[:4]
    else:
        return None

    signed = _signed_from_bytes(position_bytes)
    parts = ["TPOS"]
    if marker is not None:
        parts.append(marker)
    parts.append(_decimal_bytes(position_bytes))
    parts.append(f"({signed})")
    return " ".join(parts)


def _format_getpos(params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if len(values) >= 5 and values[0] == 0x3A:
        values = values[1:5]
    elif len(values) >= 4:
        values = values[:4]
    else:
        return None

    signed = _signed_from_bytes(values)
    return f"GETPOS {_decimal_bytes(values)} ({signed})"


def _format_flag(label: str, params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if not values:
        return label
    marker = None
    if values[0] == 0x3A:
        marker = "':'"
        values = values[1:]
    if not values:
        return None
    signed = _signed_from_bytes(values)
    parts = [label]
    if marker is not None:
        parts.append(marker)
    parts.append(_decimal_bytes(values))
    parts.append(f"({signed})")
    return " ".join(parts)


def _format_interrupt(params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if not values:
        return "INTERRUPT"
    marker = None
    if values[0] == 0x3A:
        marker = "':'"
        values = values[1:]
    if not values:
        return None
    signed = int.from_bytes(bytes(values), byteorder="big", signed=False)
    parts = ["INTERRUPT"]
    if marker is not None:
        parts.append(marker)
    parts.append(_decimal_bytes(values))
    parts.append(f"({signed})")
    return " ".join(parts)


def _format_motor_current(params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    _key, decoded = decode_command(0xCF, values)
    if not isinstance(decoded, int):
        return None
    return f"MOTOR_I {decoded} mA"


def _format_uuid(params: Sequence[int]) -> str | None:
    values = [int(value) & 0xFF for value in params]
    if len(values) >= 6 and values[0] == 0x3A:
        values = values[1:6]
    elif len(values) >= 5:
        values = values[:5]
    else:
        return None
    signed = int.from_bytes(bytes(values), byteorder="big", signed=False)
    return f"UUID {_decimal_bytes(values)} ({signed})"


def _format_generic_decoded_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        if "text" in value:
            return str(value["text"])
        if "raw" in value and "filtered" in value:
            return f"{value['raw']} {value['filtered']}"
        return ", ".join(f"{key}={value[key]}" for key in value)
    if isinstance(value, tuple):
        return " ".join(str(item) for item in value)
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def format_packet_decoded_text(packet: dict) -> str | None:
    """Return one readable decoded line for a parser packet, if possible."""
    if packet.get("status") != "ok":
        return None

    packet_type = packet.get("type")
    node_id = packet.get("sender", packet.get("node_id"))

    if packet_type == "can_over_uart":
        cmd = packet.get("cmd")
        if cmd is None:
            return None
        try:
            command = int(cmd) & 0xFF
        except (TypeError, ValueError):
            return None
        params = list(packet.get("params", []))
        label = _COMMAND_LABELS.get(command)

        if command == 0x88:
            text = _format_velocity_like("RUN", params)
        elif command == 0x84:
            text = _format_velocity_like("VEL", params)
        elif command == 0x81:
            text = _format_tpos(params)
        elif command == 0x82:
            text = _format_getpos(params)
        elif command == 0xC9:
            text = _format_flag("LFLAG", params)
        elif command == 0xCA:
            text = _format_flag("RFLAG", params)
        elif command == 0xD8:
            text = _format_interrupt(params)
        elif command == 0xCF:
            text = _format_motor_current(params)
        elif command == 0xE0:
            text = _format_uuid(params)
        elif command == 0xC4:
            text = _format_flag("NODECONFIG", params)
        else:
            text = None

        if text is not None:
            return format_decoded_line(node_id, text)

        if label is None:
            return None

        decoded_key = packet.get("decoded_key")
        decoded_value = packet.get("decoded_value")
        if decoded_key and decoded_value is not None:
            generic_value = _format_generic_decoded_value(decoded_value)
            if generic_value is not None:
                return format_decoded_line(node_id, f"{label} {generic_value}")
        return None

    if packet_type == "direct_uart":
        payload = [int(value) & 0xFF for value in packet.get("raw_payload", [])]
        if not payload:
            return None
        command = payload[0]
        params = payload[1:]
        label = _COMMAND_LABELS.get(command)
        if label == "SYS_MODE":
            key, value = decode_command(command, params)
            if value is not None:
                text = _format_generic_decoded_value(value)
                if text is not None:
                    return format_decoded_line(node_id, f"{label} {text}")
            return None
        if label == "FW":
            key, value = decode_command(command, params)
            if value is not None:
                return format_decoded_line(node_id, f"{label} {value}")
            return None
        if label == "UUID":
            text = _format_uuid(params)
            if text is not None:
                return format_decoded_line(node_id, text)
            return None
        if label is None:
            key, value = decode_command(command, params)
            if key and value is not None:
                generic_value = _format_generic_decoded_value(value)
                if generic_value is not None:
                    return format_decoded_line(node_id, f"{key.upper()} {generic_value}")
            return None

        text = _format_generic_decoded_value(decode_command(command, params)[1])
        if text is not None:
            return format_decoded_line(node_id, f"{label} {text}")
    return None


def format_outgoing_frame_decoded_text(raw_frame: bytes | bytearray | memoryview | Sequence[int]) -> str | None:
    """Format one complete outgoing AMX frame into a decoded line."""
    frame = bytes(raw_frame)
    if len(frame) < 8 or frame[0] != 0x25 or frame[1] != 0xA5:
        return None

    payload_len = frame[5]
    total_len = payload_len + 8
    if len(frame) < total_len:
        return None

    can_data = list(frame[6 : 6 + payload_len])
    if not can_data:
        return None

    packet = {
        "status": "ok",
        "type": "can_over_uart",
        # Outgoing display should reflect the addressed node, not the PC/master sender.
        "node_id": frame[3],
        "target": frame[3],
        "port": frame[4],
        "cmd": can_data[0],
        "params": can_data[1:],
        "payload_hex": " ".join(f"{byte:02X}" for byte in can_data),
    }
    return format_packet_decoded_text(packet)


def _is_background_outgoing_frame(raw_bytes: bytes | bytearray | memoryview | Sequence[int]) -> bool:
    """Return True for known periodic PC-originated polling noise.

    Keep this list intentionally narrow. Add only confirmed recurring maintenance
    frames here so operator-facing logs stay readable without hiding real traffic.
    """
    frame = bytes(raw_bytes)
    if len(frame) < 8 or frame[0] != 0x25 or frame[1] != 0xA5:
        return False

    payload_len = int(frame[5]) & 0xFF
    total_len = payload_len + 8
    if len(frame) < total_len or payload_len < 2:
        return False

    can_data = frame[6 : 6 + payload_len]
    return tuple(can_data[:2]) == _SYS_MODE_QUERY_BYTES


def _is_background_incoming_packet(packet: dict) -> bool:
    """Return True for paired responses to the known periodic sys-mode poll."""
    if not isinstance(packet, dict) or packet.get("status") != "ok":
        return False

    packet_type = packet.get("type")
    if packet_type == "direct_uart":
        payload = [int(value) & 0xFF for value in packet.get("raw_payload", [])]
        return len(payload) >= 2 and tuple(payload[:2]) == _SYS_MODE_RESPONSE_BYTES

    if packet_type == "can_over_uart":
        cmd = packet.get("cmd")
        params = [int(value) & 0xFF for value in packet.get("params", [])]
        try:
            command = int(cmd) & 0xFF
        except (TypeError, ValueError):
            return False
        return command == _SYS_MODE_QUERY_BYTES[0] and len(params) >= 1 and params[0] == _SYS_MODE_QUERY_BYTES[1]

    return False


def should_record_communication_frame(
    direction: str,
    raw_bytes: bytes | bytearray | memoryview | Sequence[int],
    *,
    packets: Iterable[dict] | None = None,
) -> bool:
    """Return False only for confirmed store-level background sys-mode noise."""
    normalized_direction = direction.strip().upper()
    if normalized_direction == "OUT":
        return not _is_background_outgoing_frame(raw_bytes)
    if normalized_direction == "IN" and packets is not None:
        packet_list = list(packets)
        if packet_list and all(_is_background_incoming_packet(packet) for packet in packet_list):
            return False
    return True


def _is_hidden_polling_decoded_line(decoded_line: str) -> bool:
    return any(marker in decoded_line for marker in _POLLING_DECODE_MARKERS)


def _is_hidden_polling_raw_line(raw_line: str) -> bool:
    return any(marker in raw_line for marker in _POLLING_CONTROL_RAW_HEX_MARKERS)


def should_display_log_entry(entry: "CommunicationLogEntry", *, hide_polling_packets: bool = False) -> bool:
    """Return whether one stored log entry should be shown in the visible log view."""
    if not hide_polling_packets:
        return True
    if _is_hidden_polling_raw_line(entry.raw_line):
        return any(not _is_hidden_polling_decoded_line(line) for line in entry.decoded_lines)
    if entry.decoded_lines:
        return any(not _is_hidden_polling_decoded_line(line) for line in entry.decoded_lines)
    return True


@dataclass
class CommunicationLogEntry:
    kind: str
    raw_line: str
    decoded_lines: tuple[str, ...] = field(default_factory=tuple)

    def render(self) -> list[str]:
        return [self.raw_line, *self.decoded_lines]

    def render_filtered(self, *, hide_polling_packets: bool = False) -> list[str]:
        if not should_display_log_entry(self, hide_polling_packets=hide_polling_packets):
            return []
        if not hide_polling_packets:
            return self.render()
        # Filtering here is display-only noise suppression; runtime decode/storage
        # still sees the original packets. MOTOR_I streaming and the confirmed
        # control packets below are safe to hide in the visible view. GETPOS
        # responses are intentionally left visible because incoming workflow and
        # background GETPOS traffic are not reliably distinguishable at this layer.
        raw_has_polling = _is_hidden_polling_raw_line(self.raw_line)
        if not self.decoded_lines:
            return [] if raw_has_polling else [self.raw_line]
        visible_decoded = tuple(
            line for line in self.decoded_lines if not _is_hidden_polling_decoded_line(line)
        )
        if raw_has_polling:
            return list(visible_decoded)
        return [self.raw_line, *visible_decoded]


class CommunicationLogStore:
    """Bounded in-memory log buffer for application-wide communication history."""

    def __init__(self, *, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: list[CommunicationLogEntry] = []
        self._listeners: list[Callable[[], None]] = []

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def unsubscribe() -> None:
            try:
                self._listeners.remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                continue

    def _append_entry(self, entry: CommunicationLogEntry) -> None:
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            excess = len(self._entries) - self._max_entries
            del self._entries[:excess]
        self._notify()

    def record_out(
        self,
        raw_bytes: bytes | bytearray | memoryview | Sequence[int],
        *,
        decoded_line: str | None = None,
        moment: datetime | None = None,
    ) -> None:
        if not should_record_communication_frame("OUT", raw_bytes):
            return
        raw_line = format_raw_line("OUT", raw_bytes, moment=moment)
        decoded_lines = (decoded_line,) if decoded_line else ()
        self._append_entry(CommunicationLogEntry("OUT", raw_line, decoded_lines))

    def record_in(
        self,
        raw_bytes: bytes | bytearray | memoryview | Sequence[int],
        *,
        packets: Iterable[dict] | None = None,
        decoded_lines: Iterable[str] = (),
        moment: datetime | None = None,
    ) -> None:
        packet_list = list(packets) if packets is not None else None
        if packet_list is not None and not should_record_communication_frame("IN", raw_bytes, packets=packet_list):
            return
        raw_line = format_raw_line("IN ", raw_bytes, moment=moment)
        if packet_list is not None:
            cleaned = tuple(
                line
                for packet in packet_list
                if not _is_background_incoming_packet(packet)
                for line in [format_packet_decoded_text(packet)]
                if line
            )
        else:
            cleaned = tuple(line for line in decoded_lines if line)
        self._append_entry(CommunicationLogEntry("IN ", raw_line, cleaned))

    def clear(self) -> None:
        self._entries.clear()
        self._notify()

    def entries(self) -> list[CommunicationLogEntry]:
        return list(self._entries)

    def to_plain_text(self, *, hide_polling_packets: bool = False) -> str:
        parts: list[str] = []
        for entry in self._entries:
            rendered_lines = entry.render_filtered(hide_polling_packets=hide_polling_packets)
            if rendered_lines:
                parts.append("\n".join(rendered_lines))
        return "\n\n".join(parts)

    def export_text(
        self,
        *,
        exported_at: datetime | None = None,
        current_page: str | None = None,
        selected_node: str | None = None,
    ) -> str:
        timestamp = format_comm_timestamp(exported_at)
        page_text = current_page or "-"
        node_text = selected_node or "-"
        header = [
            "IPQC Communication Log",
            f"Exported: {timestamp}",
            f"Current Page: {page_text}",
            f"Selected Node: {node_text}",
            "",
        ]
        body = self.to_plain_text()
        header_text = "\n".join(header)
        if body:
            return header_text + "\n" + body + "\n"
        return header_text + "\n"

    def save(
        self,
        path: str | Path,
        *,
        exported_at: datetime | None = None,
        current_page: str | None = None,
        selected_node: str | None = None,
    ) -> None:
        text = self.export_text(
            exported_at=exported_at,
            current_page=current_page,
            selected_node=selected_node,
        )
        Path(path).write_text(text, encoding="utf-8")
