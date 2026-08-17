"""TCP client for 4HEAT Lite module (2WC protocol)."""

import json
import logging
import socket

from .const import (
    QUERY_CONFIG,
    QUERY_SENSORS,
    REGISTER_TEMP,
    SOCKET_BUFFER,
    SOCKET_TIMEOUT,
    TCP_PORT,
    TEMP_MAX_RAW,
    TEMP_MIN_RAW,
    TEMP_WRITE_SUFFIX,
    WRITE_FUNCTION,
)

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteApi:
    """Communicate with a 4HEAT Lite module over TCP:80."""

    def __init__(self, host: str) -> None:
        self._host = host

    def _send(self, command: str) -> list:
        """Send a JSON command and return the parsed response."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(SOCKET_TIMEOUT)
        try:
            s.connect((self._host, TCP_PORT))
            s.send(command.encode())
            raw = s.recv(SOCKET_BUFFER).decode()
        finally:
            s.close()
        return json.loads(raw)

    def _query(self, command: str, min_hex_len: int = 4) -> str | None:
        """Send a 2WC query and return hex payload, or None on failure."""
        try:
            response = self._send(command)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOGGER.debug("Query failed: %s", exc)
            return None

        if not isinstance(response, list) or len(response) < 3:
            return None
        if response[0] == "ERR":
            _LOGGER.warning("Module returned error: %s", response)
            return None

        hexdata = response[2]
        if not hexdata or len(hexdata) < min_hex_len:
            return None
        return hexdata

    def query_sensors(self) -> dict | None:
        """Query main sensor block (0310) and decode into a dict."""
        hexdata = self._query(QUERY_SENSORS, min_hex_len=38)
        if hexdata is None:
            return None
        return self._decode_0310(hexdata)

    def query_config(self) -> dict | None:
        """Query target temp (12/005a) and power (0e/016c)."""
        result = {}
        hexdata = self._query(QUERY_CONFIG["target_temp"], min_hex_len=34)
        if hexdata:
            vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
            result["target_temp"] = ((vals[3] << 8) | vals[4]) / 10.0

        hexdata = self._query(QUERY_CONFIG["power"], min_hex_len=34)
        if hexdata:
            vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
            result["power"] = (vals[5] << 8) | vals[6]

        return result if result else None

    def test_connection(self) -> bool:
        """Test if the module responds to a 2WC query."""
        result = self.query_sensors()
        return result is not None

    @staticmethod
    def _decode_0310(hexdata: str) -> dict:
        """Decode the 0310 sensor response (19 bytes / 38 hex chars).

        Confirmed register map (Lasian Eriste air stove):
          Byte  0: header (0x10)
          Byte  1: error code (0=none)
          Byte  2: on/off flag (0=off, 1=on)
          Byte  4: exhaust temperature (°C, 1 byte)
          Byte  5: operating state (0=OFF, 5=Run, 6=Modulation, etc.)
          Bytes 10-11: room temperature (big-endian, 0.1°C)
        """
        vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
        room_raw = (vals[10] << 8) | vals[11]

        return {
            "state": vals[5],
            "error": vals[1],
            "on_off": vals[2],
            "exhaust_temp": vals[4],
            "room_temp": room_raw / 10.0,
            "raw": vals,
        }

    @staticmethod
    def build_temp_command(temp_c: float) -> list:
        """Build write command for target temperature register (12/005a)."""
        raw = int(round(temp_c * 10))
        raw = max(TEMP_MIN_RAW, min(TEMP_MAX_RAW, raw))
        temp_hex = f"{raw:04x}"
        min_hex = f"{TEMP_MIN_RAW:04x}"
        max_hex = f"{TEMP_MAX_RAW:04x}"
        data = f"{WRITE_FUNCTION}{REGISTER_TEMP}{temp_hex}{min_hex}{max_hex}{TEMP_WRITE_SUFFIX}"
        return ["2WC", "1", data]

    @staticmethod
    def build_power_command(level: int) -> list:
        """Build write command for combustion power level (register 0e/016c, range 1-7)."""
        level = max(1, min(7, level))
        level_hex = f"{level:04x}"
        data = f"050e016c{level_hex}0001000700"
        return ["2WC", "1", data]

    @staticmethod
    def build_on_command() -> list:
        """Build ON command (accensione from FileMap)."""
        return ["2WC", "1", "05040000"]

    @staticmethod
    def build_off_command() -> list:
        """Build OFF command (spegnimento from FileMap)."""
        return ["2WC", "1", "05050000"]
