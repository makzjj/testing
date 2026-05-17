"""Backend response handling for parsed runtime packets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from data.binary_cmd_parser import decode_command, parse_comm_stats, parse_get_interrupt
from myconfig.constants import BCMD_COMM_STATS, BCMD_COMM_TEST_FRAME, BCMD_GET_MCU_VERSION, BCMD_GET_NODE_ID

from .node_status_store import ensure_node_status

BCMD_COMM_TEST_FINISHED = 0xBD


@dataclass(frozen=True)
class RuntimePacketEvent:
    """One UI-agnostic event emitted after backend packet handling."""

    kind: str
    node_id: int | None = None
    value: Any = None
    message: str | None = None


class RuntimePacketHandler:
    """Translates parsed packets into state updates and UI-agnostic events."""

    def handle_packets(
        self,
        packets: list[dict],
        node_status: dict[int, dict[str, Any]],
        *,
        log_sys_mode: bool = True,
    ) -> list[RuntimePacketEvent]:
        events: list[RuntimePacketEvent] = []
        for packet in packets:
            events.extend(self.handle_packet(packet, node_status, log_sys_mode=log_sys_mode))
        return events

    def handle_packet(
        self,
        packet: dict,
        node_status: dict[int, dict[str, Any]],
        *,
        log_sys_mode: bool = True,
    ) -> list[RuntimePacketEvent]:
        if packet.get("status") != "ok":
            return [RuntimePacketEvent("log", message=f"RX Error: {packet.get('status', 'unknown')}")]

        if packet.get("type") == "can_over_uart" and "sender" in packet:
            return self._handle_can_packet(packet, node_status, log_sys_mode=log_sys_mode)

        if packet.get("type") == "direct_uart":
            return self._handle_direct_uart_packet(packet, log_sys_mode=log_sys_mode)

        return []

    def _handle_can_packet(
        self,
        packet: dict,
        node_status: dict[int, dict[str, Any]],
        *,
        log_sys_mode: bool,
    ) -> list[RuntimePacketEvent]:
        events: list[RuntimePacketEvent] = []
        node_id = int(packet["sender"])
        command = int(packet.get("cmd", 0))
        params = list(packet.get("params", []))

        self._append_monitor_events(events, node_id, command, params)

        param_str = " ".join(f"{byte:02X}" for byte in params)
        message = f"RX[CAN] From:{node_id:02X} Cmd:{command:02X} Params:[{param_str}]"
        if command == 0x81:
            _, decoded_value = decode_command(command, params)
            if decoded_value:
                message += f" -> {decoded_value}"

        if 2 <= node_id <= 17:
            events.append(RuntimePacketEvent("node_activity", node_id=node_id))
            node_record = ensure_node_status(node_status, node_id)

            if command == 0xD8:
                self._handle_interrupt_response(events, node_id, params, node_record)

            decoded_key = packet.get("decoded_key")
            decoded_value = packet.get("decoded_value")
            if decoded_key and decoded_value:
                node_record[decoded_key] = decoded_value
                if decoded_key != "tpos":
                    events.append(RuntimePacketEvent("log", message=f"Decoded [{decoded_key}] = {decoded_value}"))

            key, value = decode_command(command, params)
            if key == "sys_mode" and value is not None:
                events.append(RuntimePacketEvent("sys_mode", value=value))
                if log_sys_mode:
                    events.append(RuntimePacketEvent("log", message=f"System Mode Response (CAN): {value['text']}"))

            if key and key != decoded_key:
                node_record[key] = value
                if key not in ("tpos", "sys_mode"):
                    events.append(RuntimePacketEvent("log", message=f"Decoded [{key}] = {value}"))

            if "adc_raw" in packet and "physical_value" in packet:
                events.append(RuntimePacketEvent("zposs_sample", node_id=node_id, value=(packet["adc_raw"], packet["physical_value"])))

            if key == "tof_distance" or decoded_key == "tof_distance":
                tof_value = value if key == "tof_distance" else decoded_value
                events.append(RuntimePacketEvent("tof_sample", node_id=node_id, value=tof_value))

            if packet.get("uuid_response"):
                self._handle_uuid_response(events, node_id, packet, node_record)

            if command == BCMD_GET_NODE_ID:
                events.append(RuntimePacketEvent("node_id_response", node_id=node_id, value=params))

        events.append(RuntimePacketEvent("log", message=message))
        return events

    def _append_monitor_events(self, events: list[RuntimePacketEvent], node_id: int, command: int, params: list[int]) -> None:
        if command == BCMD_COMM_TEST_FRAME:
            sequence = (params[0] << 8) | params[1] if len(params) >= 2 else None
            if sequence is not None:
                events.append(RuntimePacketEvent("comm_test_packet", node_id=node_id, value=sequence))
        elif command == BCMD_COMM_TEST_FINISHED:
            events.append(RuntimePacketEvent("comm_test_finished", node_id=node_id))
        elif command == BCMD_GET_MCU_VERSION:
            _, version = decode_command(command, params)
            events.append(RuntimePacketEvent("node_version", node_id=node_id, value=version))

    def _handle_interrupt_response(
        self,
        events: list[RuntimePacketEvent],
        node_id: int,
        params: list[int],
        node_record: dict[str, Any],
    ) -> None:
        interrupt_data = parse_get_interrupt(params)
        if isinstance(interrupt_data, dict) and "text" in interrupt_data:
            node_record["interrupt"] = interrupt_data["text"]
            node_record["interrupt_data"] = interrupt_data
            events.append(RuntimePacketEvent("log", message=f"✅ Interrupt status for Node {node_id}: {interrupt_data['text']}"))
            return

        node_record["interrupt"] = "Error"
        node_record["interrupt_data"] = {}
        events.append(RuntimePacketEvent("log", message=f"❌ ERROR: Invalid interrupt data format for Node {node_id}"))

    def _handle_uuid_response(
        self,
        events: list[RuntimePacketEvent],
        node_id: int,
        packet: dict,
        node_record: dict[str, Any],
    ) -> None:
        uuid = packet.get("uuid", "Unknown")
        is_valid = packet.get("uuid_valid", False)
        if is_valid:
            node_record["uuid"] = uuid
            node_record["uuid_valid"] = True
            events.append(RuntimePacketEvent("log", message=f"✅ Node {node_id:02X} UUID: {uuid}"))
            return

        node_record["uuid_valid"] = False
        events.append(RuntimePacketEvent("log", message=f"❌ Node {node_id:02X} UUID: Invalid"))

    def _handle_direct_uart_packet(self, packet: dict, *, log_sys_mode: bool) -> list[RuntimePacketEvent]:
        events: list[RuntimePacketEvent] = []
        payload = list(packet.get("raw_payload", []))
        if not payload:
            return events

        command = payload[0]
        params = payload[1:]
        key, value = decode_command(command, params)
        if key == "sys_mode" and value is not None:
            events.append(RuntimePacketEvent("sys_mode", value=value))
            if log_sys_mode:
                events.append(RuntimePacketEvent("log", message=f"System Mode Response (Direct): {value['text']}"))

        if command == BCMD_COMM_STATS:
            stats = parse_comm_stats(params)
            if stats:
                events.append(RuntimePacketEvent("comm_stats", value=stats))

        if packet.get("mcu_version_response"):
            events.append(RuntimePacketEvent("mcu_version", value=packet.get("mcu_version", "Unknown")))

        return events
