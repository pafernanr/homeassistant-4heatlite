"""Offline configuration flow tests. Run with python -m unittest discover -s tests."""

import importlib
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

import homeassistant  # Initialise Home Assistant before importing the integration.
import voluptuous as vol

flows = importlib.import_module("custom_components.4heatlite.config_flow")


class LocalSetupTests(IsolatedAsyncioTestCase):
    def setUp(self):
        async def run_job(function, *args):
            return function(*args)

        self.flow = flows.FourHeatLiteConfigFlow()
        self.entries = []
        manager = Mock()
        manager.async_entries.return_value = self.entries
        manager.async_entry_for_domain_unique_id.return_value = None
        self.flow.hass = SimpleNamespace(
            async_add_executor_job=run_job, config_entries=manager
        )
        self.flow.context = {"source": "user"}
        self.flow.handler = flows.DOMAIN
        self.flow._async_in_progress = Mock(return_value=[])
        self.flow._async_resolve_host = AsyncMock(return_value="192.0.2.1")
        self.flow._async_authenticate = AsyncMock(side_effect=AssertionError("Cloud login"))
        self.flow._async_fetch_device_key = AsyncMock(side_effect=AssertionError("Cloud key"))
        self.scan = self.enterContext(patch.object(flows, "discover_modules", return_value=[]))
        self.probe = self.enterContext(
            patch.object(flows.FourHeatLiteApi, "test_connection", return_value=True)
        )

    async def test_manual_local_setup(self):
        menu = await self.flow.async_step_user()
        self.assertEqual(menu["menu_options"], ["local", "cloud"])
        form = await self.flow.async_step_local()
        schema = form["data_schema"]
        with self.assertRaises(vol.Invalid):
            schema({"host": "stove.test", "proxy_mode": flows.PROXY_MODE_LOCAL})
        result = await self.flow.async_step_device(schema({"host": "stove.test"}))
        self.assertEqual(result["data"]["host"], "192.0.2.1")
        self.assertEqual(result["data"]["device_key"], "")
        self.assertEqual(result["data"]["device_id"], "")
        self.assertTrue(result["data"]["local_setup"])
        self.assertEqual(result["options"]["proxy_mode"], flows.PROXY_MODE_DIRECT)
        self.assertIsNone(self.flow.unique_id)

    async def test_discovered_module_uses_device_id(self):
        self.scan.return_value = [{"device_id": "test-id", "ip": "192.0.2.1"}]
        form = await self.flow.async_step_local()
        self.assertEqual(form["step_id"], "discovery")
        form = await self.flow.async_step_discovery({"selected_device": "test-id|192.0.2.1"})
        result = await self.flow.async_step_device(form["data_schema"]({}))
        self.assertEqual(result["data"]["device_id"], "test-id")
        self.assertEqual(self.flow.unique_id, "test-id")

    async def test_duplicate_address_through_hostname(self):
        self.entries.append(SimpleNamespace(data={"host": "192.0.2.1", "device_id": ""}))
        form = await self.flow.async_step_local()
        result = await self.flow.async_step_device(form["data_schema"]({"host": "stove.test"}))
        self.assertEqual(result["errors"], {"host": "already_configured"})
        self.probe.assert_not_called()

    async def test_unreachable_module(self):
        self.probe.return_value = False
        form = await self.flow.async_step_local()
        result = await self.flow.async_step_device(form["data_schema"]({"host": "stove.test"}))
        self.assertEqual(result["errors"], {"host": "cannot_connect"})

    async def test_cloud_setup_keeps_proxy_and_device_key(self):
        self.flow._async_authenticate = AsyncMock(return_value="test-token")
        self.flow._async_fetch_device_key = AsyncMock(return_value="test-key")
        form = await self.flow.async_step_cloud({"email": "owner@example.invalid", "password": "test"})
        values = form["data_schema"]({
            "host": "stove.test", "device_id": "test-id", "proxy_mode": flows.PROXY_MODE_KEEPALIVE,
        })
        result = await self.flow.async_step_device(values)
        self.flow._async_fetch_device_key.assert_awaited_once_with("test-id")
        self.assertEqual(result["data"]["device_key"], "test-key")
        self.assertEqual(result["options"]["proxy_mode"], flows.PROXY_MODE_KEEPALIVE)
        self.assertEqual(self.flow.unique_id, "test-id")

    async def test_options_on_local_and_existing_entries(self):
        from unittest.mock import PropertyMock

        options = flows.FourHeatLiteOptionsFlow()
        entry = SimpleNamespace(data={"host": "stove.test"}, options={})
        with patch.object(type(options), "config_entry", new_callable=PropertyMock, return_value=entry):
            cloud_form = await options.async_step_init()
            self.assertIn("proxy_mode", cloud_form["data_schema"].schema)
            entry.data["local_setup"] = True
            local_form = await options.async_step_init()
            self.assertEqual(set(local_form["data_schema"].schema), {"schedules"})
