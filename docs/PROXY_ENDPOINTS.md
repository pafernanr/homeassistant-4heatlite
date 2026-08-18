# Proxy Endpoints

The proxy registers HTTP endpoints on HA's web server (port 8123) using the `HomeAssistantView` pattern. All endpoints use `requires_auth = False` because the module has no authentication capabilities.

## Endpoint Reference

| Endpoint | Method | When | Proxy Mode |
|----------|--------|------|------------|
| [`/api/devices/register`](#post-apidevicesregister) | POST | Module boot | Both |
| [`/api/devices/commands`](#get-apidevicescommands) | GET | Every ~60s | Both |
| [`/api/Devices/timeAlign`](#get-apidevicestimealign) | GET | After each commands poll | Both |
| [`/api/devices/store`](#post-apidevicesstore) | POST | On value change + ~15min keepalive | Both |
| [`/api/devices/cron`](#post-apidevicescron) | POST | Periodically | Both |

---

### POST `/api/devices/register`

Module sends this once on boot before starting the polling cycle.

**Request:**

```json
{
  "Id": "<DEVICE_ID>",
  "DeviceName": "",
  "Pin": "<PIN>",
  "ProductCode": "<PRODUCT_CODE>",
  "ProductVersion": "000000000001",
  "ProductCommunication": "2ways",
  "FirmwareVersion": 2,
  "FirmwareRevision": 11,
  "FilemapVersion": 34,
  "IpAddress": "<MODULE_IP>",
  "DeviceType": "Lite",
  "Coordinates": {"Latitude": "0.00", "Longitude": "0.00"},
  "NodeList": [
    {"Firmware": "4.3.0", "Type": "MSTR", "Address": "48", "Desc": "..."},
    {"Firmware": "0.3.0", "Type": "KEYB", "Address": "26", "Desc": "..."},
    {"Firmware": "0.3.0", "Type": "COMI", "Address": "50", "Desc": "..."},
    {"Firmware": "0.1.4", "Type": "COMI", "Address": "48", "Desc": "4Heat Firmware"}
  ],
  "SSID": "<WIFI_SSID>",
  "RSSI": "-60"
}
```

**Response:**

```json
{"Key": "<DEVICE_KEY>"}
```

`cloud_sync`: forwards to Azure, receives and persists DeviceKey. `local_only`: returns stored DeviceKey from config entry.

---

### GET `/api/devices/commands`

Module polls every ~60s for pending commands.

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | query | Device ID |
| `removefromserver` | query | `true` — dequeue after delivery |

**Response** (with pending command):

```json
[{"id": "<DEVICE_ID>", "comando": ["2WC", "1", "0512005a00b4006401900001000100"]}]
```

**Response** (no pending commands):

```json
[]
```

`cloud_sync`: drains local queue + fetches and merges Azure commands. `local_only`: drains local queue only.

---

### GET `/api/Devices/timeAlign`

Module calls this after every commands poll to sync its internal clock.

| Parameter | Type | Description |
|-----------|------|-------------|
| `deviceKey` | query | DeviceKey UUID |

**Response:**

```json
{"gmtOffset": 7200, "timestamp": 1787022616}
```

`cloud_sync`: forwards to Azure. `local_only`: returns local system time with configured GMT offset.

> **Critical**: If this endpoint returns 404, the module stops its polling cycle and never sends `/store`.

---

### POST `/api/devices/store`

Module sends sensor data on value changes (within seconds) and periodically as a keepalive (~15 minutes).

**Request:**

```json
{
  "DeviceKey": "<DEVICE_KEY>",
  "TimeStamp": "2026-08-18T02:15:00",
  "GmtOffset": 7200,
  "Values": [
    "1000010017000002021600f322000000010801",
    "12005a00b4006401900001000100000000",
    "0e016c00070001000700000001016c0007"
  ]
}
```

**Response:**

```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

Proxy parses `Values` to extract sensor data (see [Values Decoding](#values-decoding) below), pushes to coordinator for immediate entity updates. `cloud_sync`: also forwards full body to Azure.

---

### POST `/api/devices/cron`

Module sends schedule/timer data periodically.

**Response:**

```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

`cloud_sync`: forwards to Azure. `local_only`: acknowledges only.

---

## Values Decoding

The `Values` array in `/store` contains hex-encoded register data. Each string is identified by its prefix:

| Prefix | Register | Parsed Fields | Decoding |
|--------|----------|---------------|----------|
| `10` (38 chars) | 0310 — main sensors | state, error, exhaust_temp, room_temp, on_off | See [register map](SENSORS.md#register-map-0310-response) |
| `12005a` | Target temp | target_temp | bytes 3-4, big-endian, /10 = °C |
| `0e016c` | Power level | power | bytes 5-6, big-endian |

## Device Lookup

The proxy identifies which stove a request belongs to using two methods:

1. **Device ID** — from query parameters (`id=`) or request body (`Id`). Used by `/register` and `/commands`.
2. **Source IP** — the module's IP address. Used by `/store` and `/cron` which don't include a device ID.

A host-to-device mapping is maintained in memory and updated on every request.

## Auto-Detection

If the integration is configured without a Device ID (empty field), the proxy places the config entry in a "pending" state. When the first request arrives from the module, the device ID is auto-detected from the request and the entry is promoted to active.
