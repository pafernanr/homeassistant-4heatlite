"""Config flow for 4HEAT Lite integration."""

import json
import logging
import socket

import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME

from .api import FourHeatLiteApi
from .discovery import discover_modules
from homeassistant.helpers.selector import ObjectSelector

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    DEFAULT_FAN_REGISTER,
    CONF_MODULE_ADDRESS,
    CONF_PROXY_MODE,
    CONF_SCHEDULES,
    DATA_COORDINATOR,
    DOMAIN,
    PROTOCOL_CCS,
    PROTOCOL_H24,
    PROXY_MODE_DIRECT,
    PROXY_MODE_KEEPALIVE,
    PROXY_MODE_LOCAL,
)
from .proxy import enqueue_command

_LOGGER = logging.getLogger(__name__)

AZURE_TOKEN_URL = "https://wifi4heat.azurewebsites.net/Token"
AZURE_DETAILS_URL = "https://wifi4heat.azurewebsites.net/api/devices/Details"
MANUAL_ENTRY = "__manual__"


class FourHeatLiteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for 4HEAT Lite."""

    VERSION = 5

    _token: str | None = None
    _discovered_device_id: str | None = None
    _discovered_host: str | None = None

    async def async_step_user(self, user_input=None):
        """Step 1: authenticate with 4HEAT cloud using email/password."""
        errors = {}

        if user_input is not None:
            email = user_input["email"].strip()
            password = user_input["password"]

            token = await self._async_authenticate(email, password)
            if token:
                self._token = token
                return await self.async_step_discovery()
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

    async def async_step_discovery(self, user_input=None):
        """Step 2: scan for modules on the local network."""
        if user_input is not None:
            selected = user_input.get("selected_device", MANUAL_ENTRY)
            if selected != MANUAL_ENTRY:
                parts = selected.split("|", 1)
                if len(parts) == 2:
                    self._discovered_device_id = parts[0]
                    self._discovered_host = parts[1]
            return await self.async_step_device()

        modules = await self.hass.async_add_executor_job(discover_modules)

        configured_ids = {
            entry.data.get(CONF_DEVICE_ID)
            for entry in self._async_current_entries()
        }
        modules = [m for m in modules if m["device_id"] not in configured_ids]

        if not modules:
            return await self.async_step_device()

        options = {
            f"{m['device_id']}|{m['ip']}": f"{m['device_id']} ({m['ip']})"
            for m in modules
        }
        options[MANUAL_ENTRY] = "Manual entry"

        return self.async_show_form(
            step_id="discovery",
            data_schema=vol.Schema(
                {
                    vol.Required("selected_device"): vol.In(options),
                }
            ),
        )

    async def async_step_device(self, user_input=None):
        """Step 3: confirm device details and fetch DeviceKey from Azure."""
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
                resolved = await self._async_resolve_host(host)
                api = FourHeatLiteApi(resolved)
                can_connect = await self.hass.async_add_executor_job(
                    api.test_connection
                )
                if not can_connect:
                    errors[CONF_HOST] = "cannot_connect"
                else:
                    host = resolved

            device_key = ""
            if not errors:
                device_key = await self._async_fetch_device_key(device_id)
                if not device_key:
                    errors["base"] = "device_key_failed"

            if not errors:
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured()
                proxy_mode = user_input.get(
                    CONF_PROXY_MODE, PROXY_MODE_DIRECT
                )
                module_address = user_input.get(
                    CONF_MODULE_ADDRESS, ""
                ).strip() or host
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_DEVICE_ID: device_id,
                        CONF_NAME: user_input[CONF_NAME],
                        CONF_HOST: host,
                        CONF_DEVICE_KEY: device_key,
                    },
                    options={
                        CONF_PROXY_MODE: proxy_mode,
                        CONF_MODULE_ADDRESS: module_address,
                    },
                )

        default_id = self._discovered_device_id or ""
        default_host = self._discovered_host or ""

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID, default=default_id): str,
                    vol.Required(CONF_NAME, default="Pellet Stove"): str,
                    vol.Required(CONF_HOST, default=default_host): str,
                    vol.Optional(
                        CONF_PROXY_MODE, default=PROXY_MODE_DIRECT
                    ): vol.In({
                        PROXY_MODE_DIRECT: "Direct — no interception, all module traffic goes to Azure. HA reads sensors via TCP",
                        PROXY_MODE_KEEPALIVE: "Cloud Keepalive — module traffic handled locally, only register and store keepalives are mirrored to Azure so the mobile app sees the device online. Requires DNS/DNAT",
                        PROXY_MODE_LOCAL: "Local Only — all module traffic handled locally, nothing sent to Azure. Mobile app will show the device as offline. Requires DNS/DNAT",
                    }),
                    vol.Optional(
                        CONF_MODULE_ADDRESS, default=default_host
                    ): str,
                }
            ),
            errors=errors,
        )

    async def _async_resolve_host(self, host: str) -> str:
        """Resolve a hostname to its IPv4 address. Returns the original host on failure."""
        try:
            result = await self.hass.async_add_executor_job(
                socket.getaddrinfo, host, None, socket.AF_INET, socket.SOCK_STREAM
            )
            if result:
                return result[0][4][0]
        except OSError:
            pass
        return host

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


class FourHeatLiteOptionsFlow(config_entries.OptionsFlow):
    """Handle options for 4HEAT Lite."""

    async def async_step_init(self, user_input=None):
        errors = {}

        if user_input is not None:
            proxy_mode = user_input.get(CONF_PROXY_MODE, PROXY_MODE_DIRECT)
            schedules_data = user_input.get("schedules")
            if isinstance(schedules_data, dict):
                schedules_data = {
                    **schedules_data,
                    "protocol": user_input.get("schedule_type", PROTOCOL_H24),
                }

            err = FourHeatLiteApi.validate_schedules_config(schedules_data)
            if err:
                errors["schedules"] = err

            if not errors:
                new_active = FourHeatLiteApi.get_active_schedule(schedules_data)
                old_schedules = getattr(
                    self, "_baseline", self.config_entry.options.get(CONF_SCHEDULES)
                )
                old_active = FourHeatLiteApi.get_active_schedule(old_schedules)
                protocol = schedules_data.get("protocol", PROTOCOL_H24)

                domain_data = self.hass.data.get(DOMAIN, {})
                proxy_state = domain_data.get(PROXY_STATE, {})
                device_id = self.config_entry.data.get(CONF_DEVICE_ID, "")

                cmd = None
                if new_active is not None:
                    if new_active != old_active:
                        new_protocol, index, entry = new_active
                        if new_protocol == PROTOCOL_CCS:
                            cmd = FourHeatLiteApi.build_ccs_command(entry)
                        else:
                            cmd = FourHeatLiteApi.build_schedule_command(
                                entry, index
                            )
                elif old_active is not None:
                    old_protocol, old_index, old_entry = old_active
                    if protocol == PROTOCOL_CCS:
                        cmd = FourHeatLiteApi.build_disable_ccs_command()
                    elif old_protocol == PROTOCOL_H24:
                        cmd = FourHeatLiteApi.build_disable_schedule_command(
                            old_entry, old_index
                        )
                    else:
                        cmd = FourHeatLiteApi.build_disable_schedule_command()

                if cmd is not None:
                    status = await self._deliver_command(cmd, device_id, proxy_state)
                    if status == "rejected":
                        errors["schedules"] = "schedule_rejected"
                    elif status != "ok":
                        errors["schedules"] = "schedule_send_failed"
                    elif new_active is not None:
                        self._update_proxy_schedule(
                            {**new_active[2], "protocol": new_active[0]}
                        )

            if not errors:
                module_address = user_input.get(
                    CONF_MODULE_ADDRESS, ""
                ).strip() or self.config_entry.data.get(CONF_HOST, "")
                return self.async_create_entry(data={
                    CONF_PROXY_MODE: proxy_mode,
                    CONF_MODULE_ADDRESS: module_address,
                    CONF_SCHEDULES: schedules_data,
                })

        current_mode = self.config_entry.options.get(
            CONF_PROXY_MODE, PROXY_MODE_DIRECT
        )
        current_module_addr = self.config_entry.options.get(
            CONF_MODULE_ADDRESS,
            self.config_entry.data.get(CONF_HOST, ""),
        )
        if user_input is not None:
            current_schedules = user_input.get("schedules")
            current_type = user_input.get("schedule_type", PROTOCOL_H24)
        else:
            current_schedules = await self._refresh_schedules_from_stove(errors)
            current_type = PROTOCOL_H24
        if not isinstance(current_schedules, dict):
            current_schedules = FourHeatLiteApi.schedules_from_stove(None)
        if user_input is None:
            current_type = current_schedules.get("protocol", PROTOCOL_H24)
        current_schedules = {
            k: v for k, v in current_schedules.items() if k != "protocol"
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_PROXY_MODE,
                        default=current_mode,
                    ): vol.In({
                        PROXY_MODE_DIRECT: "Direct — no interception, all module traffic goes to Azure. HA reads sensors via TCP",
                        PROXY_MODE_KEEPALIVE: "Cloud Keepalive — module traffic handled locally, only register and store keepalives are mirrored to Azure so the mobile app sees the device online. Requires DNS/DNAT",
                        PROXY_MODE_LOCAL: "Local Only — all module traffic handled locally, nothing sent to Azure. Mobile app will show the device as offline. Requires DNS/DNAT",
                    }),
                    vol.Optional(
                        CONF_MODULE_ADDRESS,
                        default=current_module_addr,
                    ): str,
                    vol.Optional(
                        "schedule_type",
                        default=current_type,
                    ): vol.In({PROTOCOL_H24: "H24", PROTOCOL_CCS: "CCS"}),
                    vol.Optional(
                        "schedules",
                        default=current_schedules,
                    ): ObjectSelector(),
                }
            ),
            errors=errors,
            description_placeholders={
                "proxy_modes_url": "https://github.com/pafernanr/homeassistant-4heatlite/blob/main/docs/PROXY_MODES.md",
                "detected_protocol": self._detected_protocol(),
            },
        )

    async def _refresh_schedules_from_stove(self, errors: dict) -> dict | None:
        """Read the stove (source of truth) and merge it into the stored YAML.

        On failure the cached YAML is returned and a warning is added.
        """
        cached = self.config_entry.options.get(CONF_SCHEDULES)
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = entry_data.get(DATA_COORDINATOR)
        parsed = None
        if coordinator:
            parsed = await self.hass.async_add_executor_job(
                coordinator.api.query_schedule
            )
        if parsed is None:
            errors["base"] = "schedule_read_failed"
            self._baseline = cached
            return cached

        self._update_proxy_schedule(parsed)
        merged = FourHeatLiteApi.merge_stove_schedule(cached, parsed)
        self._baseline = merged
        return merged

    def _detected_protocol(self) -> str:
        """Protocol of the schedule last read from the stove, if known."""
        proxy_state = self.hass.data.get(DOMAIN, {}).get(PROXY_STATE, {})
        for dev in proxy_state.get("devices", {}).values():
            if dev.get("entry_id") == self.config_entry.entry_id:
                protocol = (dev.get("last_schedule") or {}).get("protocol")
                if protocol:
                    return protocol.upper()
        return "unknown"

    async def _deliver_command(self, cmd, device_id, proxy_state) -> str:
        """Send command via TCP and enqueue in proxy.

        Returns "ok", "rejected" (the stove answered ERR, nothing is queued)
        or "failed".
        """
        tcp_ok = False
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id, {})
        coordinator = entry_data.get(DATA_COORDINATOR)
        if coordinator:
            result = await self.hass.async_add_executor_job(
                coordinator.api.send_command, cmd
            )
            if FourHeatLiteApi.is_command_rejected(result):
                return "rejected"
            if result and len(result) >= 3 and str(result[2]) == "OK":
                tcp_ok = True

        queued = False
        if device_id:
            queued = enqueue_command(proxy_state, device_id, cmd)

        return "ok" if tcp_ok or queued else "failed"

    def _update_proxy_schedule(self, schedule_data: dict) -> None:
        """Sync proxy cache."""
        domain_data = self.hass.data.get(DOMAIN, {})
        proxy_state = domain_data.get(PROXY_STATE, {})
        for dev in proxy_state.get("devices", {}).values():
            if dev.get("entry_id") == self.config_entry.entry_id:
                dev["last_schedule"] = schedule_data
                break
