# TODO

## Integration configuration

- [ ] Implement global configuration via HA GUI to set `_LOGGER` level per component (debug/info/warning/error). Allow toggling verbose logging for proxy endpoints without restarting HA or editing YAML.

## /cron endpoint — WONTFIX

Stove-side scheduling (H24 weekly program, CCG daily timer) is redundant with HA automations. HA already controls ON/OFF, temperature, and power via the proxy command queue. Using HA schedule helpers and automations is more flexible and keeps all logic in one place. Proxy stub (`StoveCronView`) stays as-is to acknowledge module POST requests.
