"""The 4HEAT Lite integration."""

import asyncio
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant

from .const import (
    COMMAND_QUEUE,
    CONF_DEVICE_ID,
    CONF_PROXY_ENABLED,
    CONF_PROXY_MODE,
    DATA_COORDINATOR,
    DEFAULT_DEVICE_ID,
    DOMAIN,
    PROXY_MODE_CLOUD,
    PROXY_MODE_LOCAL,
    PROXY_SESSION,
)
from .coordinator import FourHeatLiteCoordinator
from .proxy import StoveCommandsView, StoveCronView, StoveStoreView

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CLIMATE]
PROXY_STATE = "proxy_state"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up 4HEAT Lite from a config entry."""
    coordinator = FourHeatLiteCoordinator(hass, entry.data[CONF_HOST])

    proxy_enabled = entry.data.get(CONF_PROXY_ENABLED, False)

    hass.data.setdefault(DOMAIN, {})
    entry_data = {DATA_COORDINATOR: coordinator}

    if proxy_enabled:
        device_id = entry.data.get(CONF_DEVICE_ID, DEFAULT_DEVICE_ID)
        proxy_mode = entry.options.get(CONF_PROXY_MODE, PROXY_MODE_LOCAL)

        command_queue = asyncio.Queue()
        entry_data[COMMAND_QUEUE] = command_queue

        cloud_session = None
        if proxy_mode == PROXY_MODE_CLOUD:
            cloud_session = aiohttp.ClientSession()
            entry_data[PROXY_SESSION] = cloud_session

        coordinator.set_proxy_mode(True)

        # Shared mutable state for proxy views (survives entry reloads)
        proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
        if proxy_state is None:
            proxy_state = {}
            hass.data[DOMAIN][PROXY_STATE] = proxy_state
            hass.http.register_view(StoveCommandsView(proxy_state))
            hass.http.register_view(StoveStoreView(proxy_state))
            hass.http.register_view(StoveCronView(proxy_state))

        proxy_state.update(
            {
                "command_queue": command_queue,
                "coordinator": coordinator,
                "device_id": device_id,
                "proxy_mode": proxy_mode,
                "cloud_session": cloud_session,
            }
        )

    hass.data[DOMAIN][entry.entry_id] = entry_data

    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data[DOMAIN].get(entry.entry_id, {})

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        session = entry_data.get(PROXY_SESSION)
        if session:
            await session.close()

        proxy_state = hass.data[DOMAIN].get(PROXY_STATE)
        if proxy_state:
            proxy_state.clear()

        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
