"""Cloud API proxy for 4HEAT Lite module."""

import asyncio
import logging

import aiohttp

from homeassistant.components.http import HomeAssistantView

from .api import FourHeatLiteApi
from .const import CLOUD_API_HOST, CLOUD_API_PORT, PROXY_MODE_CLOUD

_LOGGER = logging.getLogger(__name__)


class StoveCommandsView(HomeAssistantView):
    """GET /api/devices/commands — module polls for pending write commands."""

    url = "/api/devices/commands"
    name = "api:devices:commands"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        queue = self._state.get("command_queue")
        device_id = self._state.get("device_id", "")
        if not queue:
            return self.json([])

        commands = []
        while not queue.empty():
            try:
                cmd = queue.get_nowait()
                commands.append({"id": device_id, "comando": cmd})
            except asyncio.QueueEmpty:
                break

        proxy_mode = self._state.get("proxy_mode")
        cloud_session = self._state.get("cloud_session")
        if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
            cloud = await self._forward_cloud(cloud_session, request.query_string)
            commands.extend(cloud)

        if commands:
            _LOGGER.debug("Returning %d commands to module", len(commands))

        return self.json(commands)

    @staticmethod
    async def _forward_cloud(session, query_string):
        url = f"http://{CLOUD_API_HOST}:{CLOUD_API_PORT}/api/devices/commands?{query_string}"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        _LOGGER.info("Forwarding %d cloud commands", len(data))
                    return data if isinstance(data, list) else []
        except Exception:
            _LOGGER.debug("Cloud command fetch failed", exc_info=True)
        return []


class StoveStoreView(HomeAssistantView):
    """POST /api/devices/store — module uploads sensor data."""

    url = "/api/devices/store"
    name = "api:devices:store"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        device_id = self._state.get("device_id", "")
        coordinator = self._state.get("coordinator")
        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Invalid JSON in store request")
            return self.json(ok_response)

        values = body.get("Values", [])
        if values and coordinator:
            data = self._parse_values(values)
            if data:
                coordinator.push_data(data)

        proxy_mode = self._state.get("proxy_mode")
        cloud_session = self._state.get("cloud_session")
        if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
            await self._forward_cloud(cloud_session, body)

        return self.json(ok_response)

    @staticmethod
    def _parse_values(values):
        result = {}
        for hexdata in values:
            if not isinstance(hexdata, str) or len(hexdata) < 4:
                continue
            if hexdata.startswith("10") and len(hexdata) >= 38:
                result.update(FourHeatLiteApi._decode_0310(hexdata))
            elif hexdata.startswith("12005a") and len(hexdata) >= 10:
                vals = [
                    int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)
                ]
                if len(vals) >= 5:
                    result["target_temp"] = ((vals[3] << 8) | vals[4]) / 10.0
            elif hexdata.startswith("0e016c") and len(hexdata) >= 14:
                vals = [
                    int(hexdata[i : i + 2], 16) for i in range(0, len(hexdata), 2)
                ]
                if len(vals) >= 7:
                    result["power"] = (vals[5] << 8) | vals[6]
            else:
                _LOGGER.debug(
                    "Unrecognized store value: %.10s... (%d chars)",
                    hexdata,
                    len(hexdata),
                )
        return result

    @staticmethod
    async def _forward_cloud(session, body):
        url = f"http://{CLOUD_API_HOST}:{CLOUD_API_PORT}/api/devices/store"
        try:
            async with session.post(
                url, json=body, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                _LOGGER.debug("Cloud store forward: %d", resp.status)
        except Exception:
            _LOGGER.debug("Cloud store forward failed", exc_info=True)


class StoveCronView(HomeAssistantView):
    """POST /api/devices/cron — module uploads schedule data."""

    url = "/api/devices/cron"
    name = "api:devices:cron"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        device_id = self._state.get("device_id", "")
        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Invalid JSON in cron request")
            return self.json(ok_response)

        _LOGGER.debug("Cron data received from module")

        proxy_mode = self._state.get("proxy_mode")
        cloud_session = self._state.get("cloud_session")
        if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
            await self._forward_cloud(cloud_session, body)

        return self.json(ok_response)

    @staticmethod
    async def _forward_cloud(session, body):
        url = f"http://{CLOUD_API_HOST}:{CLOUD_API_PORT}/api/devices/cron"
        try:
            async with session.post(
                url, json=body, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                _LOGGER.debug("Cloud cron forward: %d", resp.status)
        except Exception:
            _LOGGER.debug("Cloud cron forward failed", exc_info=True)
