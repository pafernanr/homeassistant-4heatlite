"""Cloud API proxy for 4HEAT Lite module.

Supports multiple stoves — each module is identified by its device_id
in the commands poll, and by source IP for store/cron requests.
"""

import asyncio
import logging
import uuid

import aiohttp

from homeassistant.components.http import HomeAssistantView

from .api import FourHeatLiteApi
from .const import (
    CLOUD_API_HOST,
    CLOUD_API_IP,
    CLOUD_API_PORT,
    CONF_DEVICE_KEY,
    DOMAIN,
    PROXY_MODE_CLOUD,
)

_LOGGER = logging.getLogger(__name__)


def _lookup_device(state, device_id=None, remote_ip=None):
    """Find device entry by device_id or remote IP."""
    devices = state.get("devices", {})
    if device_id and device_id in devices:
        return devices[device_id], device_id

    if remote_ip:
        hosts = state.get("hosts", {})
        did = hosts.get(remote_ip)
        if did and did in devices:
            return devices[did], did

    if len(devices) == 1:
        did, entry = next(iter(devices.items()))
        return entry, did

    return None, None


def _promote_pending(state, device_id, remote_ip):
    """Move a pending entry to devices when device_id is auto-detected."""
    pending = state.get("pending", {})
    devices = state.setdefault("devices", {})
    hosts = state.setdefault("hosts", {})

    matched_eid = None
    for eid, pentry in pending.items():
        if pentry.get("host") == remote_ip:
            matched_eid = eid
            break

    if not matched_eid and len(pending) == 1:
        matched_eid = next(iter(pending))

    if matched_eid:
        entry = pending.pop(matched_eid)
        entry["entry_id"] = matched_eid
        devices[device_id] = entry
        hosts[remote_ip] = device_id
        _LOGGER.info(
            "Auto-detected device ID %s from %s (entry %s)",
            device_id,
            remote_ip,
            matched_eid,
        )
        return entry

    return None


