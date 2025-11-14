"""Support for Nubert speakers."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SOURCE_ID_TO_NAME, NubertCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Nubert speaker from a config entry."""
    coordinator: NubertCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([NubertMediaPlayer(coordinator, entry)], True)


class NubertMediaPlayer(CoordinatorEntity, MediaPlayerEntity):
    """Representation of a Nubert speaker."""

    _attr_has_entity_name = True
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.SELECT_SOURCE
    )

    def __init__(self, coordinator: NubertCoordinator, entry: ConfigEntry) -> None:
        """Initialize the media player."""
        # Initialize CoordinatorEntity so it registers listeners on the
        # DataUpdateCoordinator. This sets up coordinator_context used by
        # the helper base class.
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Nubert",
            "model": "Speaker",  # TODO: Get actual model from device
            "via_device": (DOMAIN, coordinator.address),
        }

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> str | None:
        """Return the state of the device."""
        return self.coordinator.data.get("state")

    @property
    def volume_level(self) -> float | None:
        """Return the volume level."""
        if (volume := self.coordinator.data.get("volume")) is not None:
            return float(volume) / 100
        return None

    @property
    def source(self) -> str | None:
        """Return the current input source."""
        return self.coordinator.data.get("source")

    @property
    def source_list(self) -> list[str] | None:
        """Return a list of available input sources for the UI."""
        # Present the canonical source names from the coordinator mapping
        return list(SOURCE_ID_TO_NAME.values())

    async def async_select_source(self, source: str) -> None:
        """Select input source (called from UI)."""
        # Delegate to coordinator which will write the GATT characteristic
        await self.coordinator.set_source(source)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self.coordinator.set_volume(int(volume * 100))

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        await self.coordinator.set_power(True)

    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        await self.coordinator.set_power(False)
