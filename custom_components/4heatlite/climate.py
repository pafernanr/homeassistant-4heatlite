"""Climate platform for 4HEAT Lite."""

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import FourHeatLiteApi
from .const import COMMAND_QUEUE, DATA_COORDINATOR, DOMAIN
from .coordinator import FourHeatLiteCoordinator

_LOGGER = logging.getLogger(__name__)

HEATING_STATES = {5, 6, 13}
PREHEATING_STATES = {1, 2, 3, 4, 10, 30, 31, 32, 33, 34}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    name = entry.data[CONF_NAME]
    queue = hass.data[DOMAIN][entry.entry_id].get(COMMAND_QUEUE)
    async_add_entities([StoveClimate(coordinator, name, queue)])


class StoveClimate(CoordinatorEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 10.0
    _attr_max_temp = 40.0
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [f"Power {i}" for i in range(1, 8)]

    def __init__(self, coordinator: FourHeatLiteCoordinator, stove_name: str, queue):
        super().__init__(coordinator)
        self._stove_name = stove_name
        self._queue = queue
        self._attr_name = f"{stove_name} Climate"
        self._attr_unique_id = f"{stove_name}_climate"
        if queue:
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.PRESET_MODE
                | ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
            )
        else:
            self._attr_supported_features = ClimateEntityFeature(0)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }

    @property
    def current_temperature(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("room_temp")

    @property
    def target_temperature(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("target_temp")

    @property
    def hvac_mode(self):
        if self.coordinator.data is None:
            return None
        return (
            HVACMode.HEAT
            if self.coordinator.data.get("state", 0) != 0
            else HVACMode.OFF
        )

    @property
    def hvac_action(self):
        if self.coordinator.data is None:
            return None
        state = self.coordinator.data.get("state", 0)
        if state == 0:
            return HVACAction.OFF
        if state in PREHEATING_STATES:
            return HVACAction.PREHEATING
        if state in HEATING_STATES:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self):
        if self.coordinator.data is None:
            return None
        power = self.coordinator.data.get("power")
        if power is not None:
            return f"Power {power}"
        return None

    async def _send_command(self, cmd: list, desc: str) -> None:
        if not self._queue:
            _LOGGER.info(
                "%s ignored: cloud API proxy not enabled. "
                "Enable proxy in integration config and set up DNS redirect.",
                desc,
            )
            return
        await self._queue.put(cmd)
        _LOGGER.debug("Queued %s command", desc)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self._send_command(FourHeatLiteApi.build_on_command(), "ON")
        else:
            await self._send_command(FourHeatLiteApi.build_off_command(), "OFF")

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        cmd = FourHeatLiteApi.build_temp_command(temp)
        await self._send_command(cmd, f"set temperature {temp:.1f}C")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        try:
            level = int(preset_mode.split()[-1])
        except (ValueError, IndexError):
            return
        await self._send_command(
            FourHeatLiteApi.build_power_command(level), f"set power {level}"
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