class StoveRegisterView(HomeAssistantView):
    """POST /api/devices/register — module registers on boot before polling."""

    url = "/api/devices/register"
    name = "api:devices:register"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote
        try:
            body = await request.json()
        except Exception:
            return self.json({"Key": str(uuid.uuid4())})

        device_id = body.get("Id", "")
        _LOGGER.info(
            "Module registered: id=%s ip=%s fw=%s.%s product=%s",
            device_id,
            body.get("IpAddress", remote_ip),
            body.get("FirmwareVersion", "?"),
            body.get("FirmwareRevision", "?"),
            body.get("ProductCode", "?"),
        )

        if device_id and remote_ip:
            entry, _ = _lookup_device(self._state, device_id=device_id)
            if not entry:
                _promote_pending(self._state, device_id, remote_ip)
            self._state.setdefault("hosts", {})[remote_ip] = device_id

        entry, _ = _lookup_device(self._state, device_id=device_id)

        cloud_key = None
        if entry:
            cloud_session = entry.get("cloud_session")
            proxy_mode = entry.get("proxy_mode")
            if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
                cloud_key = await self._forward_cloud(cloud_session, body)

        stored_key = entry.get("device_key") if entry else None
        key = stored_key or cloud_key or str(
            uuid.uuid5(uuid.NAMESPACE_DNS, device_id or "4heat")
        )

        if entry and not stored_key:
            entry["device_key"] = key
            self._persist_device_key(entry.get("entry_id"), key)

        return self.json({"Key": key})

    def _persist_device_key(self, entry_id, key):
        hass = self._state.get("hass")
        if not hass or not entry_id:
            return
        config_entry = hass.config_entries.async_get_entry(entry_id)
        if config_entry and config_entry.data.get(CONF_DEVICE_KEY) != key:
            hass.config_entries.async_update_entry(
                config_entry, data={**config_entry.data, CONF_DEVICE_KEY: key}
            )

    @staticmethod
    async def _forward_cloud(session, body):
        url = f"http://{CLOUD_API_IP}:{CLOUD_API_PORT}/api/devices/register"
        headers = {"Host": CLOUD_API_HOST}
        try:
            async with session.post(
                url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("Key")
        except Exception:
            _LOGGER.warning("Cloud register forward failed", exc_info=True)
        return None


class StoveCommandsView(HomeAssistantView):
    """GET /api/devices/commands — module polls for pending write commands."""

    url = "/api/devices/commands"
    name = "api:devices:commands"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        req_id = request.query.get("id", "")
        remote_ip = request.remote

        entry, device_id = _lookup_device(
            self._state, device_id=req_id, remote_ip=remote_ip
        )

        if not entry and req_id and remote_ip:
            entry = _promote_pending(self._state, req_id, remote_ip)
            device_id = req_id

        if not entry:
            if req_id:
                _LOGGER.debug("Unknown device %s from %s", req_id, remote_ip)
            return self.json([])

        if remote_ip:
            self._state.setdefault("hosts", {})[remote_ip] = device_id

        queue = entry.get("queue")
        if not queue:
            return self.json([])

        commands = []
        while not queue.empty():
            try:
                cmd = queue.get_nowait()
                commands.append({"id": device_id, "comando": cmd})
            except asyncio.QueueEmpty:
                break

        proxy_mode = entry.get("proxy_mode")
        cloud_session = entry.get("cloud_session")
        if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
            cloud = await self._forward_cloud(cloud_session, request.query_string)
            commands.extend(cloud)

        if commands:
            _LOGGER.info(
                "Delivering %d command(s) to device %s from %s: %s",
                len(commands),
                device_id,
                remote_ip,
                commands,
            )

        return self.json(commands)

    @staticmethod
    async def _forward_cloud(session, query_string):
        url = f"http://{CLOUD_API_IP}:{CLOUD_API_PORT}/api/devices/commands?{query_string}"
        headers = {"Host": CLOUD_API_HOST}
        try:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        _LOGGER.info("Forwarding %d cloud commands", len(data))
                    return data if isinstance(data, list) else []
        except Exception:
            _LOGGER.warning("Cloud command fetch failed", exc_info=True)
        return []


class StoveStoreView(HomeAssistantView):
    """POST /api/devices/store — module uploads sensor data."""

    url = "/api/devices/store"
    name = "api:devices:store"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote
        entry, device_id = _lookup_device(self._state, remote_ip=remote_ip)
        device_id = device_id or ""

        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Invalid JSON in store request")
            return self.json(ok_response)

        values = body.get("Values", [])
        if values and entry:
            coordinator = entry.get("coordinator")
            if coordinator:
                data = self._parse_values(values)
                if data:
                    _LOGGER.info(
                        "Store data from %s (device %s): %s",
                        remote_ip,
                        device_id,
                        {k: v for k, v in data.items() if k != "raw"},
                    )
                    coordinator.push_data(data)

        if entry:
            proxy_mode = entry.get("proxy_mode")
            cloud_session = entry.get("cloud_session")
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
        url = f"http://{CLOUD_API_IP}:{CLOUD_API_PORT}/api/devices/store"
        headers = {"Host": CLOUD_API_HOST}
        try:
            async with session.post(
                url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                _LOGGER.debug("Cloud store forward: %d", resp.status)
        except Exception:
            _LOGGER.warning("Cloud store forward failed", exc_info=True)


class StoveCronView(HomeAssistantView):
    """POST /api/devices/cron — module uploads schedule data."""

    url = "/api/devices/cron"
    name = "api:devices:cron"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def post(self, request):
        remote_ip = request.remote
        entry, device_id = _lookup_device(self._state, remote_ip=remote_ip)
        device_id = device_id or ""

        ok_response = {"DeviceId": device_id, "Assistant": ""}

        try:
            body = await request.json()
        except Exception:
            _LOGGER.warning("Invalid JSON in cron request")
            return self.json(ok_response)

        _LOGGER.debug("Cron data received from device %s", device_id)

        if entry:
            proxy_mode = entry.get("proxy_mode")
            cloud_session = entry.get("cloud_session")
            if proxy_mode == PROXY_MODE_CLOUD and cloud_session:
                await self._forward_cloud(cloud_session, body)

        return self.json(ok_response)

    @staticmethod
    async def _forward_cloud(session, body):
        url = f"http://{CLOUD_API_IP}:{CLOUD_API_PORT}/api/devices/cron"
        headers = {"Host": CLOUD_API_HOST}
        try:
            async with session.post(
                url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                _LOGGER.debug("Cloud cron forward: %d", resp.status)
        except Exception:
            _LOGGER.warning("Cloud cron forward failed", exc_info=True)


class ProxyDiagView(HomeAssistantView):
    """GET /api/devices/diag — test cloud connectivity (remove after debugging)."""

    url = "/api/devices/diag"
    name = "api:devices:diag"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        result = {"devices": {}, "hosts": dict(self._state.get("hosts", {}))}

        for did, entry in self._state.get("devices", {}).items():
            result["devices"][did] = {
                "proxy_mode": entry.get("proxy_mode"),
                "has_cloud_session": entry.get("cloud_session") is not None,
                "has_queue": entry.get("queue") is not None,
                "device_key": (entry.get("device_key") or "")[:8] + "...",
            }

        cloud_session = None
        for entry in self._state.get("devices", {}).values():
            cloud_session = entry.get("cloud_session")
            if cloud_session:
                break

        if not cloud_session:
            result["cloud_test"] = "no cloud session"
            return self.json(result)

        url = f"http://{CLOUD_API_IP}:{CLOUD_API_PORT}/api/devices/summary?ids%5B0%5D=<DEVICE_ID>"
        headers = {"Host": CLOUD_API_HOST}
        try:
            async with cloud_session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result["cloud_test"] = {
                    "status": resp.status,
                    "url": url,
                }
                if resp.status == 200:
                    data = await resp.json()
                    if data:
                        result["cloud_test"]["is_online"] = data[0].get("IsOnline")
        except Exception as exc:
            result["cloud_test"] = {"error": str(exc), "type": type(exc).__name__}

        return self.json(result)
