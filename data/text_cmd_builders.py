"""Canonical Manual Text command builders for Firmware Integration."""

from __future__ import annotations

from typing import Sequence

from serial_conn.commands import CommandBuilder


def normalize_text_command(command: str, value: object | None = None) -> str:
    """Normalize one legacy-style text command string before framing."""
    normalized = str(command or "").strip()
    if not normalized:
        raise ValueError("Manual text command is empty.")

    if normalized.endswith("="):
        if value is None:
            raise ValueError(f"Manual text setter {normalized} requires a value.")
        normalized_value = str(value).strip()
        if not normalized_value:
            raise ValueError(f"Manual text setter {normalized} requires a value.")
        return f"{normalized}{normalized_value}"

    if value is not None:
        raise ValueError(f"Manual text command {normalized} does not accept a value.")
    return normalized


def build_text_command_payload(command: str, value: object | None = None) -> bytearray:
    """Build one legacy-compatible AMX frame carrying an ASCII text command.

    Legacy FIT wrapped ASCII commands in the standard AMX/CAN-over-UART frame:
    - sync/header: 25 A5
    - sender/target: 01 01
    - port: 31
    - payload: ASCII command bytes terminated by CRLF CRLF
    - checksum: shared AMX checksum from CommandBuilder
    """

    normalized = normalize_text_command(command, value)
    if not normalized.endswith("\r\n\r\n"):
        if normalized.endswith("\r\n"):
            normalized = normalized + "\r\n"
        else:
            normalized = normalized + "\r\n\r\n"
    command_bytes = list(normalized.encode("ascii"))
    return CommandBuilder.build_can_over_uart_packet(0x01, 0x01, command_bytes)


def decode_text_command_response(raw_payload: Sequence[int] | bytes | bytearray) -> str | None:
    """Decode one direct-UART text payload into normalized ASCII text.

    Behavior:
    - coerce integer-like byte values into one byte string
    - decode as ASCII with invalid bytes ignored
    - trim surrounding whitespace, including CR/LF
    - return None for empty or non-decodable results
    """

    try:
        payload = bytes(int(value) & 0xFF for value in list(raw_payload))
    except Exception:
        return None
    if not payload:
        return None

    decoded = payload.decode("ascii", errors="ignore").strip()
    if not decoded:
        return None
    return decoded
