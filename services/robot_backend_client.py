"""Reusable backend client for robot-arm serial API operations."""

from __future__ import annotations

from myconfig.constants import COMMANDS
from serial_conn.commands import CommandBuilder
from serial_conn.connection import SerialConnection
from serial_conn.packet_parser import parse_uart_rx_packets


class RobotBackendClient:
    """Owns serial transport, command building, and low-level API requests."""

    def __init__(
        self,
        serial_connection: SerialConnection | None = None,
        command_builder: CommandBuilder | None = None,
    ) -> None:
        self.serial_connection = serial_connection or SerialConnection()
        self.command_builder = command_builder or CommandBuilder()

    @property
    def baudrate(self) -> int:
        return self.serial_connection.baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        self.serial_connection.baudrate = value

    @property
    def serial(self):
        """Expose the raw serial object for legacy tools during migration."""
        return self.serial_connection.serial

    def get_available_ports(self) -> list[str]:
        return self.serial_connection.get_available_ports()

    def connect(self, port: str, baudrate: int) -> bool:
        self.baudrate = baudrate
        return bool(self.serial_connection.connect(port))

    def disconnect(self) -> None:
        self.serial_connection.disconnect()

    def is_connected(self) -> bool:
        return bool(self.serial_connection.is_connected())

    def reset_input_buffer(self) -> None:
        serial_obj = self.serial
        if serial_obj and hasattr(serial_obj, "reset_input_buffer"):
            serial_obj.reset_input_buffer()

    def write(self, payload: bytearray) -> None:
        self.serial_connection.write(payload)

    def read_all(self) -> bytes:
        return self.serial_connection.read_all()

    def parse_rx_packets(self, rx_buffer: bytearray) -> tuple[list[dict], bytearray]:
        return parse_uart_rx_packets(rx_buffer)

    def get_command_bytes(self, command_name: str, fallback: list[int] | None = None) -> list[int]:
        if fallback is None:
            fallback = []
        return list(COMMANDS.get(command_name, fallback))

    def build_can_packet(self, target_node_id: int, command_bytes: list[int], sender_node_id: int = 0x01) -> bytearray:
        return self.command_builder.build_can_over_uart_packet(sender_node_id, target_node_id, command_bytes)

    def send_command_bytes(self, target_node_id: int, command_bytes: list[int], sender_node_id: int = 0x01) -> bytearray:
        payload = self.build_can_packet(target_node_id, command_bytes, sender_node_id)
        self.write(payload)
        return payload

    def send_named_command(self, command_name: str, target_node_id: int, sender_node_id: int = 0x01) -> bytearray:
        command_bytes = self.get_command_bytes(command_name)
        return self.send_command_bytes(target_node_id, command_bytes, sender_node_id)

    def send_node_id_request(self, node_id: int) -> bytearray:
        command_bytes = self.get_command_bytes("Get NodeIDRef", [0x86, 0x3F])
        return self.send_command_bytes(node_id, command_bytes)

    def send_mcu_version_query(self) -> bytearray:
        command_bytes = self.get_command_bytes("Get MCU Version")
        return self.send_command_bytes(0x01, command_bytes)

    def send_stop_motor(self, node_id: int) -> bytearray:
        command_bytes = self.get_command_bytes("Stop Motor", [0xDD])
        return self.send_command_bytes(node_id, command_bytes)

    def send_log_position_stop(self, node_id: int) -> bytearray:
        command_bytes = self.get_command_bytes("Set Log Position Stop", [0xE4, 0x3D, 0x00, 0x00])
        return self.send_command_bytes(node_id, command_bytes)

    def send_system_mode_query(self) -> bytearray:
        command_bytes = self.get_command_bytes("Get System Mode", [0xB5, 0x3F])
        return self.send_command_bytes(0x01, command_bytes)
