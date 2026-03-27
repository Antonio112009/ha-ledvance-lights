"""Tests for the Ledvance Lights diagnostics module.

Tests focus on the pure _format_device_status function and verifying
that async_get_config_entry_diagnostics redacts sensitive data.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.ha_ledvance_lights.const import (
    CONF_LOCAL_KEY,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)
from custom_components.ha_ledvance_lights.diagnostics import (
    TO_REDACT_CONFIG,
    _format_device_status,
)


class TestFormatDeviceStatus:
    """Tests for the _format_device_status function."""

    def test_full_dps(self, sample_dps):
        """Test formatting with a complete DPS dict."""
        result = _format_device_status(sample_dps)

        assert result["power"] == "ON"
        assert result["mode"] == "white"
        assert result["brightness"]["tuya_value"] == 500
        assert result["brightness"]["ha_value"] == tuya_brightness_to_ha(500)
        assert 0 <= result["brightness"]["percent"] <= 100
        assert result["color_temperature"]["tuya_value"] == 500
        assert result["color_temperature"]["kelvin"] == tuya_ct_to_kelvin(500)
        assert result["color_hsv"]["raw_hex"] == "00b401f40320"
        assert result["color_hsv"]["hue"] == 180.0
        assert result["color_hsv"]["saturation"] == 50.0
        assert result["scene_number"] == 1
        assert result["music_mode"] == "OFF"

    def test_power_off(self):
        """Test formatting with power off."""
        result = _format_device_status({"20": False})
        assert result["power"] == "OFF"

    def test_music_mode_on(self):
        """Test formatting with music mode on."""
        result = _format_device_status({"41": True})
        assert result["music_mode"] == "ON"

    def test_none_data(self):
        """Test formatting with None data."""
        result = _format_device_status(None)
        assert result["raw"] is None
        assert result["error"] == "No data available"

    def test_empty_dict(self):
        """Test formatting with empty dict."""
        result = _format_device_status({})
        assert result["raw"] is None
        assert result["error"] == "No data available"

    def test_unknown_dps_included(self):
        """Test that unknown DPs are collected in unknown_dps."""
        dps = {"20": True, "99": "mystery_value", "100": 42}
        result = _format_device_status(dps)

        assert result["power"] == "ON"
        assert "unknown_dps" in result
        assert result["unknown_dps"]["99"] == "mystery_value"
        assert result["unknown_dps"]["100"] == 42

    def test_no_unknown_dps_when_all_known(self):
        """Test that unknown_dps is absent when all DPs are known."""
        dps = {"20": True, "21": "white", "22": 500}
        result = _format_device_status(dps)
        assert "unknown_dps" not in result

    def test_brightness_percent_calculation(self):
        """Test brightness percent calculation at boundaries."""
        # Min brightness (10) -> 0%
        result = _format_device_status({"22": 10})
        assert result["brightness"]["percent"] == 0.0

        # Max brightness (1000) -> 100%
        result = _format_device_status({"22": 1000})
        assert result["brightness"]["percent"] == 100.0

    def test_hsv_with_short_hex_no_parsed_fields(self):
        """Test HSV with a hex string that's too short to parse."""
        dps = {"24": "00b4"}
        result = _format_device_status(dps)

        assert result["color_hsv"]["raw_hex"] == "00b4"
        # Should not have parsed fields
        assert "hue" not in result["color_hsv"]
        assert "saturation" not in result["color_hsv"]

    def test_hsv_with_invalid_hex(self):
        """Test HSV with a non-hex string that would fail parsing."""
        dps = {"24": "not_a_hex_value!"}
        result = _format_device_status(dps)

        assert result["color_hsv"]["raw_hex"] == "not_a_hex_value!"
        # parse_hsv_hex may raise ValueError, which is caught
        # Check that it doesn't crash

    def test_scene_data_included(self):
        """Test that scene data (DP 25) is included."""
        dps = {"25": "000e0d0000000000000000c80000"}
        result = _format_device_status(dps)
        assert result["scene_data"] == "000e0d0000000000000000c80000"

    def test_color_temp_kelvin_warm(self):
        """Test color temp at warm end (Tuya 0 = 2700K)."""
        result = _format_device_status({"23": 0})
        assert result["color_temperature"]["kelvin"] == 2700

    def test_color_temp_kelvin_cool(self):
        """Test color temp at cool end (Tuya 1000 = 6500K)."""
        result = _format_device_status({"23": 1000})
        assert result["color_temperature"]["kelvin"] == 6500


