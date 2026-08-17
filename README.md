# 4HEAT Lite Stove - Home Assistant Integration

> **WARNING: This integration is a Work in Progress and currently in Beta.**
> Use at your own risk. This software is provided "as is", without warranty of any kind. We are not responsible for bricked stoves, thermonuclear war, your house burning down, or you getting fired because the pellet stove kept you so warm you overslept. Please do some research if you have any concerns about features included in this integration before using it! YOU are choosing to use this, and if you point the finger at us for messing up your setup, we will laugh at you.

Home Assistant custom integration for pellet stoves equipped with a **4HEAT Lite** WiFi module. Communicates locally over TCP using the 2WC protocol — no cloud dependency for sensor data. Optional cloud API proxy enables write commands (temperature, ON/OFF) without modifying the module's firmware.

## Compatibility

This integration works with the **4HEAT Lite** module (ESP32-based, ESP-IDF firmware). It does NOT work with the older 4HEAT module that uses the SEL/SEC protocol — for that, see [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat).

How to tell which module you have:
- **4HEAT Lite** (this integration): sends `["2WC","1","0310"]` JSON commands over TCP:80
- **Original 4HEAT**: uses `SEL`/`SEC` text commands over TCP:80

Tested with a Lasian Eriste air pellet stove. Should work with any stove using a 4HEAT Lite module (Tiemme electronics).

## Features

### Sensors
| Entity | Description |
|--------|-------------|
| State | Stove operating state (OFF, Check Up, Ignition, Stabilization, Run, Modulation, Extinguishing, etc.) |
| Error | Active error description (None, Failed Ignition, Exhaust over Temperature, etc.) |
| Exhaust Temperature | Exhaust gas temperature in °C |
| Room Temperature | Room temperature in °C (0.1° precision) |
| Target Temperature | Configured target room temperature in °C |
| Power Level | Current power level setting (1-7) |
| Running | Binary sensor — ON when stove is in any active state |
| Error Active | Binary sensor — ON when an error is present |

Diagnostic sensors for unmapped response bytes are available but disabled by default. Enable them from the entity settings to help identify additional data fields.

### Climate Entity

A climate entity is always created for display (current/target temperature, stove state). Write commands (temperature, ON/OFF, power) require the cloud API proxy — without it, changes are logged but not sent. When the proxy is enabled:
- **HVAC modes**: OFF / HEAT (ON/OFF command register not yet captured — placeholder)
- **Target temperature**: 10–40°C, 0.5°C step
- **Preset modes**: Power 1–7 (power write command not yet captured — placeholder)
- **HVAC action**: OFF, Preheating (ignition), Heating (run/modulation), Idle (extinguishing/standby)

Temperature changes are queued and delivered to the stove via the proxy within ~60 seconds (module polling interval).

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=pafernanr&repository=homeassistant-4heatlite&category=integration)

Or manually add the custom repository:

1. Open HACS in Home Assistant
2. Click the three-dot menu (top right) and select **Custom repositories**
3. Paste `https://github.com/pafernanr/homeassistant-4heatlite` and select **Integration** as category
4. Click **Add**
5. Find "4HEAT Lite Stove" in HACS and click **Download**
6. Restart Home Assistant

HACS will notify you in Home Assistant when a new version is available.

### Manual

