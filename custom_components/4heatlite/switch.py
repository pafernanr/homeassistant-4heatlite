"""Switch platform for 4HEAT Lite: Auto on/off for combustion and heating."""

import logging

from homeassistant.components.switch import SwitchEntity
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
    stove_name = entry.data[CONF_NAME]
    async_add_entities(
        [
            AutoSwitch(
                coordinator, stove_name, "Combustion", "power",
                "build_power_command", "combustion_auto",
            ),
            AutoSwitch(
                coordinator, stove_name, "Heating", "heating_setting",
                "build_heating_setting_command", "heating_auto",
            ),
        ]
    )


class AutoSwitch(FourHeatLiteEntity, SwitchEntity):
    """On sets the setting to Auto (7). Off restores the last manual value."""

    _attr_icon = "mdi:refresh-auto"

    def __init__(
        self, coordinator, stove_name, label, data_key, command_attr, unique_suffix
    ):
        super().__init__(coordinator, stove_name)
        self._data_key = data_key
        self._command_attr = command_attr
        self._attr_name = f"{stove_name} {label} Auto"
        self._attr_unique_id = f"{stove_name}_{unique_suffix}"
        self._last_manual = AUTO_MANUAL_MAX

    def _handle_coordinator_update(self) -> None:
        value = self.coordinator.data.get(self._data_key) if self.coordinator.data else None
        if value is not None and value != AUTO_VALUE:
            self._last_manual = value
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._data_key)
        if value is None:
            return None
        return value == AUTO_VALUE

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.get(self._data_key) is not None
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._send(AUTO_VALUE)

    async def async_turn_off(self, **kwargs) -> None:
        await self._send(self._last_manual)

    async def _send(self, value: int) -> None:
        cmd = getattr(self.coordinator.api, self._command_attr)(value)
        if cmd is None:
            _LOGGER.warning("%s not read yet: set %s", self._attr_name, value)
            return
        result = await self.hass.async_add_executor_job(
            self.coordinator.api.send_command, cmd
        )
        if result is None:
            _LOGGER.warning("TCP command failed: %s %s", self._attr_name, value)
            return
        if not self.coordinator.apply_echo(result):
            await self.coordinator.async_request_refresh()
