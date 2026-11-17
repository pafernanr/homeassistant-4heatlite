# Module Scheduling (Cron)

The 4HEAT Lite WiFi module has a built-in scheduler that turns the stove on and off at configured times. The schedule is stored on the module itself, not in HA. The mobile app writes the schedule via the cloud API, and the module executes it locally based on its internal clock.

## How it works

1. The **mobile app** sends schedule commands via **raw TCP** directly to the module on port 80. The app does NOT use the cloud commands queue for schedules.
2. The **module** stores the schedule internally and executes it using its internal clock.
3. The module periodically uploads its current schedule to the cloud via `POST /api/devices/cron`. The cloud stores it but never pushes it back — `GET /api/devices/commands` always returns `[]` for schedule data.
4. The module synchronizes its clock via `GET /api/Devices/timeAlign`.

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
| `count` | Total elements after `H24` and `count`: `(pairs × 2) + 5`. The 5 = `#register`, `program_index`, `ECO`, `COMFORT`, `COMFORT2` |
| `#<register>` | Register reference (e.g., `#13`). The `#` prefix indicates new format |
| `program_index` | Schedule slot (0, 1, or 2). The app stores 3 schedules locally and sends the active slot's index here |
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

A schedule with 57 event pairs (4 daily comfort slots × 7 days, plus day-start OFF transitions):

```
["H24","119","#13","1","180","230","240",
  "0","0",       <- Monday 00:00, OFF
  "450","230",   <- Monday 07:30, COMFORT (23.0°C)
  "570","0",     <- Monday 09:30, OFF
  ...
  "1890","230",  <- Tuesday 07:30, COMFORT
  ...
]
```

count = 57 pairs × 2 + 5 = **119**. This defines 4 daily slots (07:30–09:30, 11:30–13:30, 15:30–17:30, 19:30–21:30) at COMFORT temperature, repeated every day.

**Important:** When queried back via `["CCG","0"]`, the stove returns `count=62` (pair count, not element count). The send and read formats use different count semantics.

#### Protocol constraints

- **JSON must be compact** — no spaces. Use `separators=(",",":")`. The stove returns `["ERR","1","1"]` on spaced JSON via TCP.
- **program_index is 0, 1, or 2** — identifies which of the app's 3 schedule slots this belongs to. The stove accepts all three values (and higher). The stove stores one schedule at a time; program_index is metadata the app uses to track which local slot is active.
- **Minimum 2 transition pairs** — a command with only 1 pair returns `["ERR","1","1"]`.
- **count must be `pairs*2 + 5`** — an incorrect count causes the stove to truncate the schedule. With count=62 (wrong) for 57 pairs, the stove only stored ~33 events.
- **Minutes have 2-minute granularity** — the stove rounds odd minutes up (e.g., 19:31 → 19:32).

### CCS protocol (chronothermostat)

Used by the "Crono" page in the mobile app. Defines 3 time slots per day with enable/disable flags.

```
["CCS","71","<period>","<day1>","<start1>","<end1>","<check1>","<start2>","<end2>","<check2>","<start3>","<end3>","<check3>", "<day2>", ... "<day7>", ...]
```

Captured on `estufa.lan` (write from app, reply `["CCS","1","OK"]`; read `["CCG","0"]` returns the same shape with token `CCG`).

| Field | Description |
|-------|-------------|
| `count` | `"71"` = 1 (period) + 7 days × 10 fields |
| `period` | Mode, observed: `0`=disabled (app toggle off; slot data kept, reply `OK`), `1`=daily (app DAILY tab), `2`=weekly (app WEEKLY tab), `3`=weekend (app WEEKEND tab, Mon–Fri block shared) |
| `dayN` | Day index, `1`–`7` (Mon=1 … Sun=7) |
| `startN/endN` | `HH:MM` strings, e.g. `"00:00"`, `"08:00"` |
| `checkN` | Slot enabled: `1`=on, `0`=off. Unused slots are `"00:00","00:00","0"` |

Each day block is `dayN` followed by 3 slots of `start,end,check`. Each day is always written, even when all slots are off.

Example (daily, Monday slot 1 `00:00–00:59` enabled, all else empty):