class TestToRedactConfig:
    """Tests for the TO_REDACT_CONFIG set."""

    def test_local_key_is_redacted(self):
        assert CONF_LOCAL_KEY in TO_REDACT_CONFIG

    def test_only_local_key(self):
        """Only local_key should be redacted, not IP or device_id."""
        assert len(TO_REDACT_CONFIG) == 1


class TestAsyncGetConfigEntryDiagnostics:
    """Tests for async_get_config_entry_diagnostics."""

    @pytest.mark.asyncio
    async def test_redacts_local_key(self):
        """Test that local_key is redacted in the diagnostics output."""
        from datetime import UTC, datetime, timedelta

        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "20": True,
            "21": "white",
            "22": 500,
            "23": 500,
        }
        mock_coordinator.last_update_success = True
        mock_coordinator.update_interval = timedelta(seconds=30)
        mock_coordinator.last_update_success_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        mock_coordinator.last_exception = None

        mock_entry = MagicMock()
        mock_entry.data = {
            "device_id": "bf3a09ef3b5eddce45qwer",
            "ip_address": "192.168.1.100",
            "local_key": "abcdef1234567890",
            "protocol_version": "3.4",
        }
        mock_entry.runtime_data = mock_coordinator

        mock_hass = MagicMock()

        from custom_components.ha_ledvance_lights.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        result = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

        # local_key should be redacted
        assert result["config_entry"]["local_key"] == "**REDACTED**"
        # Other fields should be present
        assert result["config_entry"]["device_id"] == "bf3a09ef3b5eddce45qwer"
        assert result["config_entry"]["ip_address"] == "192.168.1.100"
        assert result["config_entry"]["protocol_version"] == "3.4"

    @pytest.mark.asyncio
    async def test_includes_health_info(self):
        """Test that health info is included in diagnostics."""
        from datetime import UTC, datetime, timedelta

        mock_coordinator = MagicMock()
        mock_coordinator.data = {"20": True}
        mock_coordinator.last_update_success = True
        mock_coordinator.update_interval = timedelta(seconds=30)
        mock_coordinator.last_update_success_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
        mock_coordinator.last_exception = None

        mock_entry = MagicMock()
        mock_entry.data = {
            "device_id": "test_id",
            "ip_address": "192.168.1.100",
            "local_key": "secret",
            "protocol_version": "3.4",
        }
        mock_entry.runtime_data = mock_coordinator

        from custom_components.ha_ledvance_lights.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        result = await async_get_config_entry_diagnostics(MagicMock(), mock_entry)

        assert result["health"]["last_update_success"] is True
        assert result["health"]["update_interval_seconds"] == 30.0

    @pytest.mark.asyncio
    async def test_includes_device_status(self):
        """Test that formatted device status is included."""
        from datetime import timedelta

        mock_coordinator = MagicMock()
        mock_coordinator.data = {"20": True, "21": "white", "22": 500}
        mock_coordinator.last_update_success = True
        mock_coordinator.update_interval = timedelta(seconds=30)
        mock_coordinator.last_update_success_time = None
        mock_coordinator.last_exception = None

        mock_entry = MagicMock()
        mock_entry.data = {
            "device_id": "test_id",
            "ip_address": "192.168.1.100",
            "local_key": "secret",
            "protocol_version": "3.4",
        }
        mock_entry.runtime_data = mock_coordinator

        from custom_components.ha_ledvance_lights.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        result = await async_get_config_entry_diagnostics(MagicMock(), mock_entry)

        assert result["device_status"]["power"] == "ON"
        assert result["device_status"]["mode"] == "white"
        assert "brightness" in result["device_status"]

    @pytest.mark.asyncio
    async def test_dp_summary_counts(self):
        """Test that data point summary counts known and unknown DPs."""
        from datetime import timedelta

        mock_coordinator = MagicMock()
        mock_coordinator.data = {
            "20": True,
            "21": "white",
            "22": 500,
            "99": "unknown",
        }
        mock_coordinator.last_update_success = True
        mock_coordinator.update_interval = timedelta(seconds=30)
        mock_coordinator.last_update_success_time = None
        mock_coordinator.last_exception = None

        mock_entry = MagicMock()
        mock_entry.data = {
            "device_id": "test_id",
            "ip_address": "192.168.1.100",
            "local_key": "secret",
            "protocol_version": "3.4",
        }
        mock_entry.runtime_data = mock_coordinator

        from custom_components.ha_ledvance_lights.diagnostics import (
            async_get_config_entry_diagnostics,
        )

        result = await async_get_config_entry_diagnostics(MagicMock(), mock_entry)

        assert result["data_points"]["total"] == 4
        assert result["data_points"]["known"] == 3
        assert result["data_points"]["unknown"] == 1
