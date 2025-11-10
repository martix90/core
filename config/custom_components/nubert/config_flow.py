"""Config flow for Nubert integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback

from .const import DOMAIN, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class NubertConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nubert."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.info("Nubert: Discovered Bluetooth device: %s", discovery_info)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

                # Check if this is a Nubert device
        # discovery_info.advertisement may be None on some platforms, guard it
        #adv = getattr(discovery_info, "advertisement", None)
        #if not adv or not adv.service_data:
        #    _LOGGER.info("Nubert: No advertisement or service data found")
        #    return self.async_abort(reason="not_supported")

        #if SERVICE_UUID not in adv.service_data:
        #    _LOGGER.info("Nubert: Service UUID %s not found in advertisement", SERVICE_UUID)
        #    return self.async_abort(reason="not_supported")

        self._discovery_info = discovery_info
        _LOGGER.info("Nubert: Device confirmed as Nubert device")
        return await self.async_step_bluetooth_confirm()

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

        # Fallback: if we didn't find any devices by service, try matching by name
        # (some devices only expose custom GATT services after a connection)
        if not discovery_by_address:
            for device in async_discovered_service_info(self.hass, False):
                if device.name and "nubert" in device.name.lower():
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
