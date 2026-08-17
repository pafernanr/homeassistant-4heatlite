"""Sensor platform for 4HEAT Lite."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN, ERROR_NAMES, STATE_NAMES
from .coordinator import FourHeatLiteCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: FourHeatLiteCoordinator = hass.data[DOMAIN][entry.entry_id][
        DATA_COORDINATOR
    ]
    name = entry.data[CONF_NAME]

    entities = [
        StoveStateSensor(coordinator, name),
        StoveErrorSensor(coordinator, name),
        ExhaustTemperatureSensor(coordinator, name),
        RoomTemperatureSensor(coordinator, name),
        TargetTemperatureSensor(coordinator, name),
        PowerLevelSensor(coordinator, name),
    ]

    # Diagnostic sensors for unknown bytes (disabled by default)
    unknown_bytes = {
        2: "On Off Flag",
        3: "Byte 3",
        6: "Byte 6",
        7: "Byte 7",
        8: "Byte 8",
        9: "Byte 9",
        12: "Byte 12",
        13: "Byte 13",
        16: "Byte 16",
        17: "Byte 17",
        18: "Byte 18",
    }
    for idx, label in unknown_bytes.items():
        entities.append(RawByteSensor(coordinator, name, idx, label))

    async_add_entities(entities)


class FourHeatLiteEntity(CoordinatorEntity):
    """Base entity for 4HEAT Lite."""

    def __init__(self, coordinator: FourHeatLiteCoordinator, stove_name: str) -> None:
        super().__init__(coordinator)
        self._stove_name = stove_name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._stove_name)},
            "name": self._stove_name,
            "manufacturer": "4HEAT",
            "model": "Lite",
        }


class StoveStateSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:fire"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} State"
        self._attr_unique_id = f"{stove_name}_state"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        state = self.coordinator.data["state"]
        return STATE_NAMES.get(state, f"Unknown ({state})")

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return None
        return {"state_code": self.coordinator.data["state"]}


class StoveErrorSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Error"
        self._attr_unique_id = f"{stove_name}_error"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        error = self.coordinator.data["error"]
        return ERROR_NAMES.get(error, f"Unknown ({error})")

    @property
    def extra_state_attributes(self):
        if self.coordinator.data is None:
            return None
        return {"error_code": self.coordinator.data["error"]}


class ExhaustTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Exhaust Temperature"
        self._attr_unique_id = f"{stove_name}_exhaust_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["exhaust_temp"]


class RoomTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Room Temperature"
        self._attr_unique_id = f"{stove_name}_room_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data["room_temp"]


class TargetTemperatureSensor(FourHeatLiteEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:thermometer-check"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Target Temperature"
        self._attr_unique_id = f"{stove_name}_target_temp"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("target_temp")


class PowerLevelSensor(FourHeatLiteEntity, SensorEntity):
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator, stove_name):
        super().__init__(coordinator, stove_name)
        self._attr_name = f"{stove_name} Power Level"
        self._attr_unique_id = f"{stove_name}_power_level"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("power")


class RawByteSensor(FourHeatLiteEntity, SensorEntity):
    """Diagnostic sensor for unmapped bytes."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, stove_name, byte_index, label):
        super().__init__(coordinator, stove_name)
        self._byte_index = byte_index
        self._attr_name = f"{stove_name} {label}"
        self._attr_unique_id = f"{stove_name}_raw_byte_{byte_index}"

    @property
    def native_value(self):
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get("raw")
        if raw and self._byte_index < len(raw):
            return raw[self._byte_index]
        return None
