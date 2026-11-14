"""DataUpdateCoordinator for 4HEAT Lite."""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import FourHeatLiteApi
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, MAX_STALE_POLLS, PROXY_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)


class FourHeatLiteCoordinator(DataUpdateCoordinator):
    """Fetch sensor data from the 4HEAT Lite module."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self.api = FourHeatLiteApi(host)
        self._failed_polls = 0
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def set_proxy_mode(self, enabled: bool) -> None:
        """Switch to longer poll interval when proxy provides real-time data."""
        if enabled:
            self.update_interval = timedelta(seconds=PROXY_POLL_INTERVAL)

    def push_data(self, data: dict) -> None:
        """Inject sensor data from proxy store endpoint."""
        if self.data:
            merged = dict(self.data)
            merged.update(data)
        else:
            merged = data
        self.async_set_updated_data(merged)

    def apply_echo(self, response: list | None) -> bool:
        """Publish the value a write command's reply carries, right away.

        The module answers a write with the updated register; without this
        the entity showed the old value until the debounced refresh, and a
        second change made meanwhile looked like it bounced back.
        """
        if not response or not isinstance(response, list) or len(response) < 3:
            return False
        # a reply carrying the whole cache holds the old value of the register
        # just written: only a single-record reply is the echo of the write
        if len(response) != 3:
            return False
        data = self.api.decode_echo(response[2:])
        if not data:
            return False
        self.push_data(data)
        return True

    async def _async_update_data(self) -> dict:
        # Config first: the target register gives the temperature unit that
        # decoding the sensor block needs.
        config = await self.hass.async_add_executor_job(self.api.query_config)
        data = await self.hass.async_add_executor_job(self.api.query_sensors)
        if data is None:
            self._failed_polls += 1
            if self.data and self._failed_polls <= MAX_STALE_POLLS:
                _LOGGER.debug(
                    "Poll failed (%d in a row), keeping last data", self._failed_polls
                )
                return self.data
            raise UpdateFailed("Failed to query 4HEAT Lite module")
        self._failed_polls = 0
        if config:
            data.update(config)
        fans = await self.hass.async_add_executor_job(self.api.query_fans)
        data.update(fans)
        fan_setting = await self.hass.async_add_executor_job(self.api.query_fan_setting)
        data.update(fan_setting)
        heating = await self.hass.async_add_executor_job(self.api.query_heating_setting)
        data.update(heating)
        live = await self.hass.async_add_executor_job(self.api.query_live_power)
        data.update(live)
        return data
