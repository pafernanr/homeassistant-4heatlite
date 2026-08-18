"""Config flow for 4HEAT Lite integration."""

import json
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    CONF_PROXY_MODE,
    DOMAIN,
    PROXY_MODE_CLOUD,
    PROXY_MODE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)

CLOUD_TOKEN_URL = "https://wifi4heat.azurewebsites.net/Token"
CLOUD_DETAILS_URL = "https://wifi4heat.azurewebsites.net/api/Devices/Details"


async def _fetch_device_key(email, password, device_id):
    """Authenticate with 4HEAT cloud and fetch DeviceKey for a device."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                CLOUD_TOKEN_URL,
                data={
                    "grant_type": "password",
                    "username": email,
                    "password": password,
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None, "invalid_credentials"
                token_data = await resp.json()
                token = token_data.get("access_token")
                if not token:
                    return None, "invalid_credentials"

            async with session.get(
                f"{CLOUD_DETAILS_URL}?id={device_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status == 404:
                    return None, "device_not_found"
                if resp.status != 200:
                    return None, "cloud_error"
                details = await resp.json()

    except aiohttp.ClientError:
        return None, "cloud_error"
    except Exception:
        _LOGGER.exception("Unexpected error fetching device key")
        return None, "cloud_error"

    last_msg = details.get("LastMessageReceived")
    if not last_msg:
        return None, "no_device_key"

    try:
        msg_data = json.loads(last_msg)
        device_key = msg_data.get("DeviceKey")
    except (json.JSONDecodeError, TypeError):
        return None, "no_device_key"

    if not device_key:
        return None, "no_device_key"

    return device_key, None


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 1

    def __init__(self):
        self._user_input = {}

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
                proxy_mode = user_input.get(CONF_PROXY_MODE, PROXY_MODE_LOCAL)
                if proxy_mode == PROXY_MODE_CLOUD:
                    self._user_input = user_input
                    return await self.async_step_cloud()

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
                    vol.Optional(
                        CONF_PROXY_MODE, default=PROXY_MODE_LOCAL
                    ): vol.In(
                        {
                            PROXY_MODE_LOCAL: "Local only (Sensors only, Controls unavailable)",
                            PROXY_MODE_CLOUD: "Cloud sync (Sync Controls from/to the Cloud)",
                        }
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_cloud(self, user_input=None):
        errors = {}

        if user_input is not None:
            email = user_input["cloud_email"].strip()
            password = user_input["cloud_password"]
            device_id = self._user_input[CONF_DEVICE_ID].strip()

            device_key, error = await _fetch_device_key(
                email, password, device_id
            )

            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=self._user_input[CONF_NAME],
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_NAME: self._user_input[CONF_NAME],
                        CONF_HOST: self._user_input[CONF_HOST].strip(),
                        CONF_DEVICE_KEY: device_key,
                    },
                    options={CONF_PROXY_MODE: PROXY_MODE_CLOUD},
                )

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required("cloud_email"): str,
                    vol.Required("cloud_password"): str,
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
                            PROXY_MODE_LOCAL: "Local only (Sensors only, Controls unavailable)",
                            PROXY_MODE_CLOUD: "Cloud sync (Sync Controls from/to the Cloud)",
                        }
                    ),
                }
            ),
        )
