"""Ledvance Lights integration for Home Assistant."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .coordinator import LedvanceConfigEntry, LedvanceDataUpdateCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: LedvanceConfigEntry) -> bool:
    """Set up Ledvance Lights from a config entry."""
    coordinator = LedvanceDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: LedvanceConfigEntry) -> bool:
    """Unload a config entry and close the device socket.

    Order matters: unload platforms first so no entity method can fire after
    the socket is closed, then cancel any pending debounced command, then
    close the socket off-loop.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: LedvanceDataUpdateCoordinator = entry.runtime_data
        await coordinator.async_shutdown_device()
    return unload_ok
