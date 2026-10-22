# 4HEAT Lite Stove - Home Assistant Integration

> **WARNING: This integration is a Work in Progress and currently in Beta.**
> Use at your own risk. This software is provided "as is", without warranty of any kind. We are not responsible for bricked stoves, thermonuclear war, your house burning down, or you getting fired because the pellet stove kept you so warm you overslept. Please do some research if you have any concerns about features included in this integration before using it! YOU are choosing to use this, and if you point the finger at us for messing up your setup, we will laugh at you.

Home Assistant custom integration for pellet stoves equipped with a **4HEAT Lite** WiFi module. Communicates locally over TCP using the 2WC protocol — no cloud dependency. All features (sensors, controls, schedule) work via direct TCP connection to the module.

## Compatibility

This integration works with the **4HEAT Lite** WiFi module (Tiemme). It does NOT work with the older 4HEAT module that uses the SEL/SEC protocol — for that, see [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat).

How to tell which module you have — connect to port 80 and send a test command:

```bash
# 4HEAT Lite: send a JSON 2WC sensor query
echo -n '["2WC","1","0310"]' | nc -w 3 <MODULE_IP> 80

# Lite response: JSON array with register data
# ["2WR","1","031000000012005a00e6..."]

# Original 4HEAT: send a SEL status query
echo -n 'SEL' | nc -w 3 <MODULE_IP> 80

# Original response: plain text with SEC prefix
# SEC ...
```

- **4HEAT Lite** (this integration): responds with `["2WR","1","..."]` JSON
- **Original 4HEAT**: responds with `SEC` plain text

Tested with a Lasian Eriste air pellet stove. Should work with any stove using a 4HEAT Lite module (Tiemme electronics).

## Features and Modes

All features work via direct TCP connection to the module — no DNS or firewall setup required. Commands (ON/OFF, temperature, power, schedule) are sent instantly over TCP and take effect immediately. Schedules are delivered via dual path: TCP direct (immediate) + proxy command queue (backup, delivered on next module poll ~60s). The 4HEAT mobile app works on the same WiFi in both modes — it discovers the stove via UDP broadcast and communicates directly over TCP.

| Feature | Direct (default) | Local Only |
|---------|-----------------|------------|
| [Sensors](#sensors) (state, temperatures, power, errors) | Yes | Yes |
| [Write commands](#write-commands) (ON/OFF, target temperature, power level) | Yes | Yes |
| [Schedule management](#schedule-management) (weekly heating program) | Yes (TCP + queue) | Yes (TCP + queue) |
| 4HEAT mobile app (same WiFi) | Yes | Yes |
| 4HEAT mobile app (remote/cloud) | Yes | No |

### Direct Mode (default)

The module communicates with both HA (via TCP direct) and the 4HEAT cloud (via its own WiFi connection). No router configuration needed. The 4HEAT mobile app works normally alongside HA.

### Local Only Mode

Enable the **Local Only** checkbox in setup or options to block the module's cloud access. This requires a [DNS override and firewall DNAT rule](docs/PROXY_MODES.md#network-setup-openwrt) on your router to redirect the module's cloud traffic to HA. The integration runs local proxy endpoints to respond to the module's polls.

In this mode:
- No data reaches the 4HEAT cloud (security)
- The 4HEAT mobile app will **not** work
- HA receives real-time sensor push via the proxy's `/store` endpoint (in addition to TCP polling)

### Sensors

Read directly from the module over TCP (2WC protocol).

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

Sent directly to the module over TCP — instant response, no polling delay.

- **ON / OFF**: start or stop the stove
- **Target temperature**: set room target (10-40°C, 0.1°C step)
- **Power level**: set power (1-7)

All write commands are available via the [climate entity](docs/SENSORS.md#climate-entity) (HVAC modes, temperature slider, power presets).

### Schedule Management

View and edit the stove's weekly heating schedule (H24 program) directly from HA.

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



See [Proxy Modes](docs/PROXY_MODES.md) for architecture and [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) for the endpoint reference.

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
3. Enter your 4HEAT account email and password (used once to retrieve the device key from the 4HEAT cloud)
4. Enter the Device ID (printed on the module label), a name for your stove, and the module's IP address
5. Optionally check **Local Only** to block cloud access (requires DNS/firewall setup on your router)
6. The integration will verify connectivity before completing setup

### Device ID

The Device ID is printed on the module's label. You can also find it in the 4HEAT mobile app (device info section).

### Options

After setup, go to the integration's options to change:
- **Local Only**: checkbox to enable/disable cloud blocking
- **Weekly schedule**: YAML editor pre-populated with the current stove schedule. See the [schedule example](#schedule-management) above.

### Multiple Stoves

To add multiple stoves, run the "Add Integration" flow once per stove — each gets its own config entry with its own module IP. In Local Only mode, each module needs its own firewall DNAT rule (`src_ip` = that module's IP). See [Proxy Modes](docs/PROXY_MODES.md#multiple-modules).

## Known Limitations

- **Air stoves only** (for now): tested with an air stove. Hydro (water) stoves may expose additional registers (boiler pressure, water temperature) that are not yet mapped.

## Documentation

- [Sensors & Entities](docs/SENSORS.md) — entity list, register map, 2WC protocol, state/error codes
- [Proxy Modes](docs/PROXY_MODES.md) — architecture, local_only mode, network setup, stunnel
- [Proxy Endpoints](docs/PROXY_ENDPOINTS.md) — endpoint reference, request/response formats, values decoding
- [Scheduling](docs/SCHEDULING.md) — H24/CCG schedule protocols, timeAlign clock sync, schedule read/write

## Related Projects

- [homeassistant-4heat](https://github.com/zaubererty/homeassistant-4heat) — HA integration for the older 4HEAT module (SEL/SEC protocol)
- [4heat-esphome](https://github.com/leoshusar/4heat-esphome) — ESPHome component for direct ESP32-to-stove serial connection (Tiemme protocol)

## License

GPL-3.0 — see [LICENSE](LICENSE).
