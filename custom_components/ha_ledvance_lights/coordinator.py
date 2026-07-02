"""DataUpdateCoordinator for Ledvance Lights."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
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
    FAST_POLLING_INTERVAL,
    MAX_FAST_POLL_DURATION,
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
        self._debounce_generation: int = 0
        self._command_lock = asyncio.Lock()

        # Adaptive polling: fast-poll when device is unavailable.
        self._device_unavailable: bool = False
        self._fast_poll_start: float | None = None

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch device status."""
        result = await self.hass.async_add_executor_job(self.device.status)

        if not result or "dps" not in result:
            self._enter_fast_poll()
            raise UpdateFailed(f"Failed to get status from device: {result}")

        if self._device_unavailable:
            self._exit_fast_poll()

        return result["dps"]

    @property
    def device_available(self) -> bool:
        """Return True if the last poll succeeded (i.e. device is reachable)."""
        return not self._device_unavailable

    @property
    def fast_poll_elapsed_seconds(self) -> float | None:
        """Return seconds elapsed in the current fast-poll window, if active."""
        if not self._device_unavailable or self._fast_poll_start is None:
            return None
        return round(time.monotonic() - self._fast_poll_start, 1)

    def _enter_fast_poll(self) -> None:
        """Switch to fast polling for quicker device recovery detection."""
        now = time.monotonic()
        if self._device_unavailable:
            # Already fast-polling — check if cap exceeded.
            if self._fast_poll_start and (now - self._fast_poll_start) >= MAX_FAST_POLL_DURATION:
                _LOGGER.warning(
                    "Device %s unavailable for %ds; reverting to normal polling",
                    self.device.address,
                    MAX_FAST_POLL_DURATION,
                )
                self.update_interval = timedelta(seconds=DEFAULT_POLLING_INTERVAL)
                # Clear the timer so we don't repeatedly log/re-assign on every
                # subsequent failed poll. ``_device_unavailable`` stays True so
                # we don't re-enter fast-poll until a successful poll resets it.
                self._fast_poll_start = None
            return

        _LOGGER.debug(
            "Device %s unavailable; fast polling at %ds",
            self.device.address,
            FAST_POLLING_INTERVAL,
        )
        self._device_unavailable = True
        self._fast_poll_start = now
        self.update_interval = timedelta(seconds=FAST_POLLING_INTERVAL)

    def _exit_fast_poll(self) -> None:
        """Device recovered — revert to normal polling interval."""
        _LOGGER.info("Device %s recovered; resuming normal polling", self.device.address)
        self._device_unavailable = False
        self._fast_poll_start = None
        self.update_interval = timedelta(seconds=DEFAULT_POLLING_INTERVAL)

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

    async def _async_send_debounced(self, generation: int) -> None:
        """Wait for the debounce period, then send accumulated DPs to the device.

        If new DPs arrive during the wait, the timer resets and the new values
        are merged in.  Only the final merged set is sent to the device.

        ``generation`` is captured at scheduling time so that, even if this
        task wins a race against ``cancel()``, it can detect that a newer
        scheduling has superseded it and bail out without sending.
        """
        try:
            await asyncio.sleep(_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            # A newer call cancelled us — the new task will send instead.
            return

        # Grab the accumulated DPs and clear, while holding the lock so a
        # concurrent _schedule_debounced_send cannot interleave between the
        # generation check and the snapshot.
        async with self._command_lock:
            if generation != self._debounce_generation:
                # Superseded by a newer scheduling that won the cancel race.
                return
            dps = self._pending_dps.copy()
            self._pending_dps.clear()
            self._debounce_task = None

        if not dps:
            return

        try:
            await self.hass.async_add_executor_job(self.device.set_multiple_values, dps)
        except Exception:
            _LOGGER.exception("Failed to send DPs to device: %s", dps)
            # Schedule a refresh so the UI reconciles with actual device state
            # rather than keeping the (possibly wrong) optimistic state.
            await self.async_request_refresh()
            return

        # Schedule a background refresh to confirm the device accepted the
        # change (it normally pushes new state, but a refresh guarantees the
        # UI converges even if the optimistic guess was wrong).
        await self.async_request_refresh()

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

        # Bump the generation so any in-flight task that wins the cancel race
        # will detect it has been superseded.
        self._debounce_generation += 1
        my_generation = self._debounce_generation

        # Cancel previous debounce timer if still waiting.
        if self._debounce_task is not None and not self._debounce_task.done():
            self._debounce_task.cancel()

        # Start a new debounce timer.
        self._debounce_task = asyncio.ensure_future(self._async_send_debounced(my_generation))

    async def async_shutdown_device(self) -> None:
        """Cancel any pending debounce work and close the device socket.

        Called from ``async_unload_entry`` after platforms are unloaded so no
        entity method can fire against a closed socket.
        """
        # Bump generation so any in-flight task bails out even if we lose the
        # cancel race.
        self._debounce_generation += 1
        task = self._debounce_task
        self._debounce_task = None
        self._pending_dps.clear()
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.hass.async_add_executor_job(self.device.close)

    async def _async_set_power(self, on: bool) -> None:
        """Set power immediately (not debounced) with optimistic update.

        ``set_status`` reports failure by returning an error dict rather than
        raising, so check the result — otherwise a failed toggle would leave
        the wrong optimistic state on screen until the next poll.
        """
        self._apply_optimistic_update({str(DP_POWER): on})
        result = await self.hass.async_add_executor_job(self.device.set_status, on, DP_POWER)
        if not result or "Error" in result:
            _LOGGER.warning(
                "Failed to turn %s device %s: %s",
                "on" if on else "off",
                self.device.address,
                result,
            )
            await self.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn the light on (immediate — not debounced)."""
        await self._async_set_power(True)

    async def async_turn_off(self) -> None:
        """Turn the light off (immediate — not debounced)."""
        await self._async_set_power(False)

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
