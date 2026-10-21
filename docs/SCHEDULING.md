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

## Reading the schedule

Send a TCP query to the module on port 80:

```
["CCG","0"]
```

The module responds with its current schedule. Depending on the schedule type, the response uses one of two protocols:

### H24 protocol (24-hour / weekly heating program)

```
["H24","<count>","#<register>","<program_index>","<ECO>","<COMFORT>","<COMFORT2>", <minute>,<temp>, <minute>,<temp>, ...]
```

| Field | Description |
|-------|-------------|
| `count` | Number of data elements after the protocol identifier |
| `#<register>` | Register reference (e.g., `#13`). The `#` prefix indicates new format |
| `program_index` | Which heating program (0-based) |
| `ECO` | ECO temperature value (raw, may need dividing by multiplier) |
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

### CCG protocol (chronothermostat / weekly program)

```
["CCG", ...]
```

Used by the chrono/timer page in the app. The response contains 7 days × 3 time slots, each with start time, end time, and enabled flag. Parsed by the app into per-day schedules (Mon–Sun) plus special modes (weekly/weekend grouping).

The CCG format uses `HH:MM` strings (5 chars) for times and a single-char flag (`0`/`1`) for enabled/disabled, grouped in blocks of 9 values per day (3 slots × 3 fields: start, end, check), with 10-element spacing per day block.

## Writing the schedule

Schedule changes are sent via `POST /api/devices/command` with the same array format:

```json
{
  "id": "<device_id>",
  "comando": ["H24","<count>","#<register>","<index>","<ECO>","<COMFORT>","<COMFORT2>", ...]
}
```

The command is queued server-side (or in the proxy's command queue) and delivered to the module on its next `GET /api/devices/commands` poll (~60 seconds).

## Proxy behavior

| Mode | `POST /api/devices/cron` | `timeAlign` |
|------|--------------------------|-------------|
| `local_only` | Acknowledge only (schedule data discarded) | Return local fallback with dynamic timezone offset |
| `cloud_sync` | Forward to Azure, then acknowledge | Forward to Azure; fall back to local if cloud fails |

The proxy does not currently store or expose the schedule data received via `POST /api/devices/cron`. To read the current schedule, query the module directly via TCP (`["CCG","0"]`).
