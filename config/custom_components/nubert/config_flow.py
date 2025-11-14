"""Config flow for Nubert integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
import voluptuous as vol

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import CHARACTERISTIC_UUID, DOMAIN, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class NubertConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nubert."""

    VERSION = 1

    received_wls_type = None
    notify_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak | None
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug("Nubert: Discovered Bluetooth device: %s", discovery_info)

        # If discovery_info is None this flow was started manually or in an
        # unexpected way. Redirect to the user selection step (which will
        # present discovered devices) to avoid AttributeError below.
        if discovery_info is None:
            _LOGGER.debug("Nubert: async_step_bluetooth called without discovery_info; showing user selection")
            return await self.async_step_user()

        # Use the BLE address as unique id (may be random/private on some devices)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        # Attempt to verify this device is a controllable speaker (master or single)
        # by connecting and probing the characteristic. If the probe fails or the
        # device reports it's a slave, abort discovery.
        try:
            # Get Bleak device for address
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, discovery_info.address, connectable=True
            )
            if not ble_device:
                _LOGGER.debug("Nubert: No BLE device found for address %s", discovery_info.address)
                errors = {"base": "BLE Device not found"}
                return self.async_show_form(step_id="bluetooth", errors=errors)

            client = BleakClient(ble_device)
            # short timeout to avoid blocking discovery
            try:
                _LOGGER.debug("Connection to Nubert device at %s", discovery_info.address)
                async with asyncio.timeout(5):
                    await client.connect()
                    await client.start_notify(CHARACTERISTIC_UUID, self.notify_callback)
            except TimeoutError as err:
                _LOGGER.debug("Nubert: Timeout connecting to %s: %s", discovery_info.address, err)
                errors = {"base": "Could not connect to device"}
                return self.async_show_form(step_id="bluetooth", errors=errors)

            # Write probe command 0x40 0x01 0x34
            try:
                _LOGGER.debug("Nubert: Writing probe to device at %s", discovery_info.address)
                await client.write_gatt_char(CHARACTERISTIC_UUID, bytes.fromhex("400134"))
            except BleakError as err:
                _LOGGER.debug("Nubert: Write probe failed: %s", err)
                await client.disconnect()
                errors = {"base": "Could not write to device"}
                return self.async_show_form(step_id="bluetooth", errors=errors)

            try:
                await asyncio.wait_for(self.notify_event.wait(), timeout=2.0)
                if self.received_wls_type in {0, 2}:
                    _LOGGER.debug("Nubert: Device at %s is master/single (type=%s)", discovery_info.address, self.received_wls_type)
                else:
                    _LOGGER.debug("Nubert: Device at %s is not master/single (type=%s)", discovery_info.address, self.received_wls_type)
                    await client.stop_notify(CHARACTERISTIC_UUID)
                    await client.disconnect()
                    errors = {"base": "Device is not master/single"}
                    return self.async_show_form(step_id="bluetooth", errors=errors)
            except TimeoutError:
                _LOGGER.debug("Nubert: No notification received from device at %s", discovery_info.address)
                await client.stop_notify(CHARACTERISTIC_UUID)
                await client.disconnect()
                errors = {"base": "No response from device"}
                return self.async_show_form(step_id="bluetooth", errors=errors)

            await client.disconnect()


        except (BleakError, TimeoutError) as err:
            _LOGGER.debug("Nubert: BLE probe failed for %s: %s", discovery_info.address, err)
            errors = {"base": "Timeout or communication error"}
            return self.async_show_form(step_id="bluetooth", errors=errors)

        # Passed verification
        self._discovery_info = discovery_info
        _LOGGER.info("Nubert: Device at %s verified as master/single", discovery_info.address)
        return await self.async_step_bluetooth_confirm()


    def notify_callback(self, sender, data: bytearray) -> None:
        """Notification callback to handle incoming data."""
        _LOGGER.info("Nubert: Notification from %s: %s", sender, data)
        try:
            if not data:
                return
            if data[0] != 0x34:
                return
            self.received_wls_type = data[2] if len(data) > 2 else None
            self.loop.call_soon_threadsafe(self.notify_event.set)
        except Exception:
            _LOGGER.exception("Nubert: Error processing notification from %s: %s", sender, data)



    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm bluetooth discovery."""
        _LOGGER.info("Nubert: Confirming Bluetooth device: %s", self._discovery_info)
        if not self._discovery_info:
            return self.async_abort(reason="no_device_found")

        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or self._discovery_info.address,
                data={CONF_ADDRESS: self._discovery_info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or self._discovery_info.address
            },
        )

    @callback
    def _async_get_devices(self) -> dict[str, str]:
        """Get discovered devices."""
        _LOGGER.debug("Nubert: Scanning for Bluetooth devices")
        # First try to find devices advertising our service (service data or service UUID)
        discovery_by_address: dict[str, BluetoothServiceInfoBleak] = {}

        for device in async_discovered_service_info(self.hass, False):
            adv = getattr(device, "advertisement", None)
            if not adv:
                continue

            # service_data is a dict, service_uuids is a list
            service_data = getattr(adv, "service_data", {}) or {}
            service_uuids = getattr(adv, "service_uuids", []) or []

            if SERVICE_UUID in service_data or SERVICE_UUID in service_uuids:
                discovery_by_address[device.address] = device


        self._discovered_devices = discovery_by_address
        return {
            address: discovery.name or address
            for address, discovery in discovery_by_address.items()
            if address not in self._async_current_ids()
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery = self._discovered_devices[address]
            await self.async_set_unique_id(address, raise_on_progress=False)
            return self.async_create_entry(
                title=discovery.name or discovery.address,
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_get_devices()
        if not current_addresses:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(current_addresses)}
            ),
        )
