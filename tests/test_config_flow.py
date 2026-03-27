"""Tests for the Ledvance Lights config flow.

Tests focus on the pure _test_connection function and ConnectionResult logic,
avoiding the need for a real Home Assistant runtime.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.ha_ledvance_lights.config_flow import (
    PROTOCOL_VERSIONS,
    ConnectionResult,
    _test_connection,
)


class TestConnectionResult:
    """Tests for the ConnectionResult dataclass."""

    def test_success_result(self):
        result = ConnectionResult(success=True, version="3.4", dps={"20": True})
        assert result.success is True
        assert result.version == "3.4"
        assert result.dps == {"20": True}
        assert result.error is None

    def test_failure_result(self):
        result = ConnectionResult(success=False, error="device_not_found")
        assert result.success is False
        assert result.version is None
        assert result.dps is None
        assert result.error == "device_not_found"


class TestTestConnection:
    """Tests for the _test_connection function."""

    def _make_data(self):
        return {
            "ip_address": "192.168.1.100",
            "device_id": "bf3a09ef3b5eddce45qwer",
            "local_key": "abcdef1234567890",
        }

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_success_with_detected_version(self, mock_device_cls, mock_detect):
        """Test successful connection when detect_version returns a version."""
        mock_detect.return_value = "3.4"
        mock_device = MagicMock()
        mock_device.status.return_value = {"dps": {"20": True, "21": "white"}}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is True
        assert result.version == "3.4"
        assert result.dps == {"20": True, "21": "white"}
        mock_device_cls.assert_called_once_with(
            dev_id="bf3a09ef3b5eddce45qwer",
            address="192.168.1.100",
            local_key="abcdef1234567890",
            version="3.4",
        )

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_success_without_detected_version(self, mock_device_cls, mock_detect):
        """Test successful connection when detect_version returns None."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"dps": {"20": True}}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is True
        assert result.version == PROTOCOL_VERSIONS[0]

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_device_not_found_err_connect(self, mock_device_cls, mock_detect):
        """Test device_not_found when ERR_CONNECT is returned."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"Err": "901"}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "device_not_found"

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_device_not_found_err_offline(self, mock_device_cls, mock_detect):
        """Test device_not_found when ERR_OFFLINE is returned."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"Err": "905"}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "device_not_found"

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_invalid_key_all_versions_fail(self, mock_device_cls, mock_detect):
        """Test invalid_key when all versions return ERR_PAYLOAD/ERR_KEY_OR_VER."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"Err": "904"}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "invalid_key"
        assert mock_device_cls.call_count == len(PROTOCOL_VERSIONS)

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_invalid_key_err_914(self, mock_device_cls, mock_detect):
        """Test invalid_key when ERR_KEY_OR_VER (914) is returned."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"Err": "914"}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "invalid_key"

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_cannot_connect_unknown_error(self, mock_device_cls, mock_detect):
        """Test cannot_connect when status returns an unknown error."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"Err": "999"}
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "cannot_connect"

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_cannot_connect_none_result(self, mock_device_cls, mock_detect):
        """Test cannot_connect when status returns None."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = None
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is False
        assert result.error == "cannot_connect"

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_fallback_to_later_version(self, mock_device_cls, mock_detect):
        """Test that a later version succeeds after earlier ones fail."""
        mock_detect.return_value = None

        call_count = 0

        def side_effect():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"Err": "904"}
            return {"dps": {"20": True}}

        mock_device = MagicMock()
        mock_device.status.side_effect = side_effect
        mock_device_cls.return_value = mock_device

        result = _test_connection(self._make_data())

        assert result.success is True
        assert result.version == PROTOCOL_VERSIONS[2]

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_detected_version_tried_first(self, mock_device_cls, mock_detect):
        """Test that the detected version is tried first."""
        mock_detect.return_value = "3.3"

        versions_tried = []

        def capture_version(**kwargs):
            versions_tried.append(kwargs.get("version"))
            device = MagicMock()
            device.status.return_value = {"Err": "904"}
            return device

        mock_device_cls.side_effect = capture_version

        _test_connection(self._make_data())

        assert versions_tried[0] == "3.3"
        assert versions_tried.count("3.3") == 1

    @patch("custom_components.ha_ledvance_lights.config_flow.detect_version")
    @patch("custom_components.ha_ledvance_lights.config_flow.TuyaDevice")
    def test_socket_timeout_set(self, mock_device_cls, mock_detect):
        """Test that socket timeout and retry limit are configured."""
        mock_detect.return_value = None
        mock_device = MagicMock()
        mock_device.status.return_value = {"dps": {"20": True}}
        mock_device_cls.return_value = mock_device

        _test_connection(self._make_data())

        mock_device.set_socketTimeout.assert_called_with(5)
        mock_device.set_socketRetryLimit.assert_called_with(1)


