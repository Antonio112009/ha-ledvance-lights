"""Ledvance Smart+ WiFi integration for Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import LedvanceConfigEntry, LedvanceDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: LedvanceConfigEntry) -> bool:
    """Set up Ledvance Smart+ WiFi from a config entry."""
    coordinator = LedvanceDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LedvanceConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
