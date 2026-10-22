"""Cloud API proxy for 4HEAT Lite module.

Responds to module cloud endpoints locally. Required for local_only mode
(DNS/firewall intercepts module traffic). In direct mode, these endpoints
exist but receive no traffic since the module talks to Azure directly.
"""

import json
import logging
import time
from datetime import datetime, timezone

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .api import FourHeatLiteApi

_LOGGER = logging.getLogger(__name__)


def enqueue_command(state, device_id: str, command: list) -> bool:
    """Add a command to the device's polling queue."""
    entry, did = _lookup_device(state, device_id=device_id)
    if not entry:
        _LOGGER.warning("Cannot enqueue command: device %s not found", device_id)
        return False
    queue = entry.setdefault("command_queue", [])
    queue.append(command)
    _LOGGER.info("Enqueued command for device %s: %.60s...", did, str(command))
    return True


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
            return self.json({"Key": ""})

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

        return self.json({"Key": ""})


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

        queue = entry.get("command_queue", [])
        if queue:
            commands = [
                {"id": device_id, "comando": cmd} for cmd in queue
            ]
            remove = request.query.get("removefromserver", "").lower()
            if remove == "true":
                entry["command_queue"] = []
            _LOGGER.info(
                "Delivering %d queued command(s) to device %s (remove=%s)",
                len(commands),
                device_id,
                remove,
            )
            return web.Response(
                body=json.dumps(commands, separators=(",", ":")),
                content_type="application/json",
            )

        return self.json([])


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

        command = body.get("Command") if isinstance(body, dict) else body
        if isinstance(command, list) and command and str(command[0]) == "H24":
            parsed = FourHeatLiteApi.parse_h24_response(command)
            if parsed and entry:
                entry["last_schedule"] = parsed
                _LOGGER.debug("Schedule stored for device %s", device_id)

        return self.json(ok_response)


class StoveTimeAlignView(HomeAssistantView):
    """GET /api/Devices/timeAlign — module syncs its clock."""

    url = "/api/Devices/timeAlign"
    name = "api:devices:timealign"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        now = datetime.now(timezone.utc)
        gmt_offset = int(now.astimezone().utcoffset().total_seconds())
        return self.json({
            "gmtOffset": gmt_offset,
            "timestamp": int(time.time()) + gmt_offset,
        })


class ProxyDiagView(HomeAssistantView):
    """GET /api/devices/diag — diagnostic endpoint."""

    url = "/api/devices/diag"
    name = "api:devices:diag"
    requires_auth = False

    def __init__(self, state):
        self._state = state

    async def get(self, request):
        try:
            devices = self._state.get("devices", {})
            hosts = self._state.get("hosts", {})
            pending = self._state.get("pending", {})

            result = {
                "device_count": len(devices),
                "host_count": len(hosts),
                "pending_count": len(pending),
                "device_ids": list(devices.keys()),
                "host_map": {k: v for k, v in hosts.items()},
            }

            for did, entry in devices.items():
                result[f"dev_{did}"] = {
                    "proxy_mode": entry.get("proxy_mode", "unknown"),
                }

            return self.json(result)
        except Exception as exc:
            return self.json({"error": f"{type(exc).__name__}: {exc}"})
