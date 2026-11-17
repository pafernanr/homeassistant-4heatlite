"""TCP client for 4HEAT Lite module (2WC protocol)."""

import json
import logging
import socket
import threading
import time

from .const import (
    BAND_NAMES,
    CCS_PERIODS,
    CCS_SLOTS_PER_GROUP,
    CCS_WEEKDAYS,
    CCS_WEEKEND_DAYS,
    DAY_NAMES,
    DAY_OFFSETS,
    FAN_REGISTERS,
    MINUTES_PER_DAY,
    PROTOCOL_CCS,
    PROTOCOL_H24,
    QUERY_CONFIG,
    QUERY_EXHAUST,
    QUERY_MODULE_INFO,
    QUERY_RETRIES,
    QUERY_RETRY_DELAY,
    QUERY_SCHEDULE,
    QUERY_SENSORS,
    REGISTER_EXHAUST,
    REGISTER_HEATING,
    REGISTER_MODULE_INFO,
    REGISTER_POWER,
    REGISTER_SENSORS,
    REGISTER_TEMP,
    SCHEDULE_PROTOCOLS,
    SOCKET_BUFFER,
    SOCKET_TIMEOUT,
    TCP_PORT,
    TEMP_MAX_RAW,
    TEMP_MIN_RAW,
    TEMP_SCALE,
    TEMP_WRITE_SUFFIX,
    WHOLE_DEGREE_MAX_RAW,
    WRITE_FUNCTION,
)

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteApi:
    """Communicate with a 4HEAT Lite module over TCP:80."""

    def __init__(self, host: str) -> None:
        self._host = host
        # The module serves one TCP exchange at a time: polls, commands and
        # schedule reads come from different executor threads.
        self._lock = threading.Lock()
        # 10 = temperatures in 0.1 °C (Lasian), 1 = whole °C (Jollymec).
        # Detected from the target register's range on each config read.
        self.temp_divisor = 10
        self.temp_range: tuple[int, int] | None = None
        self.power_range: tuple[int, int] | None = None
        # data key -> (min, max) of each fan register the stove answers for
        self.fan_ranges: dict[str, tuple[int, int]] = {}
        # the panel's fan setting, when configured (DEFAULT_FAN_REGISTER); signed
        self.fan_register: str | None = None
        self.fan_setting_range: tuple[int, int] | None = None
        # heating setting (0e/023f): OFF..7, 7 = Auto
        self.heating_setting_range: tuple[int, int] | None = None
        # last record read per register: on whole-degree stoves a write must send
        # the record back whole, or the module keeps it and the board never sees it
        self._records: dict[str, str] = {}

    def _send(self, command: str) -> list:
        """Send a JSON command and return the parsed response.

        A reply can span several TCP segments (some modules answer with their
        whole register cache), so read until it parses as JSON.
        """
        with self._lock:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(SOCKET_TIMEOUT)
            try:
                s.connect((self._host, TCP_PORT))
                s.send(command.encode())
                raw = b""
                while chunk := s.recv(SOCKET_BUFFER):
                    raw += chunk
                    try:
                        return json.loads(raw.decode())
                    except ValueError:
                        continue
            finally:
                s.close()
        return json.loads(raw.decode())

    def send_command(self, cmd: list) -> list | None:
        """Send a command via TCP and return the parsed response."""
        try:
            return self._send(json.dumps(cmd, separators=(",", ":")))
        except (OSError, ValueError, json.JSONDecodeError):
            _LOGGER.warning("TCP command failed: %s", cmd)
            return None

    def _query(
        self, command: str, min_hex_len: int = 4, register: str | None = None
    ) -> str | None:
        """Send a 2WC query and return hex payload, or None on failure.

        The module answers ["ERR","1","4"] now and then while busy, so the
        query is retried. With ``register``, the payload must start with it:
        some modules answer a single-register read with their whole cache,
        and the requested record is picked out of it.
        """
        for attempt in range(QUERY_RETRIES + 1):
            if attempt:
                time.sleep(QUERY_RETRY_DELAY)
            try:
                response = self._send(command)
            except (OSError, ValueError) as exc:
                _LOGGER.debug("Query %s failed: %s", command, exc)
                continue

            if not isinstance(response, list) or len(response) < 3:
                continue
            if response[0] == "ERR":
                _LOGGER.debug("Module returned error: %s", response)
                continue

            for hexdata in response[2:]:
                if not isinstance(hexdata, str) or len(hexdata) < min_hex_len:
                    continue
                if register is None or hexdata.startswith(register):
                    if register and len(register) == 6:
                        self._records[register] = hexdata
                    return hexdata
            _LOGGER.debug("Register %s not in response: %s", register, response)

        _LOGGER.warning(
            "Query %s failed after %d attempts", command, QUERY_RETRIES + 1
        )
        return None

    @staticmethod
    def _decode_register(hexdata: str) -> tuple[int, int, int]:
        """Split a 12/xxxx or 0e/xxxx record into (value, min, max).

        Layout: <group + address, 3 bytes> <value, 2> <min, 2> <max, 2> ...
        """
        vals = bytes.fromhex(hexdata[:18])
        return (
            int.from_bytes(vals[3:5], "big"),
            int.from_bytes(vals[5:7], "big"),
            int.from_bytes(vals[7:9], "big"),
        )

    @staticmethod
    def _decode_signed(hexdata: str) -> tuple[int, int, int]:
        """Like _decode_register, two's complement: fff9 = -7."""
        vals = bytes.fromhex(hexdata[:18])
        return (
            int.from_bytes(vals[3:5], "big", signed=True),
            int.from_bytes(vals[5:7], "big", signed=True),
            int.from_bytes(vals[7:9], "big", signed=True),
        )

    def query_sensors(self) -> dict | None:
        """Query main sensor block (0310) and decode into a dict."""
        hexdata = self._query(QUERY_SENSORS, min_hex_len=38, register=REGISTER_SENSORS)
        if hexdata is None:
            return None
        data = self._decode_0310(hexdata, self.temp_divisor)

        # 0310 byte 4 stays 0 on some stoves (Jollymec); 12/ffff carries the
        # exhaust temperature on every stove seen so far, on two bytes.
        hexdata = self._query(QUERY_EXHAUST, min_hex_len=18, register=REGISTER_EXHAUST)
        if hexdata:
            data["exhaust_temp"] = self._decode_register(hexdata)[0]
        return data

    def query_config(self) -> dict | None:
        """Query target temp (12/005a) and power (0e/016c).

        The target register's range also gives the stove's temperature unit:
        100-400 on 0.1 °C stoves, 10-40 on whole-degree ones. None if either
        register did not answer.
        """
        target = self._query(
            QUERY_CONFIG["target_temp"], min_hex_len=18, register=REGISTER_TEMP
        )
        power = self._query(
            QUERY_CONFIG["power"], min_hex_len=18, register=REGISTER_POWER
        )
        if not target or not power:
            return None
        result = {}
        value, low, high = self._decode_register(target)
        if high:
            self.temp_divisor = 1 if high <= WHOLE_DEGREE_MAX_RAW else 10
            self.temp_range = (low, high)
        result["target_temp"] = value / self.temp_divisor

        value, low, high = self._decode_register(power)
        if high:
            self.power_range = (low, high)
        result["power"] = value
        return result

    def query_fans(self) -> dict | None:
        """Query the fan level registers (ducted fans 1-2).

        Each is a 0e record with its own range. None if any did not answer.
        """
        result = {}
        for key, register in FAN_REGISTERS.items():
            hexdata = self._query(f'["2WC","1","03{register}"]', min_hex_len=18, register=register)
            if not hexdata:
                return None
            value, low, high = self._decode_register(hexdata)
            if high:
                self.fan_ranges[key] = (low, high)
            result[key] = value
        return result

    def query_live_power(self) -> dict | None:
        """Query the running power level from state_info (0c81), liv_pot.

        Byte 3 is an ASCII digit: 0x32 is power 2. None if the reply is missing
        or not a digit.
        """
        hexdata = self._query(
            QUERY_MODULE_INFO, min_hex_len=8, register=REGISTER_MODULE_INFO
        )
        if not hexdata:
            return None
        digit = bytes.fromhex(hexdata[:8])[3]
        if not 0x30 <= digit <= 0x39:
            return None
        return {"live_power": digit - 0x30}

    def query_fan_setting(self) -> dict | None:
        """Query the panel's fan setting, if a register is configured.

        Signed, with the range the record carries (-7..+7 on a Ferlux).
        {} when no register is configured, None when the read failed.
        """
        if not self.fan_register:
            return {}
        register = self.fan_register
        hexdata = self._query(f'["2WC","1","03{register}"]', min_hex_len=18, register=register)
        if not hexdata:
            return None
        value, low, high = self._decode_signed(hexdata)
        if low < high:
            self.fan_setting_range = (low, high)
        # the heating fan power sensor shows the panel's fan setting
        return {"fan_setting": value, "heating_fan_power": value}

    def query_heating_setting(self) -> dict | None:
        """Query the heating setting (0e/023f): unsigned, OFF..7, 7 = Auto. None on failure."""
        hexdata = self._query(
            f'["2WC","1","03{REGISTER_HEATING}"]', min_hex_len=18, register=REGISTER_HEATING
        )
        if not hexdata:
            return None
        value, low, high = self._decode_register(hexdata)
        if high:
            self.heating_setting_range = (low, high)
        return {"heating_setting": value}

    def test_connection(self) -> bool:
        """Test if the module responds to a 2WC query."""
        result = self.query_sensors()
        return result is not None

    @staticmethod
    def _decode_0310(hexdata: str, temp_divisor: int = 10) -> dict:
        """Decode the 0310 sensor response (19 bytes / 38 hex chars).

        Confirmed register map (Lasian Eriste air stove):
          Byte  0: header (0x10)
          Byte  1: error code (0=none)
          Byte  2: on/off flag (0=off, 1=on)
          Byte  4: exhaust temperature (°C, 1 byte; always 0 on Jollymec)
          Byte  5: operating state (0=OFF, 5=Run, 6=Modulation, etc.)
          Bytes 10-11: room temperature (big-endian, 0.1°C or whole °C)
        """
        vals = [int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)]
        room_raw = (vals[10] << 8) | vals[11]

        return {
            "state": vals[5],
            "error": vals[1],
            "on_off": vals[2],
            "exhaust_temp": vals[4],
            "room_temp": room_raw / temp_divisor,
            "raw": vals,
        }

    def _record_frame(self, register: str, value: int) -> list | None:
        """Write frame = 05 + the record last read, with only the value replaced.

        On a whole-degree stove the short frame (value, min, max, 0000) is echoed
        by the module but does not always reach the board: verified on the panel,
        the target only changed with the whole record. 0.1 °C stoves keep the
        frames they were verified with.
        """
        if self.temp_divisor != 1:
            return None
        return self._whole_record(register, value)

    def _whole_record(self, register: str, value: int) -> list | None:
        """05 + the record last read with the value replaced, or None if unread."""
        record = self._records.get(register)
        if not record or len(record) < 18:
            return None
        return ["2WC", "1", f"{WRITE_FUNCTION}{record[:6]}{value & 0xFFFF:04x}{record[10:]}"]

    def build_temp_command(self, temp_c: float) -> list:
        """Build write command for target temperature register (12/005a).

        Whole-degree stoves get the frame verified on a Jollymec, with the
        range read back from the register; 0.1 °C stoves keep the Lasian frame.
        """
        if self.temp_divisor == 1 and self.temp_range:
            low, high = self.temp_range
            raw = max(low, min(high, int(round(temp_c))))
            frame = self._record_frame(REGISTER_TEMP, raw)
            if frame:
                return frame
            data = f"{WRITE_FUNCTION}{REGISTER_TEMP}{raw:04x}{low:04x}{high:04x}0000"
            return ["2WC", "1", data]

        raw = int(round(temp_c * 10))
        raw = max(TEMP_MIN_RAW, min(TEMP_MAX_RAW, raw))
        temp_hex = f"{raw:04x}"
        min_hex = f"{TEMP_MIN_RAW:04x}"
        max_hex = f"{TEMP_MAX_RAW:04x}"
        data = f"{WRITE_FUNCTION}{REGISTER_TEMP}{temp_hex}{min_hex}{max_hex}{TEMP_WRITE_SUFFIX}"
        return ["2WC", "1", data]

    def build_power_command(self, level: int) -> list:
        """Build write command for combustion power level (register 0e/016c).

        The level is clamped to the range the stove reports (1-6 on Jollymec),
        1-7 until the register has been read.
        """
        low, high = self.power_range or (1, 7)
        level = max(low, min(high, level))
        frame = self._record_frame(REGISTER_POWER, level)
        if frame:
            return frame
        level_hex = f"{level:04x}"
        data = f"050e016c{level_hex}0001000700"
        return ["2WC", "1", data]

    def build_fan_setting_command(self, value: int) -> list | None:
        """Write the panel's fan setting: the whole record, value replaced.

        Verified on a Ferlux (0e038c): +5 -> +2 changed on the panel. None
        until the register has been read.
        """
        if not self.fan_register:
            return None
        if self.fan_setting_range:
            low, high = self.fan_setting_range
            value = max(low, min(high, value))
        return self._whole_record(self.fan_register, value)

    def build_heating_setting_command(self, value: int) -> list | None:
        """Write the heating setting (0e/023f): the whole record, value replaced.

        None until the register has been read.
        """
        if self.heating_setting_range:
            low, high = self.heating_setting_range
            value = max(low, min(high, value))
        return self._whole_record(REGISTER_HEATING, value)

    def decode_echo(self, records: list) -> dict:
        """Decode the register records a write reply carries.

        Covers the writable registers (target temperature, power, the fan
        setting) and the declared fans, should a reply carry them.
        """
        result = {}
        for hexdata in records:
            if not isinstance(hexdata, str) or len(hexdata) < 18:
                continue
            self._records[hexdata[:6]] = hexdata
            value = self._decode_register(hexdata)[0]
            if self.fan_register and hexdata.startswith(self.fan_register):
                result["fan_setting"] = self._decode_signed(hexdata)[0]
            elif hexdata.startswith(REGISTER_TEMP):
                result["target_temp"] = value / self.temp_divisor
            elif hexdata.startswith(REGISTER_POWER):
                result["power"] = value
            else:
                for key, register in FAN_REGISTERS.items():
                    if hexdata.startswith(register):
                        result[key] = value
        return result

    @staticmethod
    def build_on_command() -> list:
        """Build ON command (accensione from FileMap)."""
        return ["2WC", "1", "05040000"]

    @staticmethod
    def build_off_command() -> list:
        """Build OFF command (spegnimento from FileMap)."""
        return ["2WC", "1", "05050000"]

    @staticmethod
    def build_disable_schedule_command(
        schedule: dict | None = None, program_index: int = 0
    ) -> list:
        """Build H24 command with no active slots (two OFF transitions)."""
        if schedule:
            eco = int(round(schedule.get("eco", 18) * TEMP_SCALE))
            comfort = int(round(schedule.get("comfort", 22) * TEMP_SCALE))
            comfort2 = int(round(schedule.get("comfort2", 24) * TEMP_SCALE))
        else:
            eco, comfort, comfort2 = 180, 220, 240
        return [
            "H24", "9", "#13", str(program_index),
            str(eco), str(comfort), str(comfort2),
            "0", "0", "0", "0",
        ]

    @staticmethod
    def is_command_rejected(result) -> bool:
        """True if the stove answered ERR (busy, code 4, is not a rejection)."""
        return (
            isinstance(result, list)
            and bool(result)
            and str(result[0]) == "ERR"
            and str(result[-1]) != "4"
        )

    def query_schedule(self) -> dict | None:
        """Query the module's schedule (CCG query) and parse H24 or CCS."""
        try:
            response = self._send(QUERY_SCHEDULE)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOGGER.debug("Schedule query failed: %s", exc)
            return None
        parsed = self.parse_schedule_response(response)
        if parsed is None:
            _LOGGER.warning(
                "Unsupported or malformed schedule response: %s", response
            )
        return parsed

    @staticmethod
    def parse_schedule_response(response) -> dict | None:
        """Parse an H24 or CCS/CCG schedule response; None if unsupported."""
        if not isinstance(response, list) or not response:
            return None
        token = str(response[0])
        if token == "H24":
            return FourHeatLiteApi.parse_h24_response(response)
        if token in ("CCS", "CCG"):
            return FourHeatLiteApi.parse_ccs_response(response)
        return None

    @staticmethod
    def _time_to_minutes(value) -> int | None:
        """Minutes since midnight for a strict HH:MM string, else None."""
        if not isinstance(value, str):
            return None
        parts = value.split(":")
        if len(parts) != 2:
            return None
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour * 60 + minute

    @staticmethod
    def parse_ccs_response(response: list) -> dict | None:
        """Parse a CCS/CCG response into a user-facing dict (period + slots)."""
        day_fields = 1 + CCS_SLOTS_PER_GROUP * 3
        if (
            not isinstance(response, list)
            or len(response) < 3 + len(DAY_NAMES) * day_fields
        ):
            return None
        try:
            period_raw = int(response[2])
        except (TypeError, ValueError):
            return None
        period = next((k for k, v in CCS_PERIODS.items() if v == period_raw), None)
        if period is None:
            return None

        days: dict[str, list] = {}
        for i, day in enumerate(DAY_NAMES):
            base = 3 + i * day_fields
            try:
                if int(response[base]) != i + 1:
                    return None
            except (TypeError, ValueError):
                return None
            slots = []
            for j in range(CCS_SLOTS_PER_GROUP):
                start, end, check = response[
                    base + 1 + j * 3: base + 4 + j * 3
                ]
                if (
                    FourHeatLiteApi._time_to_minutes(start) is None
                    or FourHeatLiteApi._time_to_minutes(end) is None
                ):
                    return None
                enabled = str(check) == "1"
                if start == end == "00:00" and not enabled:
                    continue
                slots.append({"start": start, "end": end, "enabled": enabled})
            days[day] = slots

        result: dict = {"protocol": PROTOCOL_CCS, "period": period}
        if period == "weekly":
            result["weekly_slots"] = days["mon"]
        elif period == "weekend":
            result["workday_slots"] = days["mon"]
            result["weekend_slots"] = days["sat"]
        else:
            result["daily_slots"] = {d: s for d, s in days.items() if s}
        return result

    @staticmethod
    def build_ccs_command(schedule: dict) -> list:
        """Encode a user-facing CCS schedule dict into a CCS command array."""
        period = schedule.get("period", "off")
        per_day: dict[str, list] = {day: [] for day in DAY_NAMES}
        if period == "daily":
            for day, slots in (schedule.get("daily_slots") or {}).items():
                per_day[day] = list(slots or [])
        elif period == "weekly":
            for day in DAY_NAMES:
                per_day[day] = list(schedule.get("weekly_slots") or [])
        elif period == "weekend":
            for day in CCS_WEEKDAYS:
                per_day[day] = list(schedule.get("workday_slots") or [])
            for day in CCS_WEEKEND_DAYS:
                per_day[day] = list(schedule.get("weekend_slots") or [])

        data = []
        for i, day in enumerate(DAY_NAMES):
            data.append(str(i + 1))
            slots = per_day[day]
            for j in range(CCS_SLOTS_PER_GROUP):
                if j < len(slots):
                    start = FourHeatLiteApi._time_to_minutes(slots[j]["start"])
                    end = FourHeatLiteApi._time_to_minutes(slots[j]["end"])
                    data.extend([
                        f"{start // 60:02d}:{start % 60:02d}",
                        f"{end // 60:02d}:{end % 60:02d}",
                        "1" if slots[j].get("enabled", True) else "0",
                    ])
                else:
                    data.extend(["00:00", "00:00", "0"])
        return ["CCS", str(len(data) + 1), str(CCS_PERIODS[period]), *data]

    @staticmethod
    def build_disable_ccs_command() -> list:
        """Build CCS command with period 0 (disabled) and no slots."""
        return FourHeatLiteApi.build_ccs_command({"period": "off"})

    @staticmethod
    def _validate_ccs_slots(slots) -> str | None:
        """Validate one list of CCS slots (a group). Returns error or None."""
        if slots is None:
            return None
        if not isinstance(slots, list):
            return "invalid_schedule"
        if len(slots) > CCS_SLOTS_PER_GROUP:
            return "too_many_slots"
        enabled_ranges = []
        for slot in slots:
            if not isinstance(slot, dict):
                return "invalid_schedule"
            start = FourHeatLiteApi._time_to_minutes(slot.get("start"))
            end = FourHeatLiteApi._time_to_minutes(slot.get("end"))
            if start is None or end is None or start >= end:
                return "invalid_time"
            enabled = slot.get("enabled", True)
            if not isinstance(enabled, bool):
                return "invalid_schedule"
            if enabled:
                enabled_ranges.append((start, end))
        enabled_ranges.sort()
        for i in range(len(enabled_ranges) - 1):
            if enabled_ranges[i][1] > enabled_ranges[i + 1][0]:
                return "overlapping_slots"
        return None

    @staticmethod
    def validate_ccs_schedule(data) -> str | None:
        """Validate a CCS schedule dict. Returns error string or None."""
        if not isinstance(data, dict):
            return "invalid_schedule"
        period = data.get("period")
        if period not in ("daily", "weekly", "weekend"):
            return "invalid_schedule"
        if period == "daily":
            daily = data.get("daily_slots")
            if daily is None:
                return None
            if not isinstance(daily, dict):
                return "invalid_schedule"
            for day, slots in daily.items():
                if day not in DAY_NAMES:
                    return "invalid_day"
                err = FourHeatLiteApi._validate_ccs_slots(slots)
                if err:
                    return err
            return None
        keys = ("weekly_slots",) if period == "weekly" else (
            "workday_slots", "weekend_slots"
        )
        for key in keys:
            err = FourHeatLiteApi._validate_ccs_slots(data.get(key))
            if err:
                return err
        return None

    @staticmethod
    def default_schedule_entry(protocol: str, name: str = "Schedule 1") -> dict:
        """Disabled starter entry for a protocol."""
        if protocol == PROTOCOL_CCS:
            return {
                "name": name,
                "active": False,
                "period": "weekly",
                "weekly_slots": [
                    {"start": "08:00", "end": "10:00", "enabled": False},
                    {"start": "13:00", "end": "15:00", "enabled": False},
                    {"start": "19:30", "end": "21:30", "enabled": False},
                ],
            }
        return {
            "name": name,
            "active": False,
            "eco": 18,
            "comfort": 21,
            "comfort2": 23,
            "slots": [],
        }

    @staticmethod
    def schedules_from_stove(parsed: dict | None) -> dict:
        """Build the options structure, seeded from the stove's schedule.

        The detected protocol gets the stove's schedule; the other protocol
        gets a disabled starter entry. Nothing is written to the stove.
        """
        result = {
            "protocol": PROTOCOL_H24,
            PROTOCOL_H24: [FourHeatLiteApi.default_schedule_entry(PROTOCOL_H24)],
            PROTOCOL_CCS: [FourHeatLiteApi.default_schedule_entry(PROTOCOL_CCS)],
        }
        protocol = (parsed or {}).get("protocol")
        if protocol == PROTOCOL_H24:
            entry = {
                "name": "Stove",
                "active": bool(parsed["slots"]),
                "eco": parsed["eco"],
                "comfort": parsed["comfort"],
                "comfort2": parsed["comfort2"],
                "slots": parsed["slots"],
            }
            if entry["active"] and FourHeatLiteApi.validate_schedule(entry):
                entry["active"] = False
            result[PROTOCOL_H24] = [entry]
        elif protocol == PROTOCOL_CCS:
            entry = {
                k: v for k, v in parsed.items() if k not in ("protocol", "period")
            }
            off = parsed["period"] == "off"
            entry = {
                "name": "Stove",
                "active": not off,
                "period": "daily" if off else parsed["period"],
                **entry,
            }
            result[PROTOCOL_CCS] = [entry]
            result["protocol"] = PROTOCOL_CCS
        return result

    @staticmethod
    def _schedule_signature(entry: dict) -> str:
        """Comparable form of an entry, ignoring name, active and protocol."""

        def norm(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, dict):
                return {k: norm(v) for k, v in value.items()}
            if isinstance(value, list):
                return [norm(v) for v in value]
            return value

        data = {
            k: v for k, v in entry.items() if k not in ("name", "active", "protocol")
        }
        return json.dumps(norm(data), sort_keys=True)

    @staticmethod
    def merge_stove_schedule(config, parsed: dict | None) -> dict:
        """Merge the schedule read from the stove into the stored config.

        The stove is the source of truth. The entry matching the stove
        schedule becomes the only active one; if none matches, the stove
        schedule is appended to the end of its protocol section. A disabled
        stove schedule leaves every entry inactive. Returns a new dict.
        """
        if not isinstance(config, dict):
            config = FourHeatLiteApi.schedules_from_stove(parsed)
            return config

        result = {"protocol": config.get("protocol", PROTOCOL_H24)}
        for proto in SCHEDULE_PROTOCOLS:
            entries = config.get(proto)
            result[proto] = [
                {**e, "active": False} if isinstance(e, dict) else e
                for e in (entries if isinstance(entries, list) else [])
            ]
            if not result[proto]:
                result[proto] = [FourHeatLiteApi.default_schedule_entry(proto)]

        protocol = (parsed or {}).get("protocol")
        if protocol not in SCHEDULE_PROTOCOLS:
            return result

        result["protocol"] = protocol
        seeded = FourHeatLiteApi.schedules_from_stove(parsed)[protocol][0]
        if not seeded["active"]:
            return result

        signature = FourHeatLiteApi._schedule_signature(seeded)
        for entry in result[protocol]:
            if isinstance(entry, dict) and (
                FourHeatLiteApi._schedule_signature(entry) == signature
            ):
                entry["active"] = True
                return result

        names = {e.get("name") for e in result[protocol] if isinstance(e, dict)}
        name, n = "Stove", 2
        while name in names:
            name, n = f"Stove {n}", n + 1
        seeded["name"] = name
        # Drop untouched starter entries so they do not pile up.
        defaults = FourHeatLiteApi._schedule_signature(
            FourHeatLiteApi.default_schedule_entry(protocol)
        )
        result[protocol] = [
            e
            for e in result[protocol]
            if not (
                isinstance(e, dict)
                and FourHeatLiteApi._schedule_signature(e) == defaults
            )
        ]
        result[protocol].append(seeded)
        return result

    @staticmethod
    def get_active_schedule(config) -> tuple[str, int, dict] | None:
        """(protocol, index, entry) of the active schedule, or None."""
        if not isinstance(config, dict):
            return None
        for protocol in SCHEDULE_PROTOCOLS:
            for index, entry in enumerate(config.get(protocol) or []):
                if isinstance(entry, dict) and entry.get("active"):
                    return protocol, index, entry
        return None

    @staticmethod
    def validate_schedules_config(data) -> str | None:
        """Validate the whole schedules option. Returns error string or None."""
        if not isinstance(data, dict):
            return "invalid_schedule"
        protocol = data.get("protocol", PROTOCOL_H24)
        if protocol not in SCHEDULE_PROTOCOLS:
            return "invalid_protocol"

        active = {PROTOCOL_H24: 0, PROTOCOL_CCS: 0}
        for proto in SCHEDULE_PROTOCOLS:
            entries = data.get(proto)
            if entries is None:
                continue
            if not isinstance(entries, list):
                return "invalid_schedule"
            for entry in entries:
                if not isinstance(entry, dict):
                    return "invalid_schedule"
                if proto == PROTOCOL_H24:
                    err = (
                        FourHeatLiteApi.validate_schedule(entry)
                        if entry.get("slots") or entry.get("active")
                        else None
                    )
                else:
                    err = FourHeatLiteApi.validate_ccs_schedule(entry)
                if err:
                    return err
                if entry.get("active"):
                    active[proto] += 1

        if active[PROTOCOL_H24] and active[PROTOCOL_CCS]:
            return "both_protocols_active"
        if max(active.values()) > 1:
            return "multiple_active"
        for proto, count in active.items():
            if count and proto != protocol:
                return "protocol_mismatch"
        return None

    @staticmethod
    def parse_h24_response(response: list) -> dict | None:
        """Parse an H24 schedule response into a user-facing dict."""
        if not isinstance(response, list) or len(response) < 8:
            return None
        if str(response[0]) != "H24":
            return None

        offset = 1 if str(response[2]).startswith("#") else 0
        try:
            program_index = int(response[2 + offset])
            eco_raw = int(response[3 + offset])
            comfort_raw = int(response[4 + offset])
            comfort2_raw = int(response[5 + offset])
        except (ValueError, IndexError):
            return None

        band_map = {}
        if eco_raw:
            band_map[eco_raw] = "eco"
        if comfort_raw:
            band_map[comfort_raw] = "comfort"
        if comfort2_raw:
            band_map[comfort2_raw] = "comfort2"

        transitions = []
        start_idx = 6 + offset
        for i in range(start_idx, len(response) - 1, 2):
            try:
                minute = int(response[i])
                temp = int(response[i + 1])
            except (ValueError, IndexError):
                break
            transitions.append((minute, temp))

        slots_raw = []
        current_band = None
        slot_start = None
        for minute, temp in transitions:
            band = band_map.get(temp)
            if band and current_band is None:
                current_band = band
                slot_start = minute
            elif (band is None or band != current_band) and current_band is not None:
                slots_raw.append((slot_start, minute, current_band))
                if band:
                    current_band = band
                    slot_start = minute
                else:
                    current_band = None
                    slot_start = None
        if current_band is not None and slot_start is not None:
            slots_raw.append((slot_start, MINUTES_PER_DAY * 7, current_band))

        def _minute_to_day_time(m):
            day_idx = m // MINUTES_PER_DAY
            day_m = m % MINUTES_PER_DAY
            day = DAY_NAMES[day_idx] if day_idx < 7 else DAY_NAMES[6]
            return day, f"{day_m // 60:02d}:{day_m % 60:02d}"

        day_slots = {}
        for start_m, end_m, band in slots_raw:
            day, start_t = _minute_to_day_time(start_m)
            _, end_t = _minute_to_day_time(end_m)
            key = (start_t, end_t, band)
            day_slots.setdefault(key, []).append(day)

        slots = []
        for (start_t, end_t, band), days in day_slots.items():
            ordered = [d for d in DAY_NAMES if d in days]
            slots.append({
                "days": ordered,
                "start": start_t,
                "end": end_t,
                "band": band,
            })
        slots.sort(key=lambda s: (
            DAY_OFFSETS.get(s["days"][0], 0) if s["days"] else 0,
            s["start"],
        ))

        return {
            "protocol": PROTOCOL_H24,
            "program_index": program_index,
            "eco": eco_raw / TEMP_SCALE,
            "comfort": comfort_raw / TEMP_SCALE,
            "comfort2": comfort2_raw / TEMP_SCALE,
            "slots": slots,
        }

    @staticmethod
    def build_schedule_command(schedule: dict, program_index: int = 0) -> list:
        """Encode a user-facing schedule dict into an H24 command array."""
        eco_raw = int(round(schedule["eco"] * TEMP_SCALE))
        comfort_raw = int(round(schedule["comfort"] * TEMP_SCALE))
        comfort2_raw = int(round(schedule["comfort2"] * TEMP_SCALE))

        band_to_temp = {
            "off": 0,
            "eco": eco_raw,
            "comfort": comfort_raw,
            "comfort2": comfort2_raw,
        }

        events = []
        for slot in schedule.get("slots", []):
            band = slot["band"]
            temp = band_to_temp.get(band, 0)
            start_parts = slot["start"].split(":")
            end_parts = slot["end"].split(":")
            start_offset = int(start_parts[0]) * 60 + int(start_parts[1])
            end_offset = int(end_parts[0]) * 60 + int(end_parts[1])

            for day in slot["days"]:
                base = DAY_OFFSETS[day]
                events.append((base + start_offset, temp))
                events.append((base + end_offset, 0))

        for day in DAY_NAMES:
            base = DAY_OFFSETS[day]
            events.append((base, 0))

        events.sort(key=lambda e: (e[0], -e[1]))

        deduped = []
        prev_temp = None
        seen_minutes = set()
        for minute, temp in events:
            if minute in seen_minutes:
                continue
            seen_minutes.add(minute)
            if temp != prev_temp:
                deduped.append((minute, temp))
                prev_temp = temp

        data = []
        for minute, temp in deduped:
            data.extend([str(minute), str(temp)])

        count = len(deduped) * 2 + 5
        return [
            "H24", str(count), "#13", str(program_index),
            str(eco_raw), str(comfort_raw), str(comfort2_raw),
            *data,
        ]

    @staticmethod
    def validate_schedule(data) -> str | None:
        """Validate a schedule dict. Returns error string or None."""
        if not isinstance(data, dict):
            return "invalid_schedule"

        for key in ("eco", "comfort", "comfort2"):
            val = data.get(key)
            if val is None:
                return "invalid_schedule"
            try:
                val = float(val)
            except (TypeError, ValueError):
                return "invalid_temperature"
            if not 10.0 <= val <= 40.0:
                return "invalid_temperature"

        slots = data.get("slots")
        if not isinstance(slots, list):
            return "invalid_schedule"

        day_intervals: dict[str, list[tuple[int, int]]] = {}
        for slot in slots:
            if not isinstance(slot, dict):
                return "invalid_schedule"

            days = slot.get("days")
            if not isinstance(days, list) or not days:
                return "invalid_day"
            for d in days:
                if d not in DAY_NAMES:
                    return "invalid_day"

            for field in ("start", "end"):
                val = slot.get(field, "")
                if not isinstance(val, str):
                    return "invalid_time"
                parts = val.split(":")
                if len(parts) != 2:
                    return "invalid_time"
                try:
                    h, m = int(parts[0]), int(parts[1])
                except ValueError:
                    return "invalid_time"
                if not (0 <= h <= 23 and 0 <= m <= 59):
                    return "invalid_time"

            start_m = int(slot["start"].split(":")[0]) * 60 + int(slot["start"].split(":")[1])
            end_m = int(slot["end"].split(":")[0]) * 60 + int(slot["end"].split(":")[1])
            if start_m >= end_m:
                return "invalid_time"

            band = slot.get("band", "")
            if band not in BAND_NAMES or band == "off":
                return "invalid_schedule"

            for d in days:
                day_intervals.setdefault(d, []).append((start_m, end_m))

        for d, intervals in day_intervals.items():
            intervals.sort()
            for i in range(len(intervals) - 1):
                if intervals[i][1] > intervals[i + 1][0]:
                    return "overlapping_slots"

        return None
