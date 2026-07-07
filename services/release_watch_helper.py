"""Bounded helper for optional interrupt release-watch polling."""

from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer

from data.binary_cmd_builders import build_interrupt_query_payload


class ReleaseWatchHelper(QObject):
    """Poll D8 on demand until one watched sensor is released or the watch ends."""

    def __init__(
        self,
        bridge: object,
        *,
        poll_interval_ms: int = 75,
        timeout_ms: int = 1500,
        time_source: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._poll_interval_ms = max(1, int(poll_interval_ms))
        self._timeout_ms = max(1, int(timeout_ms))
        self._time_source = time_source or time.monotonic
        self._poll_timer = QTimer(self)
        self._poll_timer.setSingleShot(False)
        self._poll_timer.setInterval(self._poll_interval_ms)
        self._poll_timer.timeout.connect(self._handle_poll_tick)
        self._active = False
        self._node_id: int | None = None
        self._expected_sensor: str | None = None
        self._send_query: Callable[[list[int]], None] | None = None
        self._on_released: Callable[[int, str], None] | None = None
        self._on_timeout: Callable[[int, str], None] | None = None
        self._on_stopped: Callable[[int, str, str], None] | None = None
        self._started_at = 0.0
        self._query_count = 0

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def active_node_id(self) -> int | None:
        return self._node_id

    @property
    def expected_sensor(self) -> str | None:
        return self._expected_sensor

    @property
    def query_count(self) -> int:
        return self._query_count

    def start_release_watch(
        self,
        node_id: int,
        expected_sensor: str,
        send_query: Callable[[list[int]], None],
        *,
        on_released: Callable[[int, str], None] | None = None,
        on_timeout: Callable[[int, str], None] | None = None,
        on_stopped: Callable[[int, str, str], None] | None = None,
    ) -> bool:
        if self._active:
            return False

        normalized_sensor = str(expected_sensor).strip().upper()
        if normalized_sensor not in {"L", "R"}:
            raise ValueError("expected_sensor must be 'L' or 'R'")

        self._active = True
        self._node_id = int(node_id)
        self._expected_sensor = normalized_sensor
        self._send_query = send_query
        self._on_released = on_released
        self._on_timeout = on_timeout
        self._on_stopped = on_stopped
        self._started_at = float(self._time_source())
        self._query_count = 0

        if self._release_condition_met():
            self._finish_released()
            return True

        self._send_interrupt_query()
        self._poll_timer.start()
        return True

    def stop_release_watch(self, reason: str = "cancelled") -> bool:
        if not self._active:
            return False
        self._finish_stop(str(reason))
        return True

    def _handle_poll_tick(self) -> None:
        if not self._active:
            return
        if not self._runtime_connected():
            self._finish_stop("disconnect")
            return
        if self._release_condition_met():
            self._finish_released()
            return
        elapsed_ms = int((float(self._time_source()) - self._started_at) * 1000)
        if elapsed_ms >= self._timeout_ms:
            self._finish_timeout()
            return
        self._send_interrupt_query()

    def _send_interrupt_query(self) -> None:
        if not self._active or self._send_query is None:
            return
        self._query_count += 1
        self._send_query(build_interrupt_query_payload())

    def _release_condition_met(self) -> bool:
        if not self._active or self._node_id is None:
            return False
        state = self._bridge.get_runtime_node_interrupt_state(self._node_id, create_if_missing=False)
        left_cut = state.get("left_cut")
        right_cut = state.get("right_cut")
        return left_cut is False and right_cut is False

    def _runtime_connected(self) -> bool:
        connection_state = getattr(self._bridge, "get_runtime_connection_state", None)
        if not callable(connection_state):
            return True
        serial_connected, _mcu_connected = connection_state(create_if_missing=False)
        return bool(serial_connected)

    def _finish_released(self) -> None:
        node_id = self._node_id
        expected_sensor = self._expected_sensor
        callback = self._on_released
        self._finish_stop("released")
        if callback is not None and node_id is not None and expected_sensor is not None:
            callback(node_id, expected_sensor)

    def _finish_timeout(self) -> None:
        node_id = self._node_id
        expected_sensor = self._expected_sensor
        callback = self._on_timeout
        self._finish_stop("timeout")
        if callback is not None and node_id is not None and expected_sensor is not None:
            callback(node_id, expected_sensor)

    def _finish_stop(self, reason: str) -> None:
        node_id = self._node_id
        expected_sensor = self._expected_sensor
        callback = self._on_stopped
        self._poll_timer.stop()
        self._active = False
        self._node_id = None
        self._expected_sensor = None
        self._send_query = None
        self._on_released = None
        self._on_timeout = None
        self._on_stopped = None
        self._started_at = 0.0
        if callback is not None and node_id is not None and expected_sensor is not None:
            callback(node_id, expected_sensor, str(reason))
