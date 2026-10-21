# 4HEAT Lite Stove - Home Assistant Integration

> **WARNING: This integration is a Work in Progress and currently in Beta.**
> Use at your own risk. This software is provided "as is", without warranty of any kind. We are not responsible for bricked stoves, thermonuclear war, your house burning down, or you getting fired because the pellet stove kept you so warm you overslept. Please do some research if you have any concerns about features included in this integration before using it! YOU are choosing to use this, and if you point the finger at us for messing up your setup, we will laugh at you.

Home Assistant custom integration for pellet stoves equipped with a **4HEAT Lite** WiFi module. Communicates locally over TCP using the 2WC protocol — no cloud dependency for sensor data. Optional cloud API proxy enables write commands (temperature, ON/OFF) and keeps the Lasian/4HEAT mobile app in sync.

## Compatibility

This integration works with the **4HEAT Lite** WiFi module (Tiemme). It does NOT work with the older 4HEAT module that uses the SEL/SEC protocol — for that, see [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat).

How to tell which module you have:
- **4HEAT Lite** (this integration): sends `["2WC","1","0310"]` JSON commands over TCP:80
- **Original 4HEAT**: uses `SEL`/`SEC` text commands over TCP:80

Tested with a Lasian Eriste air pellet stove. Should work with any stove using a 4HEAT Lite module (Tiemme electronics).

## Features

Both modes share these features:

- **Sensors**: State, error, exhaust temperature, room temperature, target temperature, power level, running and error binary sensors. See [Sensors & Entities](docs/SENSORS.md) for the full list, register map, and 2WC protocol details.

- **Climate entity**: Target temperature control, HVAC modes (OFF/HEAT), power presets, ON/OFF commands. See [Sensors & Entities](docs/SENSORS.md#climate-entity).

- **Write commands** (ON/OFF, temperature, power level): Sent to the module via the proxy command queue. The module picks them up on its next poll (~60s).

- **Cloud API Proxy**: Both modes intercept module cloud traffic via a local proxy. The module talks to HA instead of the 4HEAT cloud. A DNS override and firewall DNAT rule on your router redirect the module's requests to HA. See [Proxy Modes](docs/PROXY_MODES.md) for architecture and [Network Setup](docs/PROXY_MODES.md#network-setup-openwrt) for router configuration.

- **Proxy Endpoints**: The proxy implements 5 endpoints matching the 4HEAT cloud API. See [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) for request/response formats, values decoding, and device lookup logic.

## Proxy Modes

The integration supports two proxy modes, selected during setup and changeable in Options. They differ in what features are available and whether the module stays connected to the 4HEAT cloud.

### Local Only (`local_only`)

The module's cloud traffic is intercepted and handled locally by HA. No data is forwarded to the 4HEAT cloud. The Lasian/4HEAT mobile app will **not** work while in this mode.

Features exclusive to `local_only`:

- **Schedule management**: View and edit the stove's weekly heating schedule (H24 program) directly from HA. A YAML editor in the integration's Options Flow shows the current schedule and lets you modify it. Also available as custom services (`get_schedule` / `set_schedule`) for automations. See [Scheduling](docs/SCHEDULING.md) for protocol details.

Schedule YAML example:

```yaml
eco: 18.0
comfort: 23.0
comfort2: 24.0
slots:
  - days: [mon, tue, wed, thu, fri]
    start: "07:30"
    end: "09:30"
    band: comfort
  - days: [mon, tue, wed, thu, fri]
    start: "19:00"
    end: "22:00"
    band: comfort
  - days: [sat, sun]
    start: "08:00"
    end: "23:00"
    band: eco
```

### Cloud Sync (`cloud_sync`)

The proxy forwards all module traffic to the 4HEAT cloud and relays the responses back. This keeps the Lasian/4HEAT mobile app fully functional while adding HA sensors and controls on top.

Features exclusive to `cloud_sync`:

- **Bidirectional sync**: Changes made in the mobile app are reflected in HA, and vice versa. The Lasian/4HEAT mobile app remains fully functional.

Requires 4HEAT account credentials during setup (used once to retrieve the DeviceKey, **not stored**).

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
3. Enter the Device ID (printed on the module label), a name for your stove, and the module's IP address
4. Select the proxy mode: **Local only** (sensors only) or **Cloud sync** (full control + mobile app sync)
5. If you selected Cloud sync, enter your 4HEAT account credentials (same email/password as the Lasian/4HEAT mobile app). These are used once to retrieve the DeviceKey from the cloud and are **not stored**.
6. The integration will verify connectivity before completing setup

### Device ID

The Device ID is printed on the module's label. You can also find it in the Lasian/4HEAT mobile app (device info section).

### Options

After setup, go to the integration's options to change:
- **Proxy mode**: switch between `local_only` and `cloud_sync`
- **Weekly schedule** (shown in `local_only` mode only): YAML editor pre-populated with the current stove schedule. Edit time slots, temperature bands, and per-day configuration. See the [schedule YAML example](#local-only-local_only) above.

### Multiple Stoves

To add multiple stoves, run the "Add Integration" flow once per stove — each gets its own config entry with its own module IP. Each module needs its own firewall DNAT rule (`src_ip` = that module's IP). See [Proxy Modes](docs/PROXY_MODES.md#multiple-modules).

## Known Limitations

- **Write latency ~60s**: Commands are delivered when the module polls (every ~60 seconds). Not suitable for safety-critical controls.
- **Air stoves only** (for now): tested with an air stove. Hydro (water) stoves may expose additional registers (boiler pressure, water temperature) that are not yet mapped.

## Documentation

- [Sensors & Entities](docs/SENSORS.md) — entity list, register map, 2WC protocol, state/error codes
- [Proxy Modes](docs/PROXY_MODES.md) — architecture, local_only vs cloud_sync, network setup, stunnel
- [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) — endpoint reference, request/response formats, values decoding
- [Scheduling](docs/SCHEDULING.md) — H24/CCG schedule protocols, timeAlign clock sync, schedule read/write

## Related Projects

- [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat) — HA integration for the older 4HEAT module (SEL/SEC protocol)
- [4heat-esphome](https://github.com/leoshusar/4heat-esphome) — ESPHome component for direct ESP32-to-stove serial connection (Tiemme protocol)

## License

GPL-3.0 — see [LICENSE](LICENSE).
