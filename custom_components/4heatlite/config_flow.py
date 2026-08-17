"""Config flow for 4HEAT Lite integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from .const import (
    CONF_DEVICE_ID,
    CONF_PROXY_ENABLED,
    CONF_PROXY_MODE,
    DEFAULT_DEVICE_ID,
    DOMAIN,
    PROXY_MODE_CLOUD,
    PROXY_MODE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]

            for entry in self._async_current_entries():
                if entry.data.get(CONF_HOST) == host:
                    errors[CONF_HOST] = "already_configured"
                    break

            if not errors:
                api = FourHeatLiteApi(host)
                can_connect = await self.hass.async_add_executor_job(
                    api.test_connection
                )
                if can_connect:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data=user_input,
                    )
                errors[CONF_HOST] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default="Pellet Stove"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional(CONF_PROXY_ENABLED, default=False): bool,
                    vol.Optional(
                        CONF_DEVICE_ID, default=DEFAULT_DEVICE_ID
                    ): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return FourHeatLiteOptionsFlow()


class FourHeatLiteOptionsFlow(config_entries.OptionsFlow):
    """Handle options for 4HEAT Lite."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PROXY_MODE,
                        default=self.config_entry.options.get(
                            CONF_PROXY_MODE, PROXY_MODE_LOCAL
                        ),
                    ): vol.In(
                        {
                            PROXY_MODE_LOCAL: "Local only",
                            PROXY_MODE_CLOUD: "Cloud sync",
                        }
                    ),
                }
            ),
        )
