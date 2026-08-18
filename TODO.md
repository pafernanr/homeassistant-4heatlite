# TODO

## Integration configuration

- [ ] Implement global configuration via HA GUI to set `_LOGGER` level per component (debug/info/warning/error). Allow toggling verbose logging for proxy endpoints without restarting HA or editing YAML.

## /cron endpoint

- [ ] Capture and decode cron POST body from module
- [ ] Parse schedule/timer data in `StoveCronView`
- [ ] Store parsed schedule in coordinator
- [ ] Expose schedule as HA entities
- [ ] Implement GET `/api/devices/cron` on proxy (read schedule back)
- [ ] Write-back: send schedule changes to module via command queue
