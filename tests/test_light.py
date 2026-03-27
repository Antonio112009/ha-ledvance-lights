"""Tests for the Ledvance Lights light entity.

Tests the light entity property calculations and command dispatch by
mocking the coordinator and HA framework.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.light import ColorMode

from custom_components.ha_ledvance_lights.const import (
    SCENE_EFFECTS,
    TUYA_BRIGHTNESS_MAX,
    ha_brightness_to_tuya,
    hs_to_tuya_hex,
    kelvin_to_tuya_ct,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)
from custom_components.ha_ledvance_lights.light import LedvanceLight


def _make_light(coordinator_data):
    """Create a LedvanceLight with mocked coordinator and entry."""
    mock_coordinator = MagicMock()
    mock_coordinator.data = coordinator_data
    mock_coordinator.async_turn_on_with_attrs = AsyncMock()
    mock_coordinator.async_turn_off = AsyncMock()

    mock_entry = MagicMock()
    mock_entry.data = {
        "device_id": "bf3a09ef3b5eddce45qwer",
        "ip_address": "192.168.1.100",
        "local_key": "abcdef1234567890",
        "protocol_version": "3.4",
    }
    mock_entry.title = "Ledvance Light qwer"

    # Use __new__ to skip __init__ chain, then set required attributes manually
    light = object.__new__(LedvanceLight)
    light.coordinator = mock_coordinator
    light._attr_unique_id = mock_entry.data["device_id"]
    return light


class TestIsOn:
    """Tests for the is_on property."""

    def test_on_when_power_true(self, sample_dps):
        light = _make_light(sample_dps)
        assert light.is_on is True

    def test_off_when_power_false(self, sample_dps):
        sample_dps["20"] = False
        light = _make_light(sample_dps)
        assert light.is_on is False

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.is_on is None

    def test_none_when_no_power_key(self):
        light = _make_light({"21": "white"})
        assert light.is_on is None


class TestBrightness:
    """Tests for the brightness property."""

    def test_mid_brightness(self, sample_dps):
        """Test brightness conversion from Tuya 500 to HA scale."""
        light = _make_light(sample_dps)
        expected = tuya_brightness_to_ha(500)
        assert light.brightness == expected

    def test_min_brightness(self):
        light = _make_light({"20": True, "22": 10})
        assert light.brightness == 0

    def test_max_brightness(self):
        light = _make_light({"20": True, "22": 1000})
        assert light.brightness == 255

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.brightness is None

    def test_none_when_no_brightness_key(self):
        light = _make_light({"20": True})
        assert light.brightness is None


class TestColorMode:
    """Tests for the color_mode property."""

    def test_hs_when_colour_mode(self, sample_dps_colour):
        light = _make_light(sample_dps_colour)
        assert light.color_mode == ColorMode.HS

    def test_color_temp_when_white_mode(self, sample_dps):
        light = _make_light(sample_dps)
        assert light.color_mode == ColorMode.COLOR_TEMP

    def test_color_temp_when_no_mode_key(self):
        """Defaults to COLOR_TEMP when mode key is missing."""
        light = _make_light({"20": True})
        assert light.color_mode == ColorMode.COLOR_TEMP

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.color_mode is None


class TestColorTempKelvin:
    """Tests for the color_temp_kelvin property."""

    def test_mid_range(self, sample_dps):
        """Test conversion of Tuya CT 500 to Kelvin."""
        light = _make_light(sample_dps)
        expected = tuya_ct_to_kelvin(500)
        assert light.color_temp_kelvin == expected

    def test_warm(self):
        light = _make_light({"20": True, "21": "white", "23": 0})
        assert light.color_temp_kelvin == 2700

    def test_cool(self):
        light = _make_light({"20": True, "21": "white", "23": 1000})
        assert light.color_temp_kelvin == 6500

    def test_none_when_colour_mode(self, sample_dps_colour):
        """Should return None when in colour mode."""
        light = _make_light(sample_dps_colour)
        assert light.color_temp_kelvin is None

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.color_temp_kelvin is None

    def test_none_when_no_ct_key(self):
        light = _make_light({"20": True, "21": "white"})
        assert light.color_temp_kelvin is None


class TestHsColor:
    """Tests for the hs_color property."""

    def test_parses_hex_correctly(self, sample_dps_colour):
        """Test parsing of green HSV hex."""
        light = _make_light(sample_dps_colour)
        h, s = light.hs_color
        assert h == 120.0  # 0x0078 = 120
        assert s == 100.0  # 0x03e8 = 1000 -> 100.0

    def test_custom_color(self):
        """Test parsing with H=180, S=50%."""
        dps = {"20": True, "21": "colour", "24": "00b401f40320"}
        light = _make_light(dps)
        h, s = light.hs_color
        assert h == 180.0
        assert s == 50.0

    def test_none_when_white_mode(self, sample_dps):
        """Should return None when in white mode."""
        light = _make_light(sample_dps)
        assert light.hs_color is None

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.hs_color is None

    def test_none_when_short_hex(self):
        """Should return None when hex string is too short."""
        dps = {"20": True, "21": "colour", "24": "00b4"}
        light = _make_light(dps)
        assert light.hs_color is None

    def test_none_when_empty_hex(self):
        dps = {"20": True, "21": "colour", "24": ""}
        light = _make_light(dps)
        assert light.hs_color is None


class TestEffectList:
    """Tests for the effect_list property."""

    def test_returns_scene_effects(self, sample_dps):
        light = _make_light(sample_dps)
        assert light.effect_list == SCENE_EFFECTS

    def test_has_four_scenes(self, sample_dps):
        light = _make_light(sample_dps)
        assert len(light.effect_list) == 4


class TestEffect:
    """Tests for the effect property."""

    def test_returns_scene_name(self, sample_dps_scene):
        """Test scene 2 maps to 'Scene 2'."""
        light = _make_light(sample_dps_scene)
        assert light.effect == "Scene 2"

    def test_scene_1(self):
        dps = {"20": True, "21": "scene", "26": 1}
        light = _make_light(dps)
        assert light.effect == "Scene 1"

    def test_scene_4(self):
        dps = {"20": True, "21": "scene", "26": 4}
        light = _make_light(dps)
        assert light.effect == "Scene 4"

    def test_none_when_white_mode(self, sample_dps):
        light = _make_light(sample_dps)
        assert light.effect is None

    def test_none_when_colour_mode(self, sample_dps_colour):
        light = _make_light(sample_dps_colour)
        assert light.effect is None

    def test_none_when_no_data(self):
        light = _make_light(None)
        assert light.effect is None

    def test_none_when_scene_num_out_of_range(self):
        dps = {"20": True, "21": "scene", "26": 99}
        light = _make_light(dps)
        assert light.effect is None

    def test_none_when_scene_num_zero(self):
        dps = {"20": True, "21": "scene", "26": 0}
        light = _make_light(dps)
        assert light.effect is None


class TestAsyncTurnOn:
    """Tests for the async_turn_on method."""

    @pytest.mark.asyncio
    async def test_with_brightness(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on(brightness=128)

        expected_tuya = ha_brightness_to_tuya(128)
        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=expected_tuya,
            color_temp=None,
            hsv_hex=None,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_with_color_temp(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on(color_temp_kelvin=4000)

        expected_ct = kelvin_to_tuya_ct(4000)
        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=expected_ct,
            hsv_hex=None,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_with_hs_color(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on(hs_color=(120.0, 80.0))

        # Should use current brightness from coordinator data (DP 22 = 500)
        expected_hex = hs_to_tuya_hex(120.0, 80.0, 500)
        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=expected_hex,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_with_hs_color_and_brightness(self, sample_dps):
        """When both hs_color and brightness are set, brightness is used for V component."""
        light = _make_light(sample_dps)
        await light.async_turn_on(hs_color=(200.0, 50.0), brightness=200)

        brightness_tuya = ha_brightness_to_tuya(200)
        expected_hex = hs_to_tuya_hex(200.0, 50.0, brightness_tuya)
        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=brightness_tuya,
            color_temp=None,
            hsv_hex=expected_hex,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_with_hs_color_no_current_brightness(self):
        """When no current brightness data, should use TUYA_BRIGHTNESS_MAX."""
        light = _make_light({"20": True, "21": "colour"})
        await light.async_turn_on(hs_color=(0.0, 100.0))

        expected_hex = hs_to_tuya_hex(0.0, 100.0, TUYA_BRIGHTNESS_MAX)
        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=expected_hex,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_with_effect(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on(effect="Scene 3")

        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=None,
            scene_num=3,
        )

    @pytest.mark.asyncio
    async def test_with_effect_scene_1(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on(effect="Scene 1")

        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=None,
            scene_num=1,
        )

    @pytest.mark.asyncio
    async def test_with_unknown_effect_no_scene(self, sample_dps):
        """Unknown effect name should not set scene_num."""
        light = _make_light(sample_dps)
        await light.async_turn_on(effect="Unknown Scene")

        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=None,
            scene_num=None,
        )

    @pytest.mark.asyncio
    async def test_no_kwargs_just_power_on(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_on()

        light.coordinator.async_turn_on_with_attrs.assert_awaited_once_with(
            brightness=None,
            color_temp=None,
            hsv_hex=None,
            scene_num=None,
        )


class TestAsyncTurnOff:
    """Tests for the async_turn_off method."""

    @pytest.mark.asyncio
    async def test_calls_coordinator_turn_off(self, sample_dps):
        light = _make_light(sample_dps)
        await light.async_turn_off()

        light.coordinator.async_turn_off.assert_awaited_once()
