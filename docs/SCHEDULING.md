# Module Scheduling (Cron)

The 4HEAT Lite WiFi module has a built-in scheduler that turns the stove on and off at configured times. The schedule is stored on the module itself, not in HA. The mobile app writes the schedule via the cloud API, and the module executes it locally based on its internal clock.

## How it works

1. The **mobile app** sends schedule commands to the cloud API (`POST /api/devices/command`), which queues them for the module.
2. The **module** polls `GET /api/devices/commands`, receives the schedule command, and stores it internally.
3. The module periodically uploads its current schedule to the cloud via `POST /api/devices/cron` (acknowledged by the proxy but not parsed).
4. The module executes the schedule using its internal clock, which it synchronizes via `GET /api/Devices/timeAlign`.

## Clock synchronization (timeAlign)

The module calls `GET /api/Devices/timeAlign?deviceKey=<key>` after each commands poll. The response:

```json
{
  "gmtOffset": 7200,
  "timestamp": 1792576277
}
```

**Important:** `timestamp` is **not** a standard Unix epoch. It is `epoch_UTC + gmtOffset` — the cloud returns the timestamp already shifted to local time. The module uses this value directly as its local clock. If the timestamp is a raw UTC epoch, the module clock will be behind by `gmtOffset` seconds.

The proxy computes `gmtOffset` dynamically from the HA server's system timezone, so it adjusts automatically for DST transitions (e.g., CEST 7200 → CET 3600).

## Schedule protocols

The module supports two mutually exclusive schedule protocols. Only one can be active at a time — writing one replaces the other. Both are read via the same query (`["CCG","0"]`); the response format indicates which is active.

### H24 protocol (24-hour heating program)

Used by the "Heating" page in the mobile app. Defines temperature bands (ECO, COMFORT, COMFORT2) with minute-precision transitions across the entire week.

```
["H24","<count>","#<register>","<program_index>","<ECO>","<COMFORT>","<COMFORT2>", <minute>,<temp>, <minute>,<temp>, ...]
```

| Field | Description |
|-------|-------------|
| `count` | Number of data elements after the count field |
| `#<register>` | Register reference (e.g., `#13`). The `#` prefix indicates new format |
| `program_index` | Which heating program (0-based) |
| `ECO` | ECO temperature value (raw, divided by 10 for °C) |
| `COMFORT` | COMFORT temperature value |
| `COMFORT2` | COMFORT2 temperature value |
| pairs | `(minute_in_week, temperature)` — transitions through the week |

**Minutes are counted from Monday 00:00.** Each day has 1440 minutes:

| Day | Minute range |
|-----|-------------|
| Monday | 0–1439 |
| Tuesday | 1440–2879 |
| Wednesday | 2880–4319 |
| Thursday | 4320–5759 |
| Friday | 5760–7199 |
| Saturday | 7200–8639 |
| Sunday | 8640–10079 |

Temperature values in the pairs match one of the defined bands (ECO, COMFORT, COMFORT2) or `0` for OFF. The module switches to the specified temperature at each minute mark.

#### Example

```
["H24","62","#13","0","180","230","240",
  "0","0",       <- Monday 00:00, OFF
  "450","230",   <- Monday 07:30, COMFORT (23.0°C)
  "570","0",     <- Monday 09:30, OFF
  ...
  "1890","230",  <- Tuesday 07:30, COMFORT
  ...
]
```

This defines 4 daily slots (07:30–09:30, 11:30–13:30, 15:30–17:30, 19:30–21:30) at COMFORT temperature, repeated every day.

### CCS protocol (chronothermostat)

Used by the "Crono" page in the mobile app. Defines 3 time slots per day with enable/disable flags.

```
["CCS","<count>","<period>","<day>","<start1>","<end1>","<check1>","<start2>","<end2>","<check2>","<start3>","<end3>","<check3>", ...]
```

| Field | Description |
|-------|-------------|
| `count` | Total element count (period + 7 days × 10 fields) |
| `period` | Timer mode: `0`=disabled, `1`=per-day, `2`=weekly, `3`=weekday/weekend |
| `day` | Day number (1–7) |
| `startN/endN` | Time range in `HH:MM` format |
| `checkN` | Slot enabled: `0`=off, `1`=on |

When `period=0`, the schedule is stored but inactive — the module ignores all time slots. The mobile app uses this to "disable" without erasing slot data.

Read via `["CCG","0"]` — response starts with `"CCS"` or `"CCG"` (same format).

## Reading the schedule

Send a TCP query to the module on port 80:

```
["CCG","0"]
```

The module responds with its current schedule. The response protocol (`H24` or `CCS`/`CCG`) indicates which schedule type is active.

## Writing the schedule

Schedule changes are sent via `POST /api/devices/command` (cloud) or directly via TCP (local):

```json
{
  "id": "<device_id>",
  "comando": ["H24","<count>","#<register>","<index>","<ECO>","<COMFORT>","<COMFORT2>", ...]
}
```

The command is queued server-side (or in the proxy's command queue) and delivered to the module on its next `GET /api/devices/commands` poll (~60 seconds). For local TCP, the command is sent directly and takes effect immediately.

## Disabling the schedule

The mobile app disables the schedule by sending a CCS command with `period=0`, which overwrites whatever schedule is active (including H24) with a disabled CCS. The app caches the schedule locally and re-sends it to re-enable.

**This integration uses H24 only.** Instead of switching to CCS, disabling sends an H24 command with no active time slots — a single transition at minute 0 with temperature 0 (OFF). The ECO/COMFORT/COMFORT2 temperatures from the current schedule are preserved in the command:

```
["H24","6","#13","0","<ECO>","<COMFORT>","<COMFORT2>","0","0"]
```

The schedule data is cached in the HA config entry options and re-sent when re-enabled. The "Schedule Enabled" checkbox in the integration options controls this.

## Proxy behavior

| Mode | `POST /api/devices/cron` | `timeAlign` |
|------|--------------------------|-------------|
| `local_only` | Acknowledge only (schedule data discarded) | Return local fallback with dynamic timezone offset |
| `direct` | Forward to Azure, then acknowledge | Forward to Azure; fall back to local if cloud fails |

The proxy does not currently store or expose the schedule data received via `POST /api/devices/cron`. To read the current schedule, query the module directly via TCP (`["CCG","0"]`).
