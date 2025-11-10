"""Data update coordinator for Nubert devices."""

from __future__ import annotations

from datetime import timedelta
import logging

from bleak import BleakClient
from bleak.exc import BleakError

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CHARACTERISTIC_UUID, CONTROL_SERVICE_UUID, DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class NubertCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from Nubert speaker."""

    def __init__(
        self,
        hass: HomeAssistant,
        address: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
            config_entry=config_entry,
        )
        _LOGGER.info("NubertCoordinator initialized for device at %s", address)
        self.address = address
        self._client: BleakClient | None = None

    async def _async_update_data(self):
        """Update data via Bluetooth."""
        try:
            _LOGGER.info("Get data from Nubert device at %s", self.address)
            if not self._client or not self._client.is_connected:
                # Get a BLE device from the scanner
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )
                if not ble_device:
                    raise UpdateFailed(
                        f"Could not find device {self.address}"
                    ) from None

                self._client = BleakClient(ble_device)
                await self._client.connect()

                # Verify this is a Nubert device
                if not any(
                    service.uuid == CONTROL_SERVICE_UUID for service in self._client.services
                ):
                    raise UpdateFailed("Device is not a Nubert speaker") from None

            # Get current state from the device
            try:
                #self._client.start_notify(CHARACTERISTIC_UUID, noify_callback=lambda s, d: None)
                _raw = await self._client.read_gatt_char(CHARACTERISTIC_UUID)
                # TODO: Parse the state data based on Nubert's protocol
                # This is a placeholder until we know the actual data format

                _LOGGER.debug("Reading raw data from Nubert device: %s", _raw)
            except BleakError as err:
                self._client = None
                _LOGGER.error("Failed to read from Nubert device: %s", err)
                raise UpdateFailed("Failed to read device state") from err
            else:
                return {
                    "state": "on",
                    "volume": 50,
                    "source": "bluetooth",
                }

        except BleakError as error:
            self._client = None
            _LOGGER.error("Bluetooth communication error: %s", error)
            raise UpdateFailed(f"Error communicating with device: {error}") from error

    async def set_volume(self, volume: int) -> None:
        """Set the volume on the Nubert device."""
        if not self._client or not self._client.is_connected:
            raise BleakError("Not connected to device")
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x0b, 0x01, volume]))

    async def set_source(self, source: str) -> None:
        """Set the input source on the Nubert device."""
        if not self._client or not self._client.is_connected:
            raise BleakError("Not connected to device")
        source_map = {
            "aux": 0,
            "bt": 1,
            "xlr": 2,
            "aes": 3,
            "spdif1": 4,
            "spdif2": 5,
            "opt1": 6,
            "opt2": 7,
            "usb": 8,
            "port": 9
        }
        if source not in source_map:
            raise ValueError(f"Unsupported source: {source}")
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x0F, 0x01, source_map[source]]))

    async def set_mute(self, mute: bool) -> None:
        """Mute or unmute the Nubert device."""
        if not self._client or not self._client.is_connected:
            raise BleakError("Not connected to device")
        mute_value = 0x01 if mute else 0x00
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x4B, 0x01, mute_value]))

    async def set_power(self, power_on: bool) -> None:
        """Turn the Nubert device on or off."""
        if not self._client or not self._client.is_connected:
            raise BleakError("Not connected to device")
        power_value = 0x01 if power_on else 0x00
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x1F, 0x01, power_value]))

    async def notify_callback(self, sender: int, data: bytearray) -> None:
        """Handle notifications from the device."""
        _LOGGER.debug("Notification from Nubert device: %s", data)

        match data[0]:
            case 0x0A:
                _LOGGER.info("Volume changed to %d", data[2] - 100)
            case 0x0D:
                _LOGGER.info("Input state changed to %d", data[2])
