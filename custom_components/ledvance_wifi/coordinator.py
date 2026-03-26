"""DataUpdateCoordinator for Ledvance Smart+ WiFi."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import tinytuya
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

_LOGGER = logging.getLogger(__name__)

type LedvanceConfigEntry = ConfigEntry[LedvanceDataUpdateCoordinator]


class LedvanceDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to poll Ledvance light status via TinyTuya."""

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

        self.device = tinytuya.BulbDevice(
            dev_id=entry.data[CONF_DEVICE_ID],
            address=entry.data[CONF_IP_ADDRESS],
            local_key=entry.data[CONF_LOCAL_KEY],
        )
        self.device.set_version(float(entry.data[CONF_PROTOCOL_VERSION]))

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device status."""
        result = await self.hass.async_add_executor_job(self.device.status)

        if not result or "dps" not in result:
            raise UpdateFailed(
                f"Failed to get status from device: {result}"
            )

        return result["dps"]

    async def async_turn_on(self) -> None:
        """Turn the light on."""
        await self.hass.async_add_executor_job(
            self.device.set_status, True, DP_POWER
        )
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the light off."""
        await self.hass.async_add_executor_job(
            self.device.set_status, False, DP_POWER
        )
        await self.async_request_refresh()

    async def async_turn_on_with_attrs(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hsv_hex: str | None = None,
        scene_num: int | None = None,
    ) -> None:
        """Turn on and set attributes in a single executor job."""

        def _send() -> None:
            self.device.set_status(True, DP_POWER)

            if scene_num is not None:
                self.device.set_value(DP_SCENE_NUM, scene_num)
                return

            if hsv_hex is not None:
                self.device.set_value(DP_MODE, "colour")
                self.device.set_value(DP_COLOR_HSV, hsv_hex)
            elif color_temp is not None:
                self.device.set_value(DP_MODE, "white")
                self.device.set_value(DP_COLOR_TEMP, color_temp)

            if brightness is not None:
                self.device.set_value(DP_BRIGHTNESS, brightness)

        await self.hass.async_add_executor_job(_send)
        await self.async_request_refresh()
