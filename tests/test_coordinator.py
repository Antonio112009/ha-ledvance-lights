"""Tests for the Ledvance Lights coordinator.

Tests the coordinator logic by mocking the TuyaDevice and HA framework,
focusing on data processing and DP command construction.
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

        # Import the actual exception to check
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
    """Tests for the async_turn_on_with_attrs method."""

    @pytest.mark.asyncio
    async def test_brightness_only(self, mock_tuya_device, mock_entry_data):
        """Test setting brightness only."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(brightness=500)

        mock_tuya_device.set_multiple_values.assert_called_once()
        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_BRIGHTNESS)] == 500
        assert str(DP_MODE) not in dps

    @pytest.mark.asyncio
    async def test_color_temp(self, mock_tuya_device, mock_entry_data):
        """Test setting color temperature sets mode to white."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(color_temp=750)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_MODE)] == "white"
        assert dps[str(DP_COLOR_TEMP)] == 750

    @pytest.mark.asyncio
    async def test_color_temp_with_brightness(self, mock_tuya_device, mock_entry_data):
        """Test setting color temperature with brightness."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(color_temp=750, brightness=300)

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

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_MODE)] == "colour"
        assert dps[str(DP_COLOR_HSV)] == "007803e803e8"

    @pytest.mark.asyncio
    async def test_scene_num(self, mock_tuya_device, mock_entry_data):
        """Test setting scene number (takes priority over hsv/color_temp)."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(scene_num=2)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_POWER)] is True
        assert dps[str(DP_SCENE_NUM)] == 2
        # Scene should not set mode or color
        assert str(DP_MODE) not in dps
        assert str(DP_COLOR_HSV) not in dps

    @pytest.mark.asyncio
    async def test_scene_takes_priority_over_hsv(self, mock_tuya_device, mock_entry_data):
        """Test that scene_num takes priority when both scene and hsv are set."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(scene_num=3, hsv_hex="007803e803e8")

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_SCENE_NUM)] == 3
        assert str(DP_COLOR_HSV) not in dps
        assert str(DP_MODE) not in dps

    @pytest.mark.asyncio
    async def test_no_attrs_just_power_on(self, mock_tuya_device, mock_entry_data):
        """Test turning on with no attributes sets only power."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs()

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps == {str(DP_POWER): True}

    @pytest.mark.asyncio
    async def test_optimistic_update_after(self, mock_tuya_device, mock_entry_data):
        """Test that optimistic update is applied after setting values."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(brightness=500)

        coordinator.async_set_updated_data.assert_called_once()
        updated = coordinator.async_set_updated_data.call_args[0][0]
        assert updated[str(DP_POWER)] is True
        assert updated[str(DP_BRIGHTNESS)] == 500

    @pytest.mark.asyncio
    async def test_hsv_with_brightness_sends_both(self, mock_tuya_device, mock_entry_data):
        """Test that both DP22 and HSV are sent when brightness + HSV are set."""
        coordinator = _make_coordinator(mock_tuya_device, mock_entry_data)

        await coordinator.async_turn_on_with_attrs(hsv_hex="007803e803e8", brightness=500)

        dps = mock_tuya_device.set_multiple_values.call_args[0][0]
        assert dps[str(DP_MODE)] == "colour"
        assert dps[str(DP_COLOR_HSV)] == "007803e803e8"
        # DP_BRIGHTNESS is sent alongside HSV — DP22 controls physical brightness
        assert dps[str(DP_BRIGHTNESS)] == 500


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
