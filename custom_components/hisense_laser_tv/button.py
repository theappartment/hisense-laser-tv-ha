"""Button platform for Hisense Laser TV."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .wake import (
    can_wake_from_standby,
    configured_mac_address,
    send_wake_packets_for_entry,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Wi-Fi wake button."""
    async_add_entities([HisenseWifiWakeButton(hass, entry)])


class HisenseWifiWakeButton(ButtonEntity):
    """Button that wakes a Hisense TV over Wi-Fi."""

    _attr_has_entity_name = True
    _attr_name = "Accendi tramite Wi-Fi"
    _attr_icon = "mdi:power"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the wake button."""
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_wifi_wake"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }

    @property
    def available(self) -> bool:
        """Return whether a valid Wi-Fi MAC is configured."""
        return can_wake_from_standby(self.entry)

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Return the configured wake address."""
        return {"mac_address": configured_mac_address(self.entry) or None}

    async def async_press(self) -> None:
        """Send the Wi-Fi wake packets."""
        await self.hass.async_add_executor_job(
            send_wake_packets_for_entry,
            self.entry,
        )
