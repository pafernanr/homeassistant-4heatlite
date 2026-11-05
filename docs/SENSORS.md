# Sensors & Entities

## Sensor Entities

| Entity | Description | Source |
|--------|-------------|--------|
| State | Stove operating state (OFF, Check Up, Ignition, Stabilization, Run, Modulation, Extinguishing, etc.) | TCP poll (0310 byte 5) |
| Error | Active error description (None, Failed Ignition, Exhaust over Temperature, etc.) | TCP poll (0310 byte 1) |
| Exhaust Temperature | Exhaust gas temperature in °C | TCP poll (0310 byte 4) |
| Room Temperature | Room temperature in °C (0.1° precision) | TCP poll (0310 bytes 10-11) |
| Target Temperature | Configured target room temperature in °C | TCP poll (12/005a register) |
| Power Level | Current power level setting (1-7) | TCP poll (0e/016c register) |

## Binary Sensor Entities

| Entity | Description |
|--------|-------------|
| Running | ON when stove is in any active state (ignition, run, modulation, stabilization) |
| Error Active | ON when an error code is present |

## Climate Entity

A climate entity is always created for display (current/target temperature, stove state). Write commands (temperature, ON/OFF, power) require the [cloud API proxy](PROXY_MODES.md) — without it, changes are logged but not sent.

When the proxy is enabled:
- **HVAC modes**: OFF / HEAT (sends ON/OFF command to the module)
- **Target temperature**: 10-40°C, 0.1°C step
- **Preset modes**: Power 1-7
- **HVAC action**: OFF, Preheating (ignition), Heating (run/modulation), Idle (extinguishing/standby)

All write commands are queued and delivered to the stove via the proxy within ~60 seconds (module polling interval).

## Register Sensors (from store push)

Additional sensors parsed from the module's `POST /api/devices/store` Values array. These update every ~3 minutes when the proxy is active (cloud_keepalive or local_only mode). In direct mode, these sensors are not populated.

| Entity | Data key | Register | Source (filemap) | Notes |
|--------|----------|----------|-----------------|-------|
| Remote Room Temperature | `remote_room_temp` | 12/ffe0 | Temp ambiente remota | Shows unavailable when 0 (no probe) |
| Remote Room Temperature 2 | `remote_room_temp_2` | 12/ffe8 | Temp ambiente remota 2 | Shows unavailable when 0 (no probe) |
| Airflow | `airflow` | 12/ffed | Flusso aria | Raw value (unit TBD) |
| Heating Fan Power | `heating_fan_power` | 0e/023f | Potencia calefacción | |
| Ducted Fan 1 | `ducted_fan_1` | 0e/0266 | Potencia canalizada 1 | Disabled by default |
| Ducted Fan 2 | `ducted_fan_2` | 0e/027e | Potencia canalizada 2 | Disabled by default |
| Cleaning Counter | `cleaning_counter` | 12/ffde | CLEANING 4WEB | Diagnostic |
| Service Counter | `service_counter` | 12/ffdf | SERVICE 4WEB | Diagnostic, disabled by default |

Register 12/fff7 (room temp) is also parsed but not exposed as an entity — it duplicates the 0310 sensor block. 12/ffff (exhaust temp) is read over TCP on every poll: on some stoves 0310 byte 4 stays 0.

