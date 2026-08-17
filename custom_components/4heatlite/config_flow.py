"""Config flow for 4HEAT Lite integration."""

import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from .const import (
    CONF_DEVICE_ID,
    CONF_PROXY_ENABLED,
    CONF_PROXY_MODE,
    DOMAIN,
    PROXY_MODE_CLOUD,
    PROXY_MODE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)

DETAILS_URL = "http://wifi4heat-linux.azurewebsites.net/api/Devices/Details"


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 1

    def __init__(self):
        self._device_id = None
        self._device_name = None
        self._device_host = None

    async def _fetch_device_details(self, device_id: str) -> dict | None:
        """Fetch device details from cloud API (unauthenticated)."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    DETAILS_URL, params={"id": device_id}, timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "Id" in data:
                            return data
        except (aiohttp.ClientError, TimeoutError):
            pass
        return None

    async def async_step_user(self, user_input=None):
        """Step 1: Ask for device ID, validate via cloud API."""
        errors = {}

        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID].strip()

            for entry in self._async_current_entries():
                if entry.data.get(CONF_DEVICE_ID) == device_id:
                    errors[CONF_DEVICE_ID] = "already_configured"
                    break

            if not errors:
                details = await self._fetch_device_details(device_id)
                if details is None:
                    errors[CONF_DEVICE_ID] = "invalid_device_id"
                else:
                    self._device_id = device_id
                    self._device_name = details.get("Name") or "Pellet Stove"
                    self._device_host = details.get("IpAddress") or ""
                    return await self.async_step_configure()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): str,
                }
            ),
            errors=errors,
        )

    async def async_step_configure(self, user_input=None):
        """Step 2: Confirm name, host, and proxy settings."""
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
                        data={
                            CONF_DEVICE_ID: self._device_id,
                            CONF_NAME: user_input[CONF_NAME],
                            CONF_HOST: host,
                            CONF_PROXY_ENABLED: user_input.get(CONF_PROXY_ENABLED, False),
                        },
                    )
                errors[CONF_HOST] = "cannot_connect"

        return self.async_show_form(
            step_id="configure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=self._device_name): str,
                    vol.Required(CONF_HOST, default=self._device_host): str,
                    vol.Optional(CONF_PROXY_ENABLED, default=False): bool,
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
