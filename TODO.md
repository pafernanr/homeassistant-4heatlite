# TODO

## Integration configuration

- [ ] Implement global configuration via HA GUI to set `_LOGGER` level per component (debug/info/warning/error). Allow toggling verbose logging for proxy endpoints without restarting HA or editing YAML.

## Schedule management — DONE (v0.6.0)

Stove schedule (H24 weekly program) is now readable and writable from HA:
- Options Flow: YAML editor (`ObjectSelector`) to view/edit the schedule visually
- Services: `4heatlite.get_schedule` and `4heatlite.set_schedule` for programmatic access
- Proxy: `StoveCronView` now parses and caches the schedule from module POST requests
