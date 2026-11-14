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
from .const import DATA_COORDINATOR, DOMAIN
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
    async_add_entities([StoveClimate(coordinator, name)])


class StoveClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: FourHeatLiteCoordinator, stove_name: str):
        super().__init__(coordinator)
        self._stove_name = stove_name
        self._attr_translation_key = "climate"
        self._attr_unique_id = f"{stove_name}_climate"

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }

    # Step, range and power levels follow what the stove reports: whole °C
    # and power 1-6 on Jollymec, 0.1 °C and power 1-7 on Lasian.
    @property
    def target_temperature_step(self):
        return 1.0 if self.coordinator.api.temp_divisor == 1 else 0.1

    @property
    def min_temp(self):
        api = self.coordinator.api
        return api.temp_range[0] / api.temp_divisor if api.temp_range else 10.0

    @property
    def max_temp(self):
        api = self.coordinator.api
        return api.temp_range[1] / api.temp_divisor if api.temp_range else 40.0

    @property
    def preset_modes(self):
        low, high = self.coordinator.api.power_range or (1, 7)
        return [f"Power {i}" for i in range(low, high + 1)]

    @property
    def native_current_temperature(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("room_temp")

    @property
    def native_target_temperature(self):
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
        power = self.coordinator.data.get("live_power")
        if power is not None:
            return f"Power {power}"
        return None

    async def _send_command(self, cmd: list, desc: str) -> None:
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.send_command, cmd
        )
        if result is None:
            _LOGGER.warning("TCP command failed: %s", desc)
        else:
            _LOGGER.debug("Sent %s command via TCP", desc)
            # target and power replies carry the new register; ON/OFF ones don't
            if not self.coordinator.apply_echo(result):
                await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.HEAT:
            await self._send_command(FourHeatLiteApi.build_on_command(), "ON")
        else:
            await self._send_command(FourHeatLiteApi.build_off_command(), "OFF")

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        cmd = self.coordinator.api.build_temp_command(temp)
        await self._send_command(cmd, f"set temperature {temp:.1f}C")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        try:
            level = int(preset_mode.split()[-1])
        except (ValueError, IndexError):
            return
        await self._send_command(
            self.coordinator.api.build_power_command(level), f"set power {level}"
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