class TestConfigFlowSteps:
    """Tests for the config flow step methods (mocked HA framework)."""

    def _make_flow(self):
        """Create a LedvanceWifiConfigFlow with mocked HA internals."""
        from custom_components.ha_ledvance_lights.config_flow import (
            LedvanceWifiConfigFlow,
        )

        flow = LedvanceWifiConfigFlow()
        flow.hass = MagicMock()
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_set_unique_id = AsyncMock(return_value=None)
        flow._abort_if_unique_id_configured = MagicMock()
        return flow

    @pytest.mark.asyncio
    async def test_user_step_shows_form(self):
        """Test that the user step shows a form when no input is provided."""
        flow = self._make_flow()
        await flow.async_step_user(user_input=None)

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        assert call_kwargs.kwargs.get("step_id") == "user"

    @pytest.mark.asyncio
    async def test_user_step_manual_action(self):
        """Test that user step with 'manual' action goes to manual step."""
        flow = self._make_flow()
        flow.async_step_manual = AsyncMock(return_value={"type": "form", "step_id": "manual"})

        await flow.async_step_user(user_input={"action": "manual"})

        flow.async_step_manual.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_user_step_scan_action(self):
        """Test that user step with 'scan' action goes to scan step."""
        flow = self._make_flow()
        flow.async_step_scan = AsyncMock(return_value={"type": "form", "step_id": "scan"})

        await flow.async_step_user(user_input={"action": "scan"})

        flow.async_step_scan.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_step_shows_form(self):
        """Test that the manual step shows a form when no input is provided."""
        flow = self._make_flow()

        await flow.async_step_manual(user_input=None)

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        assert call_kwargs.kwargs.get("step_id") == "manual"

    @pytest.mark.asyncio
    async def test_manual_step_scan_failed_shows_error(self):
        """Test that manual step shows no_devices_found when coming from failed scan."""
        flow = self._make_flow()

        await flow.async_step_manual(user_input=None, _show_scan_failed=True)

        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors", {})
        assert errors.get("base") == "no_devices_found"

    @pytest.mark.asyncio
    async def test_manual_step_success_creates_entry(self):
        """Test that manual step creates entry on successful connection."""
        flow = self._make_flow()

        user_input = {
            "ip_address": "192.168.1.100",
            "device_id": "bf3a09ef3b5eddce45qwer",
            "local_key": "abcdef1234567890",
        }

        success_result = ConnectionResult(success=True, version="3.4", dps={"20": True})
        flow.hass.async_add_executor_job = AsyncMock(return_value=success_result)

        await flow.async_step_manual(user_input=user_input)

        flow.async_create_entry.assert_called_once()
        call_kwargs = flow.async_create_entry.call_args
        data = call_kwargs.kwargs.get("data")
        assert data["protocol_version"] == "3.4"
        assert data["device_id"] == "bf3a09ef3b5eddce45qwer"

    @pytest.mark.asyncio
    async def test_manual_step_device_not_found_shows_error(self):
        """Test that manual step shows error on device_not_found."""
        flow = self._make_flow()

        user_input = {
            "ip_address": "192.168.1.100",
            "device_id": "bf3a09ef3b5eddce45qwer",
            "local_key": "abcdef1234567890",
        }

        fail_result = ConnectionResult(success=False, error="device_not_found")
        flow.hass.async_add_executor_job = AsyncMock(return_value=fail_result)

        await flow.async_step_manual(user_input=user_input)

        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors", {})
        assert errors.get("base") == "device_not_found"

    @pytest.mark.asyncio
    async def test_manual_step_invalid_key_shows_error(self):
        """Test that manual step shows error on invalid_key."""
        flow = self._make_flow()

        user_input = {
            "ip_address": "192.168.1.100",
            "device_id": "bf3a09ef3b5eddce45qwer",
            "local_key": "wrong_key_here1234",
        }

        fail_result = ConnectionResult(success=False, error="invalid_key")
        flow.hass.async_add_executor_job = AsyncMock(return_value=fail_result)

        await flow.async_step_manual(user_input=user_input)

        call_kwargs = flow.async_show_form.call_args
        errors = call_kwargs.kwargs.get("errors", {})
        assert errors.get("base") == "invalid_key"

    @pytest.mark.asyncio
    async def test_scan_step_no_devices_falls_back_to_manual(self):
        """Test that scan step falls back to manual when no devices found."""
        flow = self._make_flow()
        flow._scan_network = None
        flow.hass.async_add_executor_job = AsyncMock(return_value=[])
        flow.async_step_manual = AsyncMock(return_value={"type": "form"})

        await flow.async_step_scan(user_input=None)

        flow.async_step_manual.assert_awaited_once_with(_show_scan_failed=True)

    @pytest.mark.asyncio
    async def test_scan_step_exception_falls_back_to_manual(self):
        """Test that scan step falls back to manual on scan exception."""
        flow = self._make_flow()
        flow._scan_network = None
        flow.hass.async_add_executor_job = AsyncMock(side_effect=RuntimeError("scan failed"))
        flow.async_step_manual = AsyncMock(return_value={"type": "form"})

        await flow.async_step_scan(user_input=None)

        flow.async_step_manual.assert_awaited_once_with(_show_scan_failed=True)

    @pytest.mark.asyncio
    async def test_scan_step_with_devices_shows_selection(self):
        """Test that scan step shows device selection when devices are found."""
        flow = self._make_flow()
        flow._scan_network = None

        devices = [
            {"id": "device123456", "ip": "192.168.1.50", "version": "3.4"},
            {"id": "device789012", "ip": "192.168.1.51", "version": "3.3"},
        ]
        flow.hass.async_add_executor_job = AsyncMock(return_value=devices)

        await flow.async_step_scan(user_input=None)

        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        assert call_kwargs.kwargs.get("step_id") == "scan"
        assert flow._discovered_devices == devices
