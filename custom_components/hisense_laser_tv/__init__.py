"""Hisense Laser TV integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER, Platform.BUTTON]
CARD_PATH = "/hisense_laser_tv/hisense-laser-tv-card.js"
CARD_URL = f"{CARD_PATH}?v=0.5.0"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the bundled Lovelace card."""
    frontend_file = Path(__file__).parent / "frontend" / "hisense-laser-tv-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_PATH, str(frontend_file), False)]
    )
    add_extra_js_url(hass, CARD_URL)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration after its settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hisense Laser TV from a config entry."""
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
