"""Constants for the 4HEAT Lite integration."""

DOMAIN = "4heatlite"
DATA_COORDINATOR = "coordinator"

TCP_PORT = 80
SOCKET_TIMEOUT = 5
SOCKET_BUFFER = 1024

QUERY_SENSORS = '["2WC","1","0310"]'
QUERY_CONFIG = {
    "target_temp": '["2WC","1","0312005a"]',
    "power": '["2WC","1","030e016c"]',
}
QUERY_EXHAUST = '["2WC","1","0312ffff"]'
REGISTER_SENSORS = "10"
REGISTER_EXHAUST = "12ffff"
# Fan levels the 4HEAT filemap declares, polled over TCP: data key -> 0e register.
# On a Ferlux the panel's fan setting is not among them (see DEFAULT_FAN_REGISTER).
# state_info: byte 3 is the running power level as an ASCII digit (liv_pot).
# 0e/016c stays at the max on Lasian, so it is the set point only.
QUERY_MODULE_INFO = '["2WC","1","030c81"]'
REGISTER_MODULE_INFO = "0c81"
FAN_REGISTERS = {
    "ducted_fan_1": "0e0266",
    "ducted_fan_2": "0e027e",
}

# The module answers ["ERR","1","4"] now and then while busy
QUERY_RETRIES = 2
QUERY_RETRY_DELAY = 1.5
# Failed polls that keep the last data before entities go unavailable
MAX_STALE_POLLS = 2

# Target register max at or below this = whole-degree stove (10-40 vs 100-400)
WHOLE_DEGREE_MAX_RAW = 100

DEFAULT_SCAN_INTERVAL = 30

# Sensor state values are translation keys (entity.sensor.*.state.*).
UNKNOWN_KEY = "unknown"

STATE_KEYS = {
    0: "off",
    1: "check_up",
    2: "ignition",
    3: "stabilization",
    4: "ignition",
    5: "run",
    6: "modulation",
    7: "extinguishing",
    8: "safety",
    9: "block",
    10: "recover_ignition",
    11: "standby",
    13: "run_m",
    30: "ignition",
    31: "ignition",
    32: "ignition",
    33: "ignition",
    34: "ignition",
}

ERROR_KEYS = {
    0: "none",
    1: "safety_thermostat_hv1",
    2: "safety_pressure_switch_hv2",
    3: "exhaust_temp_lowering",
    4: "water_over_temperature",
    5: "exhaust_over_temperature",
    6: UNKNOWN_KEY,
    7: "encoder_no_signal",
    8: "encoder_fan_regulation_failed",
    9: "low_boiler_pressure",
    10: "high_boiler_pressure",
    11: "clock_reset",
    12: "failed_ignition",
    13: "ignition_error",
    14: "ignition_error",
    15: "lack_of_voltage",
    16: "ignition_error",
    17: "ignition_error",
    18: "lack_of_voltage",
    44: "door_error",
}

# Proxy configuration
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_KEY = "device_key"
CONF_MODULE_ADDRESS = "module_address"
CONF_PROXY_MODE = "proxy_mode"
CONF_SCHEDULE_ENABLED = "schedule_enabled"  # v2 migration only
CONF_CACHED_SCHEDULE = "cached_schedule"  # v2 migration only
# The register the panel's fan setting lives in: 0e038c (-7..+7) on a Ferlux
# SYEVO0000559, whose 0e023f never moves. The number entity is created on it.
DEFAULT_FAN_REGISTER = "0e038c"
CONF_ACTIVE_SCHEDULE = "active_schedule"
CONF_CACHED_SCHEDULES = "cached_schedules"
NUM_SCHEDULE_SLOTS = 3
PROXY_MODE_DIRECT = "direct"
PROXY_MODE_LOCAL = "local_only"
PROXY_MODE_KEEPALIVE = "cloud_keepalive"

AZURE_HTTPS_BASE = "https://wifi4heat.azurewebsites.net"
CONF_PROXY_LOG_LEVEL = "proxy_log_level"
CONF_PROXY_DEBUG = "proxy_debug"  # v0.9.92 migration only
LOG_LEVEL_WARNING = "warning"
LOG_LEVEL_INFO = "info"
LOG_LEVEL_DEBUG = "debug"
PROXY_POLL_INTERVAL = 120

STORE_REGISTERS = {
    "12ffff": {"key": "exhaust_temp_store", "group": "12", "scale": 1},
    "12fff7": {"key": "room_temp_store", "group": "12", "temp": True},
    "12ffe0": {"key": "remote_room_temp", "group": "12", "temp": True},
    "12ffe8": {"key": "remote_room_temp_2", "group": "12", "temp": True},
    "12ffed": {"key": "airflow", "group": "12", "scale": 1},
    "12ffde": {"key": "cleaning_counter", "group": "12", "scale": 1},
    "12ffdf": {"key": "service_counter", "group": "12", "scale": 1},
    "12005a": {"key": "target_temp", "group": "12", "temp": True},
    "120058": {"key": "reg_120058", "group": "12", "scale": 1},
    "120059": {"key": "reg_120059", "group": "12", "scale": 1},
    "0e016c": {"key": "power", "group": "0e"},
    "0e0266": {"key": "ducted_fan_1", "group": "0e"},
    "0e027e": {"key": "ducted_fan_2", "group": "0e"},
    "0e0231": {"key": "reg_0e0231", "group": "0e"},
    "0c81": {"key": "module_info", "group": "0c"},
}

# Schedule constants
QUERY_SCHEDULE = '["CCG","0"]'
MINUTES_PER_DAY = 1440
DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_OFFSETS = {name: i * MINUTES_PER_DAY for i, name in enumerate(DAY_NAMES)}
BAND_NAMES = ["off", "eco", "comfort", "comfort2"]
TEMP_SCALE = 10
SERVICE_GET_SCHEDULE = "get_schedule"
SERVICE_SET_SCHEDULE = "set_schedule"

# Write command constants
WRITE_FUNCTION = "05"
REGISTER_TEMP = "12005a"
REGISTER_POWER = "0e016c"
REGISTER_HEATING = "0e023f"
# Combustion and heating: 7 is Auto, manual steps stop at AUTO_MANUAL_MAX.
AUTO_VALUE = 7
AUTO_MANUAL_MAX = 6
TEMP_MIN_RAW = 0x0064
TEMP_MAX_RAW = 0x0190
TEMP_WRITE_SUFFIX = "0001000100"
