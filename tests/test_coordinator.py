"""Tests for the Ledvance Lights coordinator.

Tests the coordinator logic by mocking the TuyaDevice and HA framework,
focusing on data processing, DP command construction, and debounce behaviour.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_ledvance_lights.const import (
    DP_BRIGHTNESS,
    DP_COLOR_HSV,
    DP_COLOR_TEMP,
    DP_MODE,
    DP_POWER,
    DP_SCENE_NUM,
)


def _make_coordinator(mock_tuya_device, mock_entry_data):
    """Create a LedvanceDataUpdateCoordinator with mocked dependencies."""
    mock_entry = MagicMock()
    mock_entry.data = mock_entry_data

    mock_hass = MagicMock()

    # Make async_add_executor_job call the function directly
    async def run_in_executor(func, *args):
        return func(*args)

    mock_hass.async_add_executor_job = AsyncMock(side_effect=run_in_executor)

    with (
        patch(
            "custom_components.ha_ledvance_lights.coordinator.DataUpdateCoordinator.__init__",
            return_value=None,
        ),
        patch(
            "custom_components.ha_ledvance_lights.coordinator.TuyaDevice",
            return_value=mock_tuya_device,
        ),
    ):
        from custom_components.ha_ledvance_lights.coordinator import (
            LedvanceDataUpdateCoordinator,
        )

        coordinator = LedvanceDataUpdateCoordinator(mock_hass, mock_entry)
        coordinator.hass = mock_hass
        coordinator.async_request_refresh = AsyncMock()
        coordinator.async_set_updated_data = MagicMock()
        # Pre-populate data so optimistic updates work
        coordinator.data = {
            "20": True,
            "21": "white",
            "22": 500,
            "23": 500,
            "24": "00b401f40320",
            "26": 1,
        }
        return coordinator


async def _flush_debounce(coordinator) -> None:
    """Wait for the debounce timer to fire and the command to be sent."""
    if coordinator._debounce_task is not None:
        await coordinator._debounce_task


class TestAsyncUpdateData:
    """Tests for the _async_update_data method."""

    @pytest.mark.asyncio
    async def test_successful_status_returns_dps(self, mock_tuya_device, mock_entry_data):
        """Test that successful status fetch returns the DPS dict."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        result = await coordinator._async_update_data()

        assert result == {
            "20": True,
            "21": "white",
            "22": 500,
            "23": 500,
            "24": "00b401f40320",
            "26": 1,
        }
        mock_tuya_device.status.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_status_no_result_raises(self, mock_tuya_device, mock_entry_data):
        """Test that None status raises UpdateFailed."""
        mock_tuya_device.status.return_value = None
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        from homeassistant.helpers.update_coordinator import UpdateFailed

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_failed_status_no_dps_raises(self, mock_tuya_device, mock_entry_data):
        """Test that status without 'dps' key raises UpdateFailed."""
        mock_tuya_device.status.return_value = {"Err": "901"}
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        from homeassistant.helpers.update_coordinator import UpdateFailed

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()


class TestAsyncTurnOnWithAttrs:
    """Tests for the async_turn_on_with_attrs method (debounced)."""

    @pytest.mark.asyncio
    async def test_brightness_only_white_mode(self, mock_tuya_device, mock_entry_data):
        """Test setting brightness in white mode sends DP22."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(brightness=500)
        await _flush_debounce(coordinator)

        mock_tuya_device.set_multiple_values.assert_called_once()
        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_BRIGHTNESS)] == 500

    @pytest.mark.asyncio
    async def test_color_temp(self, mock_tuya_device, mock_entry_data):
        """Test setting color temperature sets mode to white."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(color_temp=750)
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_MODE)] == "white"
        assert dps[str(DP_COLOR_TEMP)] == 750

    @pytest.mark.asyncio
    async def test_color_temp_with_brightness(self, mock_tuya_device, mock_entry_data):
        """Test setting color temperature with brightness."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(color_temp=750, brightness=300)
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_MODE)] == "white"
        assert dps[str(DP_COLOR_TEMP)] == 750
        assert dps[str(DP_BRIGHTNESS)] == 300

    @pytest.mark.asyncio
    async def test_hsv_color(self, mock_tuya_device, mock_entry_data):
        """Test setting HSV color sets mode to colour."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(hsv_hex="007803e803e8")
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_MODE)] == "colour"
        assert dps[str(DP_COLOR_HSV)] == "007803e803e8"

    @pytest.mark.asyncio
    async def test_hsv_does_not_send_dp_brightness(self, mock_tuya_device, mock_entry_data):
        """Test that DP_BRIGHTNESS is NOT sent when HSV is set.

        Ledvance devices switch to white mode when DP22 is sent in colour mode.
        Brightness in colour mode is encoded in the V component of HSV hex.
        """
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(hsv_hex="007803e803e8", brightness=500)
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_MODE)] == "colour"
        assert dps[str(DP_COLOR_HSV)] == "007803e803e8"
        # DP_BRIGHTNESS must NOT be sent — it triggers white mode on Ledvance
        assert str(DP_BRIGHTNESS) not in dps

    @pytest.mark.asyncio
    async def test_scene_num(self, mock_tuya_device, mock_entry_data):
        """Test setting scene number (takes priority over hsv/color_temp)."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(scene_num=2)
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_SCENE_NUM)] == 2
        assert str(DP_MODE) not in dps
        assert str(DP_COLOR_HSV) not in dps

    @pytest.mark.asyncio
    async def test_scene_takes_priority_over_hsv(self, mock_tuya_device, mock_entry_data):
        """Test that scene_num takes priority when both scene and hsv are set."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(scene_num=3, hsv_hex="007803e803e8")
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_SCENE_NUM)] == 3
        assert str(DP_COLOR_HSV) not in dps
        assert str(DP_MODE) not in dps

    @pytest.mark.asyncio
    async def test_no_attrs_just_power_on(self, mock_tuya_device, mock_entry_data):
        """Test turning on with no attributes sets only power."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs()
        await _flush_debounce(coordinator)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps == {str(DP_POWER): True}

    @pytest.mark.asyncio
    async def test_optimistic_update_immediate(self, mock_tuya_device, mock_entry_data):
        """Test that optimistic update is applied immediately (before debounce)."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(brightness=500)

        # Optimistic update should fire immediately, not after debounce.
        coordinator.async_set_updated_data.assert_called_once()
        updated = coordinator.async_set_updated_data.call_args[0][0]
        assert updated[str(DP_POWER)] is True
        assert updated[str(DP_BRIGHTNESS)] == 500

        # Device command hasn't been sent yet (still debouncing).
        mock_tuya_device.set_multiple_values.assert_not_called()

        # After debounce, device gets the command.
        await _flush_debounce(coordinator)
        mock_tuya_device.set_multiple_values.assert_called_once()


