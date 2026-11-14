"""Number platform for 4HEAT Lite: the panel settings (fan, combustion, heating)."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import AUTO_MANUAL_MAX, AUTO_VALUE, DATA_COORDINATOR, DOMAIN
from .coordinator import FourHeatLiteCoordinator
from .sensor import FourHeatLiteEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    async_add_entities(
        [
            FanSettingNumber(coordinator, entry.data[CONF_NAME]),
            CombustionSettingNumber(coordinator, entry.data[CONF_NAME]),
            HeatingSettingNumber(coordinator, entry.data[CONF_NAME]),
        ]
    )


class SettingNumber(FourHeatLiteEntity, NumberEntity):
    """A panel setting the stove reports a range for; written as the whole record."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_step = 1
    _data_key: str
    _range_attr: str
    _command_attr: str
    _default_range: tuple[int, int]
    _label: str
    _unique_suffix: str
    _has_auto = False

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_unique_id = f"{stove_name}_{self._unique_suffix}"

    def _range(self) -> tuple[int, int]:
        return getattr(self.coordinator.api, self._range_attr) or self._default_range

    def _is_auto(self) -> bool:
        return (
            self._has_auto
            and self.coordinator.data is not None
            and self.coordinator.data.get(self._data_key) == AUTO_VALUE
        )

    @property
    def native_min_value(self) -> float:
        return self._range()[0]

    @property
    def native_max_value(self) -> float:
        high = self._range()[1]
        return min(high, AUTO_MANUAL_MAX) if self._has_auto else high

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._data_key)

    @property
    def available(self) -> bool:
        return (
            super().available
            and getattr(self.coordinator.api, self._range_attr) is not None
            and not self._is_auto()
        )

    async def async_set_native_value(self, value: float) -> None:
        cmd = getattr(self.coordinator.api, self._command_attr)(int(value))
        if cmd is None:
            _LOGGER.warning("%s register not read yet: set %s", self._label, value)
            return
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.send_command, cmd
        )
        if result is None:
            _LOGGER.warning("TCP command failed: set %s %s", self._label, value)
            return
        _LOGGER.debug("Set %s to %s via TCP", self._label, value)
        if not self.coordinator.apply_echo(result):
            await self.coordinator.async_request_refresh()


class FanSettingNumber(SettingNumber):
    """The room fan setting (0e/038c), -7..+7 on a Ferlux."""

    _attr_icon = "mdi:fan"
    _data_key = "fan_setting"
    _range_attr = "fan_setting_range"
    _command_attr = "build_fan_setting_command"
    _default_range = (-7, 7)
    _attr_translation_key = "fan_setting"
    _label = "Room Fan"
    _unique_suffix = "fan_setting"


class CombustionSettingNumber(SettingNumber):
    """The combustion setting (0e/016c): 1-6 manual, 7 = Auto."""

    _attr_icon = "mdi:fire"
    _data_key = "power"
    _range_attr = "power_range"
    _command_attr = "build_power_command"
    _default_range = (1, 7)
    _attr_translation_key = "combustion_setting"
    _label = "Combustion Level"
    _unique_suffix = "combustion_setting"
    _has_auto = True


class HeatingSettingNumber(SettingNumber):
    """The heating setting (0e/023f): OFF (0), 1-6 manual, 7 = Auto."""

    _attr_icon = "mdi:radiator"
    _data_key = "heating_setting"
    _range_attr = "heating_setting_range"
    _command_attr = "build_heating_setting_command"
    _default_range = (0, 7)
    _attr_translation_key = "heating_setting"
    _label = "Heating Level"
    _unique_suffix = "heating_setting"
    _has_auto = True
