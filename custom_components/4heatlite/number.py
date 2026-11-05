"""Number platform for 4HEAT Lite: the panel's fan setting."""

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


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    async_add_entities([FanSettingNumber(coordinator, entry.data[CONF_NAME])])


class FanSettingNumber(FourHeatLiteEntity, NumberEntity):
    """The fan setting of the panel, in the configured register.

    Range as the record reports it: -7..+7 on a Ferlux, an offset on the speed
    the board picks.
    """

    _attr_icon = "mdi:fan"
    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Fan"
        self._attr_unique_id = f"{stove_name}_fan_setting"

    @property
    def native_min_value(self) -> float:
        return (self.coordinator.api.fan_setting_range or (-7, 7))[0]

    @property
    def native_max_value(self) -> float:
        return (self.coordinator.api.fan_setting_range or (-7, 7))[1]

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("fan_setting")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.api.fan_setting_range is not None

    async def async_set_native_value(self, value: float) -> None:
        cmd = self.coordinator.api.build_fan_setting_command(int(value))
        if cmd is None:
            _LOGGER.warning("Fan register not read yet: set fan %s", value)
            return
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.send_command, cmd
        )
        if result is None:
            _LOGGER.warning("TCP command failed: set fan %s", value)
            return
        _LOGGER.debug("Set fan to %s via TCP", value)
        if not self.coordinator.apply_echo(result):
            await self.coordinator.async_request_refresh()
