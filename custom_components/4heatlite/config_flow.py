"""Config flow for 4HEAT Lite integration."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from .const import (
    CONF_DEVICE_ID,
    CONF_PROXY_MODE,
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
                if can_connect:
                    return self.async_create_entry(
                        title=user_input[CONF_NAME],
                        data={
                            CONF_DEVICE_ID: device_id,
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_HOST: host,
                        },
                        options={
                            CONF_PROXY_MODE: user_input.get(
                                CONF_PROXY_MODE, PROXY_MODE_LOCAL
                            ),
                        },
                    )
                errors[CONF_HOST] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_NAME, default="Pellet Stove"): str,
                    vol.Required(CONF_HOST): str,
                    vol.Optional(
                        CONF_PROXY_MODE, default=PROXY_MODE_LOCAL
                    ): vol.In(
                        {
                            PROXY_MODE_LOCAL: "Local only",
                            PROXY_MODE_CLOUD: "Cloud sync",
                        }
                    ),
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

        proxy_mode = self.config_entry.options.get(
            CONF_PROXY_MODE, PROXY_MODE_LOCAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PROXY_MODE,
                        default=proxy_mode,
                    ): vol.In(
                        {
                            PROXY_MODE_LOCAL: "Local only",
                            PROXY_MODE_CLOUD: "Cloud sync",
                        }
                    ),
                }
            ),
        )
