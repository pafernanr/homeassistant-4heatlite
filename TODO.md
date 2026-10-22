# TODO

## Integration configuration

- [ ] Implement global configuration via HA GUI to set `_LOGGER` level per component (debug/info/warning/error). Allow toggling verbose logging for proxy endpoints without restarting HA or editing YAML.

## Schedule management — DONE (v0.6.0)

Stove schedule (H24 weekly program) is now readable and writable from HA:
- Options Flow: YAML editor (`ObjectSelector`) to view/edit the schedule visually
- Services: `4heatlite.get_schedule` and `4heatlite.set_schedule` for programmatic access
- Proxy: `StoveCronView` now parses and caches the schedule from module POST requests

## Direct TCP writes — DONE (v0.7.0)

All write commands (ON/OFF, temperature, power, schedule) now sent via direct TCP to the module instead of the proxy command queue. Instant response, no ~60s polling delay.
- `cloud_sync` mode removed — no longer needed
- Two modes: `direct` (default, no setup) and `local_only` (blocks cloud, requires DNS/firewall)
- Config flow simplified: checkbox instead of dropdown, no cloud credentials step

## HACS default inclusion — [guide](ADD2HACS.md)

- [ ] Submit brand assets (icon/logo) to [home-assistant/brands](https://github.com/home-assistant/brands) under `custom_integrations/4heatlite/`
- [ ] Submit PR to [hacs/default](https://github.com/hacs/default) adding entry to `integrations.json`
