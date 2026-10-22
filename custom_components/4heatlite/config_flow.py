"""Config flow for 4HEAT Lite integration."""

import json
import logging

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig

from .const import (
    CONF_ACTIVE_SCHEDULE,
    CONF_CACHED_SCHEDULES,
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    CONF_PROXY_MODE,
    DATA_COORDINATOR,
    DOMAIN,
    NUM_SCHEDULE_SLOTS,
    PROXY_MODE_DIRECT,
    PROXY_MODE_LOCAL,
)
from .proxy import enqueue_command

_LOGGER = logging.getLogger(__name__)

AZURE_TOKEN_URL = "https://wifi4heat.azurewebsites.net/Token"
AZURE_DETAILS_URL = "https://wifi4heat.azurewebsites.net/api/devices/Details"


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 3

    _token: str | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: authenticate with 4HEAT cloud using email/password."""
        errors = {}

        if user_input is not None:
            email = user_input["email"].strip()
            password = user_input["password"]

            token = await self._async_authenticate(email, password)
            if token:
                self._token = token
                return await self.async_step_device()
            else:
                errors["base"] = "auth_failed"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("email"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_device(self, user_input=None):
        """Step 2: enter device details and fetch DeviceKey from Azure."""
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

            device_key = ""
            if not errors:
                device_key = await self._async_fetch_device_key(device_id)
                if not device_key:
                    errors["base"] = "device_key_failed"

            if not errors:
                local_only = user_input.get("local_only", False)
                proxy_mode = PROXY_MODE_LOCAL if local_only else PROXY_MODE_DIRECT
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                        CONF_DEVICE_KEY: device_key,
                    },
                    options={CONF_PROXY_MODE: proxy_mode},
                )

        return self.async_show_form(
            step_id="device",
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

    async def _async_authenticate(self, email: str, password: str) -> str | None:
        """POST /Token to get an access token."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    AZURE_TOKEN_URL,
                    data={
                        "grant_type": "password",
                        "username": email,
                        "password": password,
                    },
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning("4HEAT auth failed: HTTP %s", resp.status)
                        return None
                    result = await resp.json(content_type=None)
                    return result.get("access_token")
        except Exception:
            _LOGGER.exception("4HEAT auth request failed")
            return None

    async def _async_fetch_device_key(self, device_id: str) -> str:
        """GET /api/devices/Details with Bearer token to retrieve DeviceKey."""
        if not self._token:
            return ""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    AZURE_DETAILS_URL,
                    params={"id": device_id},
                    headers={"Authorization": f"Bearer {self._token}"},
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "4HEAT Details fetch failed: HTTP %s", resp.status
                        )
                        return ""
                    result = await resp.json(content_type=None)
                    key = result.get("DeviceKey", "")
                    if not key:
                        last_msg = result.get("LastMessageReceived", "")
                        if last_msg:
                            try:
                                msg = json.loads(last_msg)
                                key = msg.get("DeviceKey", "")
                            except (ValueError, TypeError):
                                pass
                    if key:
                        _LOGGER.info(
                            "Fetched DeviceKey for device %s", device_id
                        )
                    return key
        except Exception:
            _LOGGER.exception("4HEAT Details request failed")
            return ""

    @staticmethod
    def async_get_options_flow(config_entry):
        return FourHeatLiteOptionsFlow()


PROXY_STATE = "proxy_state"


SCHEDULE_OPTIONS = [
    {"value": "none", "label": "Disabled"},
    {"value": "0", "label": "Schedule 1"},
    {"value": "1", "label": "Schedule 2"},
    {"value": "2", "label": "Schedule 3"},
]

EDIT_OPTIONS = [
    {"value": "skip", "label": "Don't edit"},
    {"value": "0", "label": "Edit Schedule 1"},
    {"value": "1", "label": "Edit Schedule 2"},
    {"value": "2", "label": "Edit Schedule 3"},
]


