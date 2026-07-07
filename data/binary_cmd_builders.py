"""Binary command builders for motor control commands.

These functions are intentionally self-contained to avoid tight coupling
with UI/controller modules. Tests and controllers import builders from
this stable module path.
"""

from __future__ import annotations

def build_hunting_timeout(timeout_ms: int) -> list[int]:
    timeout_ms = max(0, min(0xFFFF, int(timeout_ms)))
    hi = (timeout_ms >> 8) & 0xFF
    lo = timeout_ms & 0xFF
    return [0xC3, 0x21, hi, lo]


def build_getpos() -> list[int]:
    return [0x82]


def _twos_complement_16(value: int) -> tuple[int, int]:
    value &= 0xFFFF
    return (value >> 8) & 0xFF, value & 0xFF


def build_run(velocity: int) -> list[int]:
    vel = int(velocity)
    if vel < -32768:
        vel = -32768
    if vel > 32767:
        vel = 32767
    hi, lo = _twos_complement_16(vel)
    return [0x88, hi, lo]


def build_vel(velocity: int) -> list[int]:
    if not isinstance(velocity, int):
        raise TypeError("velocity must be int")
    vel = velocity & 0xFFFF
    hi, lo = _twos_complement_16(vel)
    return [0x84, hi, lo]


def build_tpos(position: int) -> list[int]:
    b = list((int(position) & 0xFFFFFFFF).to_bytes(4, byteorder="big", signed=False))
    return [0x81] + b


def build_stopmotor() -> list[int]:
    return [0xDD]


# These builders are used by both unit tests and the Single Axis Functional
# Test controller/state machine.


def build_nodeconfig_query_payload() -> list[int]:
    """Build NODECONFIG query payload.

    Firmware-confirmed format:
    - Command ID: C4
    - Query: C4 3F
    """
    return [0xC4, 0x3F]


def build_lflag_query_payload() -> list[int]:
    """Build Sensor-L (LFLAG) query payload.

    Firmware format:
    - Command ID: C9
    - Query: C9 3F
    - Response: C9 3A <flags>
    """
    return [0xC9, 0x3F]


def build_rflag_query_payload() -> list[int]:
    """Build Sensor-R (RFLAG) query payload.

    Firmware format:
    - Command ID: CA
    - Query: CA 3F
    - Response: CA 3A <flags>
    """
    return [0xCA, 0x3F]


def build_interrupt_query_payload() -> list[int]:
    """Build interrupt-state (D8) query payload."""
    return [0xD8, 0x3F]
