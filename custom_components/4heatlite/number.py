"""Number platform for 4HEAT Lite: fan levels."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import FourHeatLiteCoordinator
from .sensor import FourHeatLiteEntity

_LOGGER = logging.getLogger(__name__)

# data key -> (name, enabled by default); ducted fans exist only on some stoves
FAN_NUMBERS = {
    "heating_fan_power": ("Heating Fan", True),
    "ducted_fan_1": ("Ducted Fan 1 Level", False),
    "ducted_fan_2": ("Ducted Fan 2 Level", False),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    name = entry.data[CONF_NAME]
    async_add_entities(
        FanLevelNumber(coordinator, name, key, label, enabled)
        for key, (label, enabled) in FAN_NUMBERS.items()
    )


class FanLevelNumber(FourHeatLiteEntity, NumberEntity):
    """A fan level register (0e group), range as reported by the stove."""

    _attr_icon = "mdi:fan"
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1

    def __init__(self, coordinator, stove_name, key, label, enabled):
        super().__init__(coordinator, stove_name)
        self._key = key
        self._attr_name = f"{stove_name} {label}"
        self._attr_unique_id = f"{stove_name}_{key}_level"
        if not enabled:
            self._attr_entity_registry_enabled_default = False

    @property
    def native_min_value(self) -> float:
        return self.coordinator.api.fan_ranges.get(self._key, (0, 6))[0]

    @property
    def native_max_value(self) -> float:
        return self.coordinator.api.fan_ranges.get(self._key, (0, 6))[1]

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._key in self.coordinator.api.fan_ranges

    async def async_set_native_value(self, value: float) -> None:
        cmd = self.coordinator.api.build_fan_command(self._key, int(value))
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.send_command, cmd
        )
        if result is None:
            _LOGGER.warning("TCP command failed: set %s %s", self._key, value)
            return
        _LOGGER.debug("Set %s to %s via TCP", self._key, value)
        await self.coordinator.async_request_refresh()