class TestDebounceCoalescing:
    """Tests that rapid calls are coalesced into a single device command."""

    @pytest.mark.asyncio
    async def test_rapid_brightness_changes_coalesce(self, mock_tuya_device, mock_entry_data):
        """Test that multiple rapid brightness changes send only the last value."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        # Simulate rapid slider drags — no await between calls.
        await coordinator.async_turn_on_with_attrs(brightness=100)
        await coordinator.async_turn_on_with_attrs(brightness=300)
        await coordinator.async_turn_on_with_attrs(brightness=800)

        # Only the last debounce task should fire.
        await _flush_debounce(coordinator)

        # Device should receive exactly ONE command with the final brightness.
        mock_tuya_device.set_multiple_values.assert_called_once()
        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_BRIGHTNESS)] == 800

    @pytest.mark.asyncio
    async def test_mode_switch_then_brightness_coalesce(self, mock_tuya_device, mock_entry_data):
        """Test that mode switch + brightness change merge into one command."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        # Switch to colour mode, then immediately change brightness.
        await coordinator.async_turn_on_with_attrs(hsv_hex="007803e803e8")
        await coordinator.async_turn_on_with_attrs(brightness=600)

        await _flush_debounce(coordinator)

        # Single merged command should have both mode + brightness.
        mock_tuya_device.set_multiple_values.assert_called_once()
        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_MODE)] == "colour"
        assert dps[str(DP_COLOR_HSV)] == "007803e803e8"
        # Brightness merges via _pending_dps.update, so DP22 will be present
        # in the merged dict (from the second call which was brightness-only).
        assert dps[str(DP_BRIGHTNESS)] == 600

    @pytest.mark.asyncio
    async def test_optimistic_updates_applied_for_each_call(
        self, mock_tuya_device, mock_entry_data
    ):
        """Test that optimistic updates fire for each call, not just the last."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(brightness=100)
        await coordinator.async_turn_on_with_attrs(brightness=800)

        # Two optimistic updates should have been applied.
        assert coordinator.async_set_updated_data.call_count == 2

        await _flush_debounce(coordinator)


class TestAsyncTurnOff:
    """Tests for the async_turn_off method."""

    @pytest.mark.asyncio
    async def test_turn_off_sets_power_false(self, mock_tuya_device, mock_entry_data):
        """Test that turn_off sets power DP to False."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_off()

        mock_tuya_device.set_status.assert_called_once_with(False, DP_POWER)

    @pytest.mark.asyncio
    async def test_turn_off_optimistic_update(self, mock_tuya_device, mock_entry_data):
        """Test that turn_off applies optimistic update."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_off()

        coordinator.async_set_updated_data.assert_called_once()
        updated = coordinator.async_set_updated_data.call_args[0][0]
        assert updated[str(DP_POWER)] is False


class TestAsyncTurnOn:
    """Tests for the async_turn_on method (simple power on)."""

    @pytest.mark.asyncio
    async def test_turn_on_sets_power_true(self, mock_tuya_device, mock_entry_data):
        """Test that turn_on sets power DP to True."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on()

        mock_tuya_device.set_status.assert_called_once_with(True, DP_POWER)

    @pytest.mark.asyncio
    async def test_turn_on_optimistic_update(self, mock_tuya_device, mock_entry_data):
        """Test that turn_on applies optimistic update."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on()

        coordinator.async_set_updated_data.assert_called_once()
        updated = coordinator.async_set_updated_data.call_args[0][0]
        assert updated[str(DP_POWER)] is True
