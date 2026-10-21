"""Config flow for 4HEAT Lite integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from homeassistant.helpers.selector import ObjectSelector

from .api import FourHeatLiteApi
from .const import (
    CONF_CACHED_SCHEDULE,
    CONF_DEVICE_ID,
    CONF_PROXY_MODE,
    CONF_SCHEDULE_ENABLED,
    DATA_COORDINATOR,
    DOMAIN,
    PROXY_MODE_DIRECT,
    PROXY_MODE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()
            host = user_input[CONF_HOST].strip()

            for entry in self._async_current_entries():
                if entry.data.get(CONF_DEVICE_ID) == device_id:
                    errors[CONF_DEVICE_ID] = "already_configured"
                    break
                if entry.data.get(CONF_HOST) == host:
                    errors[CONF_HOST] = "already_configured"
                    break

            if not errors:
                api = FourHeatLiteApi(host)
                can_connect = await self.hass.async_add_executor_job(
                    api.test_connection
                )
                if not can_connect:
                    errors[CONF_HOST] = "cannot_connect"

            if not errors:
                local_only = user_input.get("local_only", False)
                proxy_mode = PROXY_MODE_LOCAL if local_only else PROXY_MODE_DIRECT
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                    },
                    options={CONF_PROXY_MODE: proxy_mode},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_NAME, default="Pellet Stove"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional("local_only", default=False): bool,
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return FourHeatLiteOptionsFlow()


PROXY_STATE = "proxy_state"


class FourHeatLiteOptionsFlow(config_entries.OptionsFlow):
    """Handle options for 4HEAT Lite."""

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            local_only = user_input.get("local_only", False)
            proxy_mode = PROXY_MODE_LOCAL if local_only else PROXY_MODE_DIRECT
            schedule_enabled = user_input.get("schedule_enabled", True)
            schedule_data = user_input.get("schedule")

            entry_data = self.hass.data.get(DOMAIN, {}).get(
                self.config_entry.entry_id, {}
            )
            coordinator = entry_data.get(DATA_COORDINATOR)

            if schedule_enabled and schedule_data:
                error = FourHeatLiteApi.validate_schedule(schedule_data)
                if error:
                    errors["schedule"] = error
                else:
                    cmd = FourHeatLiteApi.build_schedule_command(schedule_data)
                    if coordinator:
                        result = await self.hass.async_add_executor_job(
                            coordinator.api.send_command, cmd
                        )
                        if result is None:
                            errors["schedule"] = "schedule_send_failed"
                    else:
                        errors["schedule"] = "schedule_send_failed"
            elif not schedule_enabled:
                cmd = FourHeatLiteApi.build_disable_schedule_command(schedule_data)
                if coordinator:
                    result = await self.hass.async_add_executor_job(
                        coordinator.api.send_command, cmd
                    )
                    if result is None:
                        errors["schedule"] = "schedule_send_failed"
                else:
                    errors["schedule"] = "schedule_send_failed"

            if not errors:
                options = {
                    CONF_PROXY_MODE: proxy_mode,
                    CONF_SCHEDULE_ENABLED: schedule_enabled,
                }
                if schedule_data:
                    options[CONF_CACHED_SCHEDULE] = schedule_data
                else:
                    cached = self.config_entry.options.get(CONF_CACHED_SCHEDULE)
                    if cached:
                        options[CONF_CACHED_SCHEDULE] = cached
                return self.async_create_entry(data=options)

        current_mode = self.config_entry.options.get(
            CONF_PROXY_MODE, PROXY_MODE_DIRECT
        )
        current_enabled = self.config_entry.options.get(
            CONF_SCHEDULE_ENABLED, True
        )
        current_schedule = await self._get_current_schedule()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "local_only",
                        default=(current_mode == PROXY_MODE_LOCAL),
                    ): bool,
                    vol.Optional(
                        "schedule_enabled",
                        default=current_enabled,
                    ): bool,
                    vol.Optional("schedule", default=current_schedule): ObjectSelector(),
                }
            ),
            errors=errors,
        )

    async def _get_current_schedule(self) -> dict | None:
        """Read current schedule from cache, proxy, or module TCP."""
        if not self.config_entry.options.get(CONF_SCHEDULE_ENABLED, True):
            cached = self.config_entry.options.get(CONF_CACHED_SCHEDULE)
            if cached:
                return cached

        domain_data = self.hass.data.get(DOMAIN, {})
        proxy_state = domain_data.get(PROXY_STATE, {})

        for dev in proxy_state.get("devices", {}).values():
            if dev.get("entry_id") == self.config_entry.entry_id:
                cached = dev.get("last_schedule")
                if cached:
                    return cached
                break

        entry_data = domain_data.get(self.config_entry.entry_id, {})
        coordinator = entry_data.get(DATA_COORDINATOR)
        if coordinator:
            return await self.hass.async_add_executor_job(
                coordinator.api.query_schedule
            )

        return None
