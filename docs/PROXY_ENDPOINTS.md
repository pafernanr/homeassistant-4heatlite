# Proxy Endpoints

The proxy registers HTTP endpoints on HA's existing web server (port 8123) using the `HomeAssistantView` pattern. All endpoints use `requires_auth = False` because the module has no authentication capabilities.

## Endpoint Reference

### POST `/api/devices/register`

**When**: Module sends this once on boot before starting the polling cycle.

**Request body** (JSON):
```json
{
  "Id": "<DEVICE_ID>",
  "DeviceName": "",
  "Pin": "<PIN>",
  "ProductCode": "SYEVO0000564",
  "ProductVersion": "000000000001",
  "ProductCommunication": "2ways",
  "FirmwareVersion": 2,
  "FirmwareRevision": 11,
  "FilemapVersion": 34,
  "IpAddress": "192.168.1.50",
  "DeviceType": "Lite",
  "Coordinates": {"Latitude": "0.00", "Longitude": "0.00"},
  "NodeList": [
    {"Firmware": "4.3.0", "Type": "MSTR", "Address": "48", "Desc": "FSYSR03000001."},
    {"Firmware": "0.3.0", "Type": "KEYB", "Address": "26", "Desc": "FSYSF29000001."},
    {"Firmware": "0.3.0", "Type": "COMI", "Address": "50", "Desc": "FSYSF29000001."},
    {"Firmware": "0.1.4", "Type": "COMI", "Address": "48", "Desc": "4Heat Firmware"}
  ],
  "SSID": "<WIFI_SSID>",
  "RSSI": "-60"
}
```

**Response** (JSON):
```json
{"Key": "<DEVICE_KEY>"}
```

**Proxy behavior**:
1. Auto-detects device ID and maps it to the config entry.
2. In `cloud_sync` mode: forwards the full payload to Azure and receives the real DeviceKey.
3. Returns the stored DeviceKey (from config entry) or the cloud-retrieved key.
4. If a new key is received from the cloud, persists it in the config entry.

---

### GET `/api/devices/commands`

**When**: Module polls every ~60 seconds.

**Query parameters**:
- `id` — Device ID
- `removefromserver` — `true` (module wants commands removed after delivery)

**Response** (JSON array):
```json
[{"id": "<DEVICE_ID>", "comando": ["2WC", "1", "0512005a00b4006401900001000100"]}]
```
Or empty: `[]`

**Proxy behavior**:
1. Drains the local command queue (commands from HA climate entity).
2. In `cloud_sync` mode: also fetches commands from Azure and merges them.
3. Returns the combined list.

---

### GET `/api/Devices/timeAlign`

**When**: Module calls this after every commands poll to sync its internal clock.

**Query parameters**:
- `deviceKey` — The module's DeviceKey UUID

**Response** (JSON):
```json
{"gmtOffset": 7200, "timestamp": 1787022616}
```

**Proxy behavior**:
1. In `cloud_sync` mode: forwards to Azure and returns the response.
2. Fallback: returns local system time with configured GMT offset.

> **Critical**: If this endpoint returns 404, the module stops its polling cycle and never sends `/store`. This was discovered empirically — it is not documented in any API reference.

---

### POST `/api/devices/store`

**When**: Module sends sensor data on value changes (within seconds) and periodically as a keepalive (~15 minutes).

**Request body** (JSON):
```json
{
  "DeviceKey": "<DEVICE_KEY>",
  "TimeStamp": "2026-08-18T02:15:00",
  "GmtOffset": 7200,
  "Values": [
    "1000010017000002021600f322000000010801",
    "12005a00b4006401900001000100000000",
    "0e016c00070001000700000001016c0007",
    ...
  ]
}
```

**Response** (JSON):
```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

**Proxy behavior**:
1. Parses the `Values` array to extract sensor data:
   - `10...` (38 chars) — main sensor block (0310): state, error, exhaust temp, room temp
   - `12005a...` — target temperature register
   - `0e016c...` — power level register
2. Pushes parsed data to the coordinator for immediate entity updates.
3. In `cloud_sync` mode: forwards the full body to Azure.

### Values Decoding

| Prefix | Register | Parsed Field | Decoding |
|--------|----------|-------------|----------|
| `10` | 0310 (sensors) | state, error, exhaust_temp, room_temp, on_off | See [register map](SENSORS.md#register-map-0310-response) |
| `12005a` | Target temp | `target_temp` | bytes 3-4, big-endian, ÷10 → °C |
| `0e016c` | Power | `power` | bytes 5-6, big-endian |

---

### POST `/api/devices/cron`

**When**: Module sends schedule/timer data periodically.

**Response** (JSON):
```json
{"DeviceId": "<DEVICE_ID>", "Assistant": ""}
```

**Proxy behavior**:
1. Acknowledges with the standard response.
2. In `cloud_sync` mode: forwards to Azure.

---

### GET `/api/devices/diag` (temporary)

Diagnostic endpoint for debugging proxy state. Returns device count, host mapping, cloud session status, and forward tracking. Will be removed in a future release.

## Device Lookup

The proxy identifies which stove a request belongs to using two methods:

1. **Device ID** — from query parameters (`id=`) or request body (`Id`). Used by `/register` and `/commands`.
2. **Source IP** — the module's IP address. Used by `/store` and `/cron` which don't include a device ID.

A host-to-device mapping is maintained in memory and updated on every request.

## Auto-Detection

If the integration is configured without a Device ID (empty field), the proxy places the config entry in a "pending" state. When the first request arrives from the module, the device ID is auto-detected from the request and the entry is promoted to active.
