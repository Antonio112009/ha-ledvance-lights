"""DataUpdateCoordinator for Ledvance Lights."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DEFAULT_POLLING_INTERVAL,
    DOMAIN,
    DP_BRIGHTNESS,
    DP_COLOR_HSV,
    DP_COLOR_TEMP,
    DP_MODE,
    DP_POWER,
    DP_SCENE_NUM,
)
from .tuya import TuyaDevice

_LOGGER = logging.getLogger(__name__)

type LedvanceConfigEntry = ConfigEntry[LedvanceDataUpdateCoordinator]


class LedvanceDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to poll Ledvance light status via local Tuya protocol."""

    config_entry: LedvanceConfigEntry

    def __init__(self, hass: HomeAssistant, entry: LedvanceConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_POLLING_INTERVAL),
            config_entry=entry,
        )

        self.device = TuyaDevice(
            dev_id=entry.data[CONF_DEVICE_ID],
            address=entry.data[CONF_IP_ADDRESS],
            local_key=entry.data[CONF_LOCAL_KEY],
            version=entry.data.get(CONF_PROTOCOL_VERSION, "3.3"),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device status."""
        result = await self.hass.async_add_executor_job(self.device.status)

        if not result or "dps" not in result:
            raise UpdateFailed(f"Failed to get status from device: {result}")

        return result["dps"]

    async def async_turn_on(self) -> None:
        """Turn the light on."""
        await self.hass.async_add_executor_job(self.device.set_status, True, DP_POWER)
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the light off."""
        await self.hass.async_add_executor_job(self.device.set_status, False, DP_POWER)
        await self.async_request_refresh()

    async def async_turn_on_with_attrs(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hsv_hex: str | None = None,
        scene_num: int | None = None,
    ) -> None:
        """Turn on and set attributes in a single command.

        Batches all DP changes into one set_multiple_values call to avoid
        multiple TCP connections.
        """
        dps: dict[str, Any] = {str(DP_POWER): True}

        if scene_num is not None:
            dps[str(DP_SCENE_NUM)] = scene_num
        elif hsv_hex is not None:
            dps[str(DP_MODE)] = "colour"
            dps[str(DP_COLOR_HSV)] = hsv_hex
        elif color_temp is not None:
            dps[str(DP_MODE)] = "white"
            dps[str(DP_COLOR_TEMP)] = color_temp

        if brightness is not None:
            dps[str(DP_BRIGHTNESS)] = brightness

        await self.hass.async_add_executor_job(self.device.set_multiple_values, dps)
        await self.async_request_refresh()