class FourHeatLiteOptionsFlow(config_entries.OptionsFlow):
    """Handle options for 4HEAT Lite."""

    def __init__(self):
        self._pending_options: dict | None = None
        self._edit_slot: int | None = None

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            local_only = user_input.get("local_only", False)
            proxy_mode = PROXY_MODE_LOCAL if local_only else PROXY_MODE_DIRECT
            active_val = user_input.get("active_schedule", "none")
            edit_val = user_input.get("edit_slot", "skip")

            active_schedule = int(active_val) if active_val != "none" else None
            old_active = self.config_entry.options.get(CONF_ACTIVE_SCHEDULE)

            domain_data = self.hass.data.get(DOMAIN, {})
            proxy_state = domain_data.get(PROXY_STATE, {})
            device_id = self.config_entry.data.get(CONF_DEVICE_ID, "")
            schedules = list(
                self.config_entry.options.get(CONF_CACHED_SCHEDULES)
                or [None] * NUM_SCHEDULE_SLOTS
            )

            if active_schedule != old_active:
                if active_schedule is not None and schedules[active_schedule]:
                    cmd = FourHeatLiteApi.build_schedule_command(
                        schedules[active_schedule], active_schedule
                    )
                    if not self._deliver_command(cmd, device_id, proxy_state):
                        errors["base"] = "schedule_send_failed"
                    else:
                        self._update_proxy_schedule(schedules[active_schedule])
                elif active_schedule is None:
                    prev = old_active if old_active is not None else 0
                    prev_sched = schedules[prev] if prev < len(schedules) else None
                    cmd = FourHeatLiteApi.build_disable_schedule_command(
                        prev_sched, prev
                    )
                    if not self._deliver_command(cmd, device_id, proxy_state):
                        errors["base"] = "schedule_send_failed"

            if not errors:
                self._pending_options = {
                    CONF_PROXY_MODE: proxy_mode,
                    CONF_ACTIVE_SCHEDULE: active_schedule,
                    CONF_CACHED_SCHEDULES: schedules,
                }

                if edit_val != "skip":
                    self._edit_slot = int(edit_val)
                    return await self.async_step_edit_schedule()

                return self.async_create_entry(data=self._pending_options)

        current_mode = self.config_entry.options.get(
            CONF_PROXY_MODE, PROXY_MODE_DIRECT
        )
        current_active = self.config_entry.options.get(CONF_ACTIVE_SCHEDULE)
        active_default = str(current_active) if current_active is not None else "none"

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "local_only",
                        default=(current_mode == PROXY_MODE_LOCAL),
                    ): bool,
                    vol.Optional(
                        "active_schedule",
                        default=active_default,
                    ): SelectSelector(SelectSelectorConfig(
                        options=SCHEDULE_OPTIONS, mode="dropdown"
                    )),
                    vol.Optional(
                        "edit_slot",
                        default="skip",
                    ): SelectSelector(SelectSelectorConfig(
                        options=EDIT_OPTIONS, mode="dropdown"
                    )),
                }
            ),
            errors=errors,
        )

    async def async_step_edit_schedule(self, user_input=None):
        errors = {}
        slot = self._edit_slot

        if user_input is not None:
            schedule_data = user_input.get("schedule")

            if schedule_data:
                error = FourHeatLiteApi.validate_schedule(schedule_data)
                if error:
                    errors["schedule"] = error
                else:
                    self._pending_options[CONF_CACHED_SCHEDULES][slot] = schedule_data
                    active = self._pending_options.get(CONF_ACTIVE_SCHEDULE)
                    if active == slot:
                        domain_data = self.hass.data.get(DOMAIN, {})
                        proxy_state = domain_data.get(PROXY_STATE, {})
                        device_id = self.config_entry.data.get(CONF_DEVICE_ID, "")
                        cmd = FourHeatLiteApi.build_schedule_command(
                            schedule_data, slot
                        )
                        if not self._deliver_command(cmd, device_id, proxy_state):
                            errors["schedule"] = "schedule_send_failed"
                        else:
                            self._update_proxy_schedule(schedule_data)

            if not errors:
                return self.async_create_entry(data=self._pending_options)

        from homeassistant.helpers.selector import ObjectSelector

        schedules = self._pending_options.get(CONF_CACHED_SCHEDULES, [None] * NUM_SCHEDULE_SLOTS)
        current = schedules[slot] if slot < len(schedules) else None

        return self.async_show_form(
            step_id="edit_schedule",
            data_schema=vol.Schema(
                {
                    vol.Optional("schedule", default=current): ObjectSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"slot_name": f"Schedule {slot + 1}"},
        )

    def _deliver_command(self, cmd, device_id, proxy_state) -> bool:
        """Send command via TCP and enqueue in proxy."""
        tcp_ok = False
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = entry_data.get(DATA_COORDINATOR)
        if coordinator:
            result = coordinator.api.send_command(cmd)
            if result and len(result) >= 3 and str(result[2]) == "OK":
                tcp_ok = True

        queued = False
        if device_id:
            queued = enqueue_command(proxy_state, device_id, cmd)

        return tcp_ok or queued

    def _update_proxy_schedule(self, schedule_data: dict) -> None:
        """Sync proxy cache."""
        domain_data = self.hass.data.get(DOMAIN, {})
        proxy_state = domain_data.get(PROXY_STATE, {})
        for dev in proxy_state.get("devices", {}).values():
            if dev.get("entry_id") == self.config_entry.entry_id:
                dev["last_schedule"] = schedule_data
                break
