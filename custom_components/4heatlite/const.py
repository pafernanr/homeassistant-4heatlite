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

DEFAULT_SCAN_INTERVAL = 30

STATE_NAMES = {
    0: "OFF",
    1: "Check Up",
    2: "Ignition",
    3: "Stabilization",
    4: "Ignition",
    5: "Run",
    6: "Modulation",
    7: "Extinguishing",
    8: "Safety",
    9: "Block",
    10: "Recover Ignition",
    11: "Standby",
    13: "Run M",
    30: "Ignition",
    31: "Ignition",
    32: "Ignition",
    33: "Ignition",
    34: "Ignition",
}

ERROR_NAMES = {
    0: "None",
    1: "Safety Thermostat HV1",
    2: "Safety PressureSwitch HV2",
    3: "Exhaust Temp lowering",
    4: "Water over Temperature",
    5: "Exhaust over Temperature",
    6: "Unknown",
    7: "Encoder: No Signal",
    8: "Encoder: Fan regulation failed",
    9: "Low boiler pressure",
    10: "High boiler pressure",
    11: "Clock reset (power loss)",
    12: "Failed Ignition",
    13: "Ignition error",
    14: "Ignition error",
    15: "Lack of Voltage",
    16: "Ignition error",
    17: "Ignition error",
    18: "Lack of Voltage",
    44: "Door error",
}

# Proxy configuration
CONF_DEVICE_ID = "device_id"
CONF_PROXY_MODE = "proxy_mode"
PROXY_MODE_LOCAL = "local_only"
PROXY_MODE_CLOUD = "cloud_sync"
CLOUD_API_HOST = "wifi4heat-linux.azurewebsites.net"
CLOUD_API_PORT = 80
# DNS hijack redirects the hostname to the local router, so cloud
# forwarding must use the real Azure IP with a Host header override.
CLOUD_API_IP = "20.105.232.8"
COMMAND_QUEUE = "command_queue"
PROXY_SESSION = "proxy_session"
PROXY_POLL_INTERVAL = 120

# Write command constants
WRITE_FUNCTION = "05"
REGISTER_TEMP = "12005a"
REGISTER_POWER = "0e016c"
TEMP_MIN_RAW = 0x0064
TEMP_MAX_RAW = 0x0190
TEMP_WRITE_SUFFIX = "0001000100"
