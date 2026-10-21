"""The 4HEAT Lite integration."""

import asyncio
import logging

import aiohttp

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import FourHeatLiteApi
from .const import (
    COMMAND_QUEUE,
    CONF_DEVICE_ID,
    CONF_DEVICE_KEY,
    CONF_PROXY_MODE,
    DATA_COORDINATOR,
    DOMAIN,
    PROXY_MODE_CLOUD,
    PROXY_SESSION,
    SERVICE_GET_SCHEDULE,
    SERVICE_SET_SCHEDULE,
)
from .coordinator import FourHeatLiteCoordinator
from .proxy import (
    ProxyDiagView,
    StoveCommandsView,
    StoveCronView,
    StoveRegisterView,
    StoveStoreView,
    StoveTimeAlignView,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CLIMATE]
DATA_PLATFORMS = "platforms"
PROXY_STATE = "proxy_state"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up 4HEAT Lite from a config entry."""
    coordinator = FourHeatLiteCoordinator(hass, entry.data[CONF_HOST])

    proxy_mode = entry.options.get(CONF_PROXY_MODE, "local_only")
    device_id = entry.data.get(CONF_DEVICE_ID, "")
    host = entry.data[CONF_HOST]

    hass.data.setdefault(DOMAIN, {})

    command_queue = asyncio.Queue()
    cloud_session = None
    if proxy_mode == PROXY_MODE_CLOUD:
        cloud_session = aiohttp.ClientSession()

    coordinator.set_proxy_mode(True)

    proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
    if proxy_state is None:
        proxy_state = {"devices": {}, "hosts": {}, "pending": {}, "hass": hass}
        hass.data[DOMAIN][PROXY_STATE] = proxy_state

    device_entry = {
        "queue": command_queue,
        "coordinator": coordinator,
        "proxy_mode": proxy_mode,
        "cloud_session": cloud_session,
        "host": host,
        "entry_id": entry.entry_id,
        "device_key": entry.data.get(CONF_DEVICE_KEY),
    }

    if device_id:
        proxy_state["devices"][device_id] = device_entry
        proxy_state["hosts"][host] = device_id
    else:
        proxy_state["pending"][entry.entry_id] = device_entry

    if not proxy_state.get("_views_registered"):
        hass.http.register_view(StoveRegisterView(proxy_state))
        hass.http.register_view(StoveCommandsView(proxy_state))
        hass.http.register_view(StoveStoreView(proxy_state))
        hass.http.register_view(StoveCronView(proxy_state))
        hass.http.register_view(StoveTimeAlignView(proxy_state))
        hass.http.register_view(ProxyDiagView(proxy_state))
        proxy_state["_views_registered"] = True

    if not hass.data[DOMAIN].get("_services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["_services_registered"] = True

    entry_data = {
        DATA_COORDINATOR: coordinator,
        COMMAND_QUEUE: command_queue,
    }
    if cloud_session:
        entry_data[PROXY_SESSION] = cloud_session

    entry_data[DATA_PLATFORMS] = list(PLATFORMS)

    hass.data[DOMAIN][entry.entry_id] = entry_data

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _resolve_entry(hass: HomeAssistant, config_entry_id: str | None = None):
    """Find entry data and device entry for a service call."""
    domain_data = hass.data.get(DOMAIN, {})
    proxy_state = domain_data.get(PROXY_STATE, {})

    if config_entry_id:
        entry_data = domain_data.get(config_entry_id)
        if not entry_data:
            raise HomeAssistantError(f"Config entry {config_entry_id} not found")
    else:
        entries = {
            k: v for k, v in domain_data.items()
            if k not in (PROXY_STATE, "_services_registered") and isinstance(v, dict)
        }
        if len(entries) == 1:
            config_entry_id, entry_data = next(iter(entries.items()))
        elif not entries:
            raise HomeAssistantError("No 4HEAT Lite stoves configured")
        else:
            raise HomeAssistantError(
                "Multiple stoves configured — specify config_entry_id"
            )

    device_entry = None
    for dev in proxy_state.get("devices", {}).values():
        if dev.get("entry_id") == config_entry_id:
            device_entry = dev
            break

    return entry_data, device_entry


def _register_services(hass: HomeAssistant) -> None:
    """Register get_schedule and set_schedule services."""

    async def async_get_schedule(call: ServiceCall):
        entry_data, device_entry = _resolve_entry(
            hass, call.data.get("config_entry_id")
        )

        schedule = None
        if device_entry:
            schedule = device_entry.get("last_schedule")

        if schedule is None:
            coordinator = entry_data.get(DATA_COORDINATOR)
            if coordinator:
                schedule = await hass.async_add_executor_job(
                    coordinator.api.query_schedule
                )

        if schedule is None:
            raise HomeAssistantError("Failed to read schedule from module")

        return schedule

    async def async_set_schedule(call: ServiceCall):
        entry_data, _ = _resolve_entry(
            hass, call.data.get("config_entry_id")
        )

        schedule = call.data["schedule"]
        error = FourHeatLiteApi.validate_schedule(schedule)
        if error:
            raise HomeAssistantError(f"Invalid schedule: {error}")

        cmd = FourHeatLiteApi.build_schedule_command(schedule)
        queue = entry_data.get(COMMAND_QUEUE)
        if not queue:
            raise HomeAssistantError("Command queue not available")
        await queue.put(cmd)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SCHEDULE,
        async_get_schedule,
        schema=vol.Schema({
            vol.Optional("config_entry_id"): cv.string,
        }),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SCHEDULE,
        async_set_schedule,
        schema=vol.Schema({
            vol.Optional("config_entry_id"): cv.string,
            vol.Required("schedule"): dict,
        }),
    )


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

    platforms = entry_data.get(DATA_PLATFORMS, PLATFORMS)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)

    if unload_ok:
        session = entry_data.get(PROXY_SESSION)
        if session:
            await session.close()

        proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
        if proxy_state:
            proxy_state["pending"].pop(entry.entry_id, None)

            remove_ids = [
                did
                for did, d in proxy_state["devices"].items()
                if d.get("entry_id") == entry.entry_id
            ]
            for did in remove_ids:
                proxy_state["devices"].pop(did, None)

            remove_hosts = [
                h for h, did in proxy_state["hosts"].items() if did in remove_ids
            ]
            for h in remove_hosts:
                proxy_state["hosts"].pop(h, None)

        hass.data[DOMAIN].pop(entry.entry_id, None)

        remaining = [
            k for k in hass.data[DOMAIN]
            if k not in (PROXY_STATE, "_services_registered")
        ]
        if not remaining and hass.data[DOMAIN].get("_services_registered"):
            hass.services.async_remove(DOMAIN, SERVICE_GET_SCHEDULE)
            hass.services.async_remove(DOMAIN, SERVICE_SET_SCHEDULE)
            hass.data[DOMAIN].pop("_services_registered", None)

    return unload_ok
