# serial_conn/connection.py
"""Serial connection management."""

from datetime import datetime
import os

import serial
import serial.tools.list_ports


class SerialConnection:
    def __init__(self):
        self.serial = None
        self.serial_virt = None
        self.baudrate = 345600
        self.timeout = 0.1
        self.log_file = "biobot_serial.log"
        self.connected = False

    def _log(self, level: str, message: str):
        """Write serial diagnostics to a small local log file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = f"[{timestamp}] [{level}] {message}"

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(log_entry + os.linesep)
        except Exception:
            print(log_entry)

    def _get_target(self, is_virt: bool = False):
        return self.serial_virt if is_virt else self.serial

    def _set_target(self, serial_obj, is_virt: bool = False):
        if is_virt:
            self.serial_virt = serial_obj
        else:
            self.serial = serial_obj
            self.connected = bool(serial_obj and serial_obj.is_open)

    def connect(self, port: str, is_virt: bool = False) -> bool:
        """Establish a serial connection."""
        port_type = "virtual" if is_virt else "physical"

        if not isinstance(port, str) or not port.strip():
            self._log("ERROR", f"Invalid {port_type} port: {port!r}")
            return False

        try:
            serial_obj = serial.Serial(
                port=port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )

            if not serial_obj.is_open:
                self._log("ERROR", f"{port_type.title()} port {port} did not open")
                return False

            try:
                serial_obj.reset_input_buffer()
                serial_obj.reset_output_buffer()
            except serial.SerialException as exc:
                self._log("WARNING", f"Could not reset {port_type} buffers: {exc}")

            old_target = self._get_target(is_virt)
            if old_target and old_target is not serial_obj:
                try:
                    old_target.close()
                except serial.SerialException as exc:
                    self._log("WARNING", f"Could not close previous {port_type} port: {exc}")

            self._set_target(serial_obj, is_virt)
            self._log("INFO", f"Connected {port_type} port {port} at {self.baudrate} baud")
            return True

        except serial.SerialException as exc:
            self._log("ERROR", f"Serial connection failed for {port_type} port {port}: {exc}")
        except Exception as exc:
            self._log("ERROR", f"Unexpected connection error for {port_type} port {port}: {exc}")

        if not is_virt:
            self.connected = False
        return False

    def disconnect(self, is_virt: bool = False):
        """Close the serial connection."""
        port_type = "virtual" if is_virt else "physical"
        target = self._get_target(is_virt)

        if target:
            try:
                target.close()
                self._log("INFO", f"Disconnected {port_type} port")
            except serial.SerialException as exc:
                self._log("ERROR", f"Serial error closing {port_type} port: {exc}")
            except Exception as exc:
                self._log("ERROR", f"Unexpected error closing {port_type} port: {exc}")

        self._set_target(None, is_virt)

    def is_connected(self, is_virt: bool = False) -> bool:
        """Check if the selected serial connection is open."""
        target = self._get_target(is_virt)
        try:
            is_open = bool(target and target.is_open)
        except serial.SerialException as exc:
            self._log("ERROR", f"Serial error checking connection: {exc}")
            is_open = False

        if not is_virt:
            self.connected = is_open
        return is_open

    def write(self, data, is_virt: bool = False) -> int:
        """Write bytes to the selected serial port."""
        port_type = "virtual" if is_virt else "physical"

        if not isinstance(data, (bytes, bytearray, memoryview)):
            self._log("ERROR", f"Invalid write data type: {type(data).__name__}")
            return 0

        if not data:
            return 0

        target = self._get_target(is_virt)
        if not target or not target.is_open:
            self._log("WARNING", f"No open {port_type} port to write to")
            return 0

        try:
            written = target.write(data)
            if written != len(data):
                self._log("WARNING", f"Partial write on {port_type} port: {written}/{len(data)} bytes")
            return written
        except serial.SerialException as exc:
            self._log("ERROR", f"Serial write failed on {port_type} port: {exc}")
        except Exception as exc:
            self._log("ERROR", f"Unexpected write error on {port_type} port: {exc}")

        if not is_virt:
            self.connected = False
        return 0

    def read_all(self, is_virt: bool = False) -> bytes:
        """Read all currently available bytes from the selected serial port."""
        port_type = "virtual" if is_virt else "physical"
        target = self._get_target(is_virt)

        if not target or not target.is_open:
            return b""

        try:
            return target.read_all()
        except serial.SerialException as exc:
            self._log("ERROR", f"Serial read failed on {port_type} port: {exc}")
        except Exception as exc:
            self._log("ERROR", f"Unexpected read error on {port_type} port: {exc}")

        if not is_virt:
            self.connected = False
        return b""

    def get_available_ports(self):
        """Get list of available serial ports."""
        try:
            return [port.device for port in serial.tools.list_ports.comports()]
        except serial.SerialException as exc:
            self._log("ERROR", f"Serial error listing ports: {exc}")
        except Exception as exc:
            self._log("ERROR", f"Unexpected error listing ports: {exc}")
        return []
