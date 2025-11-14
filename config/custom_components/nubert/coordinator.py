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

# Mapping between numeric source IDs used by the device and human-friendly
# source keys used in the UI and in set_source calls.
SOURCE_ID_TO_NAME: dict[int, str] = {
    0: "aux",
    1: "bt",
    2: "xlr",
    3: "aes",
    4: "spdif1",
    5: "spdif2",
    6: "opt1",
    7: "opt2",
    8: "usb",
    9: "port",
}

NAME_TO_SOURCE_ID: dict[str, int] = {v: k for k, v in SOURCE_ID_TO_NAME.items()}

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
                await self._client.start_notify(CHARACTERISTIC_UUID, self.notify_callback)
                await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x40, 0x03, 0x0A, 0x0E, 0x1E]))
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
        await self._ensure_client_connected()
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x0b, 0x01, volume]))

    async def set_source(self, source: str) -> None:
        """Set the input source on the Nubert device."""
        if not self._client or not self._client.is_connected:
            raise BleakError("Not connected to device")
        if source not in NAME_TO_SOURCE_ID:
            raise ValueError(f"Unsupported source: {source}")
        source_id = NAME_TO_SOURCE_ID[source]
        await self._ensure_client_connected()
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x0F, 0x01, source_id]))

    async def set_mute(self, mute: bool) -> None:
        """Mute or unmute the Nubert device."""
        await self._ensure_client_connected()
        mute_value = 0x01 if mute else 0x00
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x4B, 0x01, mute_value]))

    async def set_power(self, power_on: bool) -> None:
        """Turn the Nubert device on or off."""
        await self._ensure_client_connected()
        power_value = 0x01 if power_on else 0x00
        await self._client.write_gatt_char(CHARACTERISTIC_UUID, bytearray([0x1F, 0x01, power_value]))

    async def _ensure_client_connected(self) -> None:
        """Ensure we have a connected BleakClient ready to use.

        This helper will attempt to use an existing client or create and
        connect a new client using Home Assistant's bluetooth helpers.
        """
        if self._client and getattr(self._client, "is_connected", False):
            return

        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            raise BleakError(f"Could not find device {self.address}")

        self._client = BleakClient(ble_device)
        await self._client.connect()

    def notify_callback(self, sender, data: bytearray) -> None:
        """Handle notifications from the device."""
        _LOGGER.debug("Notification from Nubert device: %s", data)

        # Keep the callback short and thread-safe. Bleak may call this on
        # the event loop thread; schedule any HA-facing work as an
        # asyncio task on Home Assistant's event loop.
        try:
            if not data:
                return

            parsed: dict[str, object] = {}

            # Parse notifications according to known opcodes
            opcode = data[0]
            if opcode == 0x0A:
                # volume notification: device reports value as an unsigned
                # byte which, when subtracting 100, yields the dB value in the
                # range -80..0 (0 dB loudest, -80 dB softest). Convert that to
                # a 0..100 percentage for Home Assistant.
                vol_db = data[2] - 100 if len(data) > 2 else None
                vol_pct = None
                if vol_db is not None:
                    # map from [-80, 0] -> [0, 100]
                    vol_pct = int(round((vol_db + 80) / 80 * 100))
                    vol_pct = max(0, min(100, vol_pct))
                _LOGGER.info("Volume notification parsed (db=%s -> pct=%s)", vol_db, vol_pct)
                if vol_pct is not None:
                    parsed["volume"] = vol_pct
            elif opcode == 0x0E:
                src = data[2] if len(data) > 2 else None
                src_name = None
                if src is not None:
                    src_name = SOURCE_ID_TO_NAME.get(src, str(src))
                _LOGGER.info("Source notification parsed: %s -> %s", src, src_name)
                if src_name is not None:
                    parsed["source"] = src_name
            elif opcode == 0x1E:
                power = data[2] if len(data) > 2 else None
                _LOGGER.info("Power notification parsed: %s", power)
                if power is not None:
                    is_on = not bool(power)
                    parsed["power"] = is_on
                    # mirror onto the coordinator 'state' key expected by media_player
                    parsed["state"] = "on" if is_on else "off"

            # If we parsed something useful, schedule an async update so the
            # DataUpdateCoordinator can propagate changes to entities.
            if parsed:
                # Schedule the async handler on HA's event loop. Using
                # hass.async_create_task is safe from any thread/context.
                self.hass.async_create_task(self._async_process_notification(parsed))

        except Exception:  # Keep callback robust - log and swallow
            _LOGGER.exception("Error handling Nubert notification")

    async def _async_process_notification(self, parsed: dict[str, object]) -> None:
        """Process parsed notification data and update coordinator state.

        This runs on Home Assistant's event loop and uses
        async_set_updated_data so CoordinatorEntity listeners get updated.
        """
        try:
            # Merge parsed values into existing coordinator data
            new_data = {**(self.data or {}), **parsed}
            # async_set_updated_data will notify entities and listeners
            self.async_set_updated_data(new_data)
        except Exception:
            _LOGGER.exception("Failed to apply notification to coordinator data")

