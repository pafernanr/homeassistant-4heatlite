# 4HEAT Lite Stove - Home Assistant Integration

> **WARNING: This integration is a Work in Progress and currently in Beta.**
> Use at your own risk. This software is provided "as is", without warranty of any kind. We are not responsible for bricked stoves, thermonuclear war, your house burning down, or you getting fired because the pellet stove kept you so warm you overslept. Please do some research if you have any concerns about features included in this integration before using it! YOU are choosing to use this, and if you point the finger at us for messing up your setup, we will laugh at you.

Home Assistant custom integration for pellet stoves equipped with a **4HEAT Lite** WiFi module. Communicates locally over TCP using the 2WC protocol — no cloud dependency for sensor data. Optional cloud API proxy enables write commands and schedule management.

## Compatibility

This integration works with the **4HEAT Lite** WiFi module (Tiemme). It does NOT work with the older 4HEAT module that uses the SEL/SEC protocol — for that, see [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat).

How to tell which module you have:
- **4HEAT Lite** (this integration): sends `["2WC","1","0310"]` JSON commands over TCP:80
- **Original 4HEAT**: uses `SEL`/`SEC` text commands over TCP:80

Tested with a Lasian Eriste air pellet stove. Should work with any stove using a 4HEAT Lite module (Tiemme electronics).

## Features

What you get depends on whether you configure the cloud API proxy ([DNS override + firewall DNAT rule](docs/PROXY_MODES.md#network-setup-openwrt) on your router):

| Feature | No proxy | `local_only` | `cloud_sync` |
|---------|----------|--------------|--------------|
| [Sensors](#sensors) (state, temperatures, power, errors) | Yes | Yes | Yes |
| [Write commands](#write-commands) (ON/OFF, target temperature, power level) | No | Yes | Yes |
| [Schedule management](#schedule-management) (weekly heating program) | No | Yes | Yes |
| Lasian/4HEAT mobile app | Yes (direct cloud) | No | Yes (via HA) |

### Sensors

Read directly from the module over TCP (2WC protocol) — no proxy, DNS, or firewall setup required.

- **State**: operating state (OFF, Ignition, Run, Modulation, Extinguishing, etc.)
- **Error**: active error description (None, Failed Ignition, Exhaust over Temperature, etc.)
- **Exhaust temperature**: exhaust gas temperature in °C
- **Room temperature**: room temperature in °C (0.1° precision)
- **Target temperature**: configured target room temperature in °C
- **Power level**: current power level (1-7)
- **Running**: binary sensor, ON when stove is in any active state
- **Error Active**: binary sensor, ON when an error code is present

See [Sensors & Entities](docs/SENSORS.md) for the full register map, 2WC protocol details, and diagnostic sensors.

### Write Commands

Require the cloud API proxy. Commands are queued and delivered to the module on its next poll (~60s).

- **ON / OFF**: start or stop the stove
- **Target temperature**: set room target (10-40°C, 0.1°C step)
- **Power level**: set power (1-7)

All write commands are available via the [climate entity](docs/SENSORS.md#climate-entity) (HVAC modes, temperature slider, power presets).

### Schedule Management

View and edit the stove's weekly heating schedule (H24 program) directly from HA. Available in both proxy modes.

- **Options Flow**: YAML editor pre-populated with the current schedule
- **Services**: `4heatlite.get_schedule` and `4heatlite.set_schedule` for automations

See [Scheduling](docs/SCHEDULING.md) for the H24/CCG protocol details.

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

## Proxy Modes

The cloud API proxy intercepts the module's cloud traffic by redirecting it to HA. This requires a DNS override and firewall DNAT rule on your router. See [Network Setup](docs/PROXY_MODES.md#network-setup-openwrt) for step-by-step instructions.

Without the proxy, the module talks directly to the 4HEAT cloud — sensors still work (TCP is direct), but HA cannot send commands or manage the schedule.

Two proxy modes are available, selected during setup and changeable in Options:

### Local Only (`local_only`)

All module cloud traffic is handled locally by HA. No data is forwarded to the 4HEAT cloud. Write commands and schedule management are available. The Lasian/4HEAT mobile app will **not** work in this mode.

### Cloud Sync (`cloud_sync`)

The proxy forwards all module traffic to the 4HEAT cloud and relays the responses back. Write commands are available. The Lasian/4HEAT mobile app remains fully functional with bidirectional sync — changes in the app are reflected in HA and vice versa.

Requires 4HEAT account credentials during setup (used once to retrieve the DeviceKey, **not stored**).

See [Proxy Modes](docs/PROXY_MODES.md) for architecture details and [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) for the endpoint reference.

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
4. Select the proxy mode: **Local only** or **Cloud sync**
5. If you selected Cloud sync, enter your 4HEAT account credentials (same email/password as the Lasian/4HEAT mobile app). These are used once to retrieve the DeviceKey and are **not stored**.
6. The integration will verify connectivity before completing setup

### Device ID

The Device ID is printed on the module's label. You can also find it in the Lasian/4HEAT mobile app (device info section).

### Options

After setup, go to the integration's options to change:
- **Proxy mode**: switch between `local_only` and `cloud_sync`
- **Weekly schedule**: YAML editor pre-populated with the current stove schedule. See the [schedule example](#schedule-management) above.

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
