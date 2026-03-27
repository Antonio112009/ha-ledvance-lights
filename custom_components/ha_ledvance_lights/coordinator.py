"""DataUpdateCoordinator for Ledvance Lights."""

from __future__ import annotations

import asyncio
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

# Debounce delay: wait this long after the last change before sending to the
# device.  Rapid slider drags will coalesce into a single command.
_DEBOUNCE_SECONDS = 0.3

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

        # Debounce state: accumulates DPs from rapid calls, sends once settled.
        self._pending_dps: dict[str, Any] = {}
        self._debounce_task: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device status."""
        result = await self.hass.async_add_executor_job(self.device.status)

        if not result or "dps" not in result:
            raise UpdateFailed(f"Failed to get status from device: {result}")

        return result["dps"]

    def _apply_optimistic_update(self, dps: dict[str, Any]) -> None:
        """Apply DPs to local data immediately so the UI reflects changes instantly.

        Called BEFORE sending the command to the device so that any subsequent
        calls (e.g. brightness change right after a mode switch) see the
        intended state, avoiding race conditions.
        """
        if not hasattr(self, "data") or self.data is None:
            return
        updated = {**self.data, **dps}
        self.async_set_updated_data(updated)

    async def _async_send_debounced(self) -> None:
        """Wait for the debounce period, then send accumulated DPs to the device.

        If new DPs arrive during the wait, the timer resets and the new values
        are merged in.  Only the final merged set is sent to the device.
        """
        try:
            await asyncio.sleep(_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            # A newer call cancelled us — the new task will send instead.
            return

        # Grab the accumulated DPs and clear.
        async with self._command_lock:
            dps = self._pending_dps.copy()
            self._pending_dps.clear()
            self._debounce_task = None

        if not dps:
            return

        try:
            await self.hass.async_add_executor_job(self.device.set_multiple_values, dps)
        except Exception:
            _LOGGER.exception("Failed to send DPs to device: %s", dps)

    def _schedule_debounced_send(self, dps: dict[str, Any]) -> None:
        """Merge *dps* into the pending set and (re)start the debounce timer.

        Optimistic update is applied immediately so the UI stays responsive.
        The actual device command is delayed until no new changes arrive for
        ``_DEBOUNCE_SECONDS``.
        """
        # Merge into pending — later values overwrite earlier ones.
        self._pending_dps.update(dps)

        # Optimistic: update local state now.
        self._apply_optimistic_update(dps)

        # Cancel previous debounce timer if still waiting.
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Start a new debounce timer.
        self._debounce_task = asyncio.ensure_future(self._async_send_debounced())

    async def async_turn_on(self) -> None:
        """Turn the light on (immediate — not debounced)."""
        self._apply_optimistic_update({str(DP_POWER): True})
        await self.hass.async_add_executor_job(self.device.set_status, True, DP_POWER)

    async def async_turn_off(self) -> None:
        """Turn the light off (immediate — not debounced)."""
        self._apply_optimistic_update({str(DP_POWER): False})
        await self.hass.async_add_executor_job(self.device.set_status, False, DP_POWER)

    async def async_turn_on_with_attrs(
        self,
        brightness: int | None = None,
        color_temp: int | None = None,
        hsv_hex: str | None = None,
        scene_num: int | None = None,
    ) -> None:
        """Turn on and set attributes with debouncing.

        Rapid sequential calls (e.g. dragging a brightness slider) are merged
        into a single device command.  The optimistic update is applied
        immediately so the UI stays responsive, but the actual TCP command is
        delayed by ``_DEBOUNCE_SECONDS`` to coalesce rapid changes.

        IMPORTANT: In colour mode, brightness is encoded in the V component of
        the HSV hex string (DP24).  DP22 (DP_BRIGHTNESS) must NOT be sent in
        colour mode — Ledvance devices interpret it as a white-mode command and
        switch away from colour mode.
        """
        dps: dict[str, Any] = {str(DP_POWER): True}

        if scene_num is not None:
            dps[str(DP_SCENE_NUM)] = scene_num
        elif hsv_hex is not None:
            dps[str(DP_MODE)] = "colour"
            dps[str(DP_COLOR_HSV)] = hsv_hex
            # Do NOT send DP_BRIGHTNESS — it triggers white mode on Ledvance.
            # Brightness in colour mode is the V component of the HSV hex.
        elif color_temp is not None:
            dps[str(DP_MODE)] = "white"
            dps[str(DP_COLOR_TEMP)] = color_temp
            if brightness is not None:
                dps[str(DP_BRIGHTNESS)] = brightness
        else:
            # No mode change — brightness-only in white mode.
            if brightness is not None:
                dps[str(DP_BRIGHTNESS)] = brightness

        self._schedule_debounced_send(dps)