Every `12` and `0e` record has the same layout: `<group + address, 3 bytes> <value, 2> <min, 2> <max, 2> ...`. "temp unit" means 0.1 °C or whole °C, see [Temperature unit](#temperature-unit).

### Full store register map

| Prefix | Register | Group | Decode | Key |
|--------|----------|-------|--------|-----|
| `10` | 0310 main block | compound | `_decode_0310()` — 19 bytes | state, error, on_off, exhaust_temp, room_temp |
| `12ffff` | Exhaust temp | 12 | bytes 3-4, ×1 | exhaust_temp_store (also polled over TCP) |
| `12fff7` | Room temp | 12 | bytes 3-4, temp unit | room_temp_store (duplicate) |
| `12ffe0` | Remote room temp | 12 | bytes 3-4, temp unit | remote_room_temp |
| `12ffe8` | Remote room temp 2 | 12 | bytes 3-4, temp unit | remote_room_temp_2 |
| `12ffed` | Airflow | 12 | bytes 3-4, ×1 | airflow |
| `12ffde` | Cleaning counter | 12 | bytes 3-4, ×1 | cleaning_counter |
| `12ffdf` | Service counter | 12 | bytes 3-4, ×1 | service_counter |
| `12005a` | Target temp | 12 | bytes 3-4, temp unit | target_temp |
| `120058` | Unknown | 12 | bytes 3-4, ×1 | reg_120058 |
| `120059` | Unknown | 12 | bytes 3-4, ×1 | reg_120059 |
| `0e016c` | Combustion power | 0e | bytes 3-4 | power |
| `0e023f` | Heating fan power | 0e | bytes 3-4 | heating_fan_power |
| `0e0266` | Ducted fan 1 | 0e | bytes 3-4 | ducted_fan_1 |
| `0e027e` | Ducted fan 2 | 0e | bytes 3-4 | ducted_fan_2 |
| `0e0231` | Unknown | 0e | bytes 3-4 | reg_0e0231 |
| `0c81` | Module info | 0c | raw hex | module_info |

## How Sensors Are Updated

The integration uses two data sources:

1. **TCP polling** (primary): Direct queries to the module over TCP:80 using the 2WC protocol. Polls every 30 seconds in local mode, every 120 seconds when the proxy is active.

2. **Proxy push** (real-time): When the proxy is active, the module pushes sensor data via `POST /api/devices/store` every time values change (typically within seconds of a change) and periodically as a keepalive. This data is injected directly into the coordinator, updating all entities immediately without waiting for the next TCP poll.

## 2WC Protocol

The 4HEAT Lite module exposes a TCP server on port 80. The integration sends JSON-encoded 2WC commands to read sensor registers from the stove's Tiemme controller board via the module's RS485 bus.

```
Query:    ["2WC","1","0310"]
Response: ["2WC","1","<38 hex chars>"]
```

The 19-byte response contains the stove state, error code, exhaust temperature, room temperature, and other registers.

### Register Map (0310 response)

| Byte(s) | Field | Unit | Notes |
|---------|-------|------|-------|
| 0 | Header | - | Always 0x10 |
| 1 | Error | enum | See `ERROR_NAMES` in const.py |
| 2 | On/Off | flag | 0=off, 1=on (stays 1 during cooldown) |
| 3 | Unknown | - | |
| 4 | Exhaust temp | °C | 1-byte unsigned; always 0 on some stoves, 12/ffff is used instead |
| 5 | State | enum | See `STATE_NAMES` in const.py |
| 6-9 | Unknown | - | |
| 10-11 | Room temp | temp unit | 2-byte big-endian |
| 12-18 | Unknown | - | |

### State Values

| Code | State |
|------|-------|
| 0 | OFF |
| 1 | Check Up |
| 2-4 | Ignition |
| 5 | Run |
| 6 | Modulation |
| 7 | Extinguishing |
| 8 | Safety |
| 9 | Block |
| 10 | Recover Ignition |
| 11 | Standby |
| 13 | Run M |
| 30-34 | Ignition |

### Error Codes

| Code | Error |
|------|-------|
| 0 | None |
| 1 | Safety Thermostat HV1 |
| 2 | Safety PressureSwitch HV2 |
| 3 | Exhaust Temp lowering |
| 4 | Water over Temperature |
| 5 | Exhaust over Temperature |
| 7 | Encoder: No Signal |
| 8 | Encoder: Fan regulation failed |
| 9 | Low boiler pressure |
| 10 | High boiler pressure |
| 11 | Clock reset (power loss) |
| 12-14 | Failed/Ignition error |
| 15 | Lack of Voltage |
| 16-17 | Ignition error |
| 18 | Lack of Voltage |
| 44 | Door error |

### Write Command Format

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

On whole-degree stoves a write sends back the whole record last read, with only the value replaced. This is the format the 4HEAT cloud sends:
```
["2WC","1","0512005a0019000a00280000000100000000"]
```
- `12005a0019000a00280000000100000000` — the record of 12/005a as read, with the value set to `0019` (25 °C); `000a` and `0028` are its min and max, 10 and 40 °C

The short frame `0512005a0019000a00280000` (from issue #2) is echoed by the module, but on a Ferlux it did not reliably reach the board: the panel kept the old value. With the whole record, target 26→25 and power P1→P3→P1 changed on the panel.

The module answers with the updated register, e.g. `["2WC","1","12005a0019000a0028..."]`. A reply carrying the whole register cache holds the old value, so only a single-record reply is published as the new state.

### Fan setting

On a Ferlux (product `SYEVO0000559`) the fan setting of the panel is not the register the 4HEAT filemap declares for the heating fan. `0e/023f` never moved when the panel's fan changed, and the 4HEAT app, which writes there, could not change it either. The panel's setting is `0e/038c`, an offset from -7 to +7 on the speed the board picks:
```
0e038c 0005 fff9 0007 00000001038c0000      +5, min -7, max +7
```
Values are two's complement (`fff9` = -7). Writing the whole record with the value replaced changed the panel (+5 → +2).

The **Fan register** option (`0e038c` on that stove) adds a fan number entity on that register, with the range the record reports. Other stoves keep it empty. To look for the register on another stove, read the `0e` group one address at a time (`["2WC","1","030e<address>"]`, read-only), change the fan on the panel, read again and compare.

### Temperature unit

Stoves report temperatures either in 0.1 °C (Lasian Eriste) or in whole °C (Jollymec and others). The integration tells them apart from the range of the target register 12/005a, read on every poll before the sensor block:

| Target register range | Unit | Example |
|---|---|---|
| `0064`–`0190` (100–400) | 0.1 °C | `12005a00e600640190…` = 23.0 °C |
| `000a`–`0028` (10–40) | whole °C | `12005a001a000a0028…` = 26 °C |

The unit applies to the room temperature (0310 bytes 10-11, 12/fff7), the remote probes and the target temperature; the climate entity's step and range follow it. The weekly schedule (H24) still uses 0.1 °C and has not been tested on whole-degree stoves.

### Module quirks

- **Busy answer**: the module sometimes replies `["ERR","1","4"]`. Queries are retried twice, 1.5 s apart, and the last data is kept for two failed polls before the entities go unavailable.
- **Whole cache**: a single-register read can come back with the whole register cache (`["2WC","1","1000…","0c81…","12ffff…",…]`). The record that starts with the requested register is picked out of it.
- **One client at a time**: TCP exchanges with the module are serialized inside the integration.
