# serial/commands.py
"""Command building and sending utilities."""

from utils.checksum import fletcher_checksum
from utils.checksum import calc_checksum
from myconfig.constants import COMMANDS


class CommandBuilder:
    @staticmethod
    def build_can_over_uart_packet(sender: int, target: int, cmd_bytes: list) -> bytearray:
        """Build CAN-over-UART packet."""
        # Reverted: Index 2 is Sender ID, Index 3 is Target ID
        payload = [0x25, 0xA5, sender, target, 0x31, len(cmd_bytes)] + cmd_bytes

        chk_a, chk_b = calc_checksum(payload)
        payload += [chk_a, chk_b]

        return bytearray(payload)

    @staticmethod
    def get_command_bytes(command_name: str) -> list:
        """Get command bytes by command name."""
        return COMMANDS.get(command_name, [])

    def test_checksum(self):
        """Test the checksum calculation."""
        # ROBOT Off command
        data = [0x25, 0xA5, 0x01, 0x01, 0x31, 0x0A, 0x6F, 0x6E, 0x52, 0x42, 0x3D, 0x30, 0x0D, 0x0A, 0x0D, 0x0A]
        chk_a, chk_b = calc_checksum(bytes(data))
        chk_a2, chk_b2 = fletcher_checksum(bytes(data))
        return {
            "calc_checksum": (chk_a, chk_b),
            "fletcher_checksum": (chk_a2, chk_b2),
            "expected": (0x49, 0x3B),
        }