```
["CCS","71","1","1","00:00","00:59","1","00:00","00:00","0","00:00","00:00","0","2","00:00","00:00","0","00:00","00:00","0","00:00","00:00","0", ...]
```

Read via `["CCG","0"]` — same shape, token `CCG`. The module also uploads it to `POST /api/devices/cron` as `{"key":"<DeviceKey>","comando":["CCG",...]}`.

Weekend example (`period=3`, app WEEKEND tab with MON–FRI selected, slot 1 `00:00–00:30` enabled): days 1–5 carry `"00:00","00:30","1"`, days 6–7 are empty. The app writes all 7 day blocks in every mode.

`period=0` (disabled) is captured: the app writes `["CCS","71","0",…]` with the slot data kept (`day1` slot 1 `00:00–00:59` still `1`), and the stove replies `["CCS","1","OK"]`.

## Reading the schedule

Send a TCP query to the module on port 80:

```
["CCG","0"]
```

The module responds with its current schedule. The response protocol (`H24` or `CCS`/`CCG`) indicates which schedule type is active.

## Writing the schedule

The integration uses **dual delivery**: TCP direct + proxy command queue.

**TCP (primary):** Send the raw JSON array directly to the module on port 80. This is how the mobile app does it. Takes effect immediately. The stove responds `["H24","1","OK"]` on success or `["ERR","1","1"]` on failure.

```
["H24","119","#13","1","180","230","240","0","0","450","230",...]
```

**Command queue (backup):** The same command is also enqueued in the proxy's in-memory queue. On the module's next `GET /api/devices/commands` poll (~60s), it receives the command wrapped in the queue format:

```json
[{"id":"<device_id>","comando":["H24","119","#13","1","180","230","240","0","0","450","230",...]}]
```

The queue response must use compact JSON (`separators=(",",":")`) to fit within the ESP32's HTTP receive buffer.

## Disabling the schedule

The mobile app disables the schedule by sending a CCS command with `period=0`, which overwrites whatever schedule is active (including H24) with a disabled CCS. The app caches the schedule locally and re-sends it to re-enable.

**Disabling:** `["H24",...]` with two OFF transitions is used when H24 is the selected protocol (the app itself uses CCS `period=0`). When CCS is the selected protocol the integration sends the CCS disable command with `period=0` and empty slots, in the same format as the app. The ECO/COMFORT/COMFORT2 temperatures of the previous H24 schedule are preserved in the H24 form:

```
["H24","9","#13","0","<ECO>","<COMFORT>","<COMFORT2>","0","0","0","0"]
```

count = 2 pairs × 2 + 5 = **9**.

The schedules (both protocols) are stored in the HA config entry options under `schedules` (`protocol`, `h24`, `ccs`). The stove is the source of truth. Each time the options screen opens, the integration reads the stove schedule and merges it into the saved YAML: the entry of the detected protocol that matches becomes the only active one; otherwise the stove schedule is appended as a new `Stove` entry at the end of its protocol section (`h24` or `ccs`). If the stove schedule is disabled, all entries become inactive. The other protocol section is kept (a disabled default is created if absent), so you can save alternatives of both. If the stove cannot be read, the saved YAML is shown with a warning. The stove stores only one schedule at a time, and stoves may support only CCS or both. Setting `active: true` on one entry sends it to the stove; enabling both an H24 and a CCS entry is an error. Setting all entries to `active: false` sends the disable command of the selected `protocol`. If the stove answers `ERR` (other than busy, code 4) the write is treated as unsupported: an error is shown and the previous schedule is kept.

## Proxy behavior

| Mode | `POST /api/devices/cron` | `timeAlign` |
|------|--------------------------|-------------|
| `direct` | Forward to Azure, then acknowledge | Forward to Azure; fall back to local if cloud fails |
| `cloud_keepalive` | Acknowledge only (not mirrored) | Return local fallback with dynamic timezone offset |
| `local_only` | Acknowledge only (not mirrored) | Return local fallback with dynamic timezone offset |

The proxy parses H24 and CCS/CCG data from `POST /api/devices/cron` and caches it (with a `protocol` key) in `device_entry["last_schedule"]`. The `get_schedule` service reads the stove over TCP first (`["CCG","0"]`) and falls back to this cache.