1. Download the [latest release](https://github.com/pafernanr/homeassistant-4heatlite/releases/latest)
2. Copy the `custom_components/4heatlite/` directory to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

With manual installation you will not receive update notifications.

## Configuration

1. Go to Settings > Devices & Services > Add Integration
2. Search for "4HEAT Lite Stove"
3. Enter a name for your stove and the IP address of the 4HEAT Lite module
4. Optionally enable the cloud API proxy and enter your Device ID
5. The integration will verify connectivity before completing setup

No authentication is needed — the module's local TCP API has no auth.

### Finding your Device ID

If you enable the cloud API proxy, you need your module's Device ID. Query the 4HEAT cloud API with your Lasian/4HEAT mobile app credentials:

```bash
# Get OAuth token
TOKEN=$(curl -s -X POST https://wifi4heat.azurewebsites.net/Token \
  -d "grant_type=password&username=YOUR_EMAIL&password=YOUR_PASSWORD" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token','').strip())")

# List your devices — try both API hosts
curl -sv -H "Authorization: Bearer $TOKEN" \
  https://wifi4heat.azurewebsites.net/api/devices 2>&1

# If the above returns empty, try the -linux host:
curl -sv -H "Authorization: Bearer $TOKEN" \
  https://wifi4heat-linux.azurewebsites.net/api/devices 2>&1
```

Replace `YOUR_EMAIL` and `YOUR_PASSWORD` with the credentials you use in the Lasian/4HEAT mobile app. The Device ID is a numeric string (e.g. `12345678`) in the JSON response.

### Options

After setup, go to the integration's options to change:
- **Proxy mode**: `local_only` (default) or `cloud_sync` (forwards data to/from Azure so the Lasian app stays in sync)

## Cloud API Proxy

The 4HEAT Lite module's local TCP API is **read-only** — write commands (temperature changes, ON/OFF) are only accepted via cloud polling. The integration includes an embedded HTTP proxy using Home Assistant's native `HomeAssistantView` pattern that intercepts the module's cloud traffic and injects local commands.

### Architecture

```
                    ┌──────────────┐
                    │  Lasian App   │ (cloud_sync mode only)
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Azure Cloud  │ (bypassed in local_only mode)
                    └──────▲───────┘
                           │ forwarded (cloud_sync only)
┌─────────┐  RS485    ┌───┴───────────┐  HTTP     ┌──────────────────────┐
│  Stove  │◄─────────►│ 4HEAT Module  │◄─────────►│  HA (port 8123)      │
│         │  Tiemme   │   (.50)       │ DNAT:80   │  HomeAssistantView   │
└─────────┘           └───────────────┘           │  proxy endpoints     │
                                                  └──────────────────────┘
```

### Proxy Endpoints

The proxy registers three endpoints on HA's existing web server (port 8123):

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/devices/commands` | GET | Module polls for pending write commands |
| `/api/devices/store` | POST | Module uploads sensor data (pushed to coordinator for real-time updates) |
| `/api/devices/cron` | POST | Module uploads schedule data |

### Proxy Modes

- **`local_only`** (default): Module traffic stays local. Cloud is fully bypassed. The Lasian mobile app will NOT work.
- **`cloud_sync`**: Commands from both HA and the Lasian app are merged. Sensor data is forwarded to Azure so the app stays in sync.

### Network Setup (OpenWrt)

The module connects to `wifi4heat-linux.azurewebsites.net` on port 80. To redirect this traffic to HA, configure DNS override and firewall DNAT on your router.

**DNS override** — resolve the cloud hostname to your router:

```bash
uci add_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/192.168.1.1'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

**Firewall DNAT** — redirect module traffic from router:80 to HA:8123:

```bash
uci add firewall redirect
uci set firewall.@redirect[-1].name='4heat-proxy'
uci set firewall.@redirect[-1].src='lan'
uci set firewall.@redirect[-1].src_ip='192.168.1.50'
uci set firewall.@redirect[-1].dest='lan'
uci set firewall.@redirect[-1].dest_ip='192.168.1.10'
uci set firewall.@redirect[-1].dest_port='8123'
uci set firewall.@redirect[-1].proto='tcp'
uci set firewall.@redirect[-1].target='DNAT'
uci commit firewall
/etc/init.d/firewall restart
```

Replace `192.168.1.50` with your module's IP, `192.168.1.1` with your router's IP, and `192.168.1.10` with your HA server's IP.

> **Note**: LAN-to-LAN DNAT (hairpin NAT) may require an additional masquerade rule on some OpenWrt configurations.

### Reverting to Cloud

To restore cloud connectivity, remove the DNS override and firewall redirect:

```bash
uci del_list dhcp.@dnsmasq[0].address='/wifi4heat-linux.azurewebsites.net/192.168.1.1'
uci commit dhcp
/etc/init.d/dnsmasq restart
# Remove the firewall redirect (find its index with: uci show firewall | grep 4heat)
uci delete firewall.@redirect[N]
uci commit firewall
/etc/init.d/firewall restart
```

## How it works

The 4HEAT Lite module exposes a TCP server on port 80. This integration sends JSON-encoded 2WC commands to read sensor registers from the stove's Tiemme controller board via the module's RS485 bus.

Query: `["2WC","1","0310"]`
Response: `["2WC","1","<38 hex chars>"]`

The 19-byte response contains the stove state, error code, exhaust temperature, room temperature, and other registers. The integration polls every 30 seconds (or 120 seconds when the proxy is active and providing real-time updates via `/api/devices/store`).

### Register map (0310 response)

| Byte(s) | Field | Unit | Notes |
|---------|-------|------|-------|
| 0 | Header | - | Always 0x10 |
| 1 | Error | enum | See `ERROR_NAMES` in const.py |
| 2 | On/Off | flag | 0=off, 1=on (stays 1 during cooldown) |
| 4 | Exhaust temp | °C | 1-byte unsigned |
| 5 | State | enum | See `STATE_NAMES` in const.py |
| 10-11 | Room temp | 0.1°C | 2-byte big-endian |

Bytes 3, 6-9, 12-18 are not yet mapped. Enable the diagnostic sensors to help identify them while the stove is running.

### Write command format

Write commands use function code `05` followed by the register address and data:

```
["2WC","1","05<register><data>"]
```

Example — set target temperature to 28.8°C:
```
["2WC","1","0512005a0120006401900001000100"]
```

- `05` — write function
- `12005a` — register group 12, address 005a (target temperature)
- `0120` — 28.8°C (0x120 = 288, in 0.1°C units)
- `0064` — min 10.0°C
- `0190` — max 40.0°C
- `0001000100` — trailing register data

## Known limitations

- **ON/OFF and power commands not yet captured**: The ON/OFF and power level write registers have not been captured from cloud traffic yet. Temperature changes work via the proxy.
- **Write latency ~60s**: Commands are delivered when the module polls (every ~60 seconds). Not suitable for safety-critical controls.
- **Air stoves only** (for now): tested with an air stove. Hydro (water) stoves may expose additional registers (boiler pressure, water temperature) that are not yet mapped.
- **Single stove per HA instance**: The proxy endpoints use fixed URL paths. Multiple stoves would require separate HA instances or custom routing.

## Related projects

- [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat) — HA integration for the older 4HEAT module (SEL/SEC protocol)
- [4heat-esphome](https://github.com/leoshusar/4heat-esphome) — ESPHome component for direct ESP32-to-stove serial connection (Tiemme protocol)

## License

GPL-3.0 — see [LICENSE](LICENSE).
