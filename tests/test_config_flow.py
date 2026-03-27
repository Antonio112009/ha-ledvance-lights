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

    def _make_flow(self, configured_entries=None):
        """Create a LedvanceWifiConfigFlow with mocked HA internals."""
        from custom_components.ha_ledvance_lights.config_flow import (
            LedvanceWifiConfigFlow,
        )

        flow = LedvanceWifiConfigFlow()
        flow.hass = MagicMock()
        flow.context = {}
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_set_unique_id = AsyncMock(return_value=None)
        flow._abort_if_unique_id_configured = MagicMock()
        flow._async_current_entries = MagicMock(return_value=configured_entries or [])
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

    @pytest.mark.asyncio
    async def test_scan_filters_already_configured_by_id(self):
        """Test that already-configured devices are filtered from scan results."""
        configured_entry = MagicMock()
        configured_entry.data = {
            "device_id": "device123456",
            "ip_address": "192.168.1.50",
        }

        flow = self._make_flow(configured_entries=[configured_entry])
        flow._scan_network = None

        devices = [
            {"id": "device123456", "ip": "192.168.1.50", "version": "3.4"},
            {"id": "device789012", "ip": "192.168.1.51", "version": "3.3"},
        ]
        flow.hass.async_add_executor_job = AsyncMock(return_value=devices)

        await flow.async_step_scan(user_input=None)

        # Only the unconfigured device should remain
        assert len(flow._discovered_devices) == 1
        assert flow._discovered_devices[0]["id"] == "device789012"

    @pytest.mark.asyncio
    async def test_scan_all_configured_shows_message(self):
        """Test that scan with all devices configured shows appropriate message."""
        configured_entry = MagicMock()
        configured_entry.data = {
            "device_id": "device123456",
            "ip_address": "192.168.1.50",
        }

        flow = self._make_flow(configured_entries=[configured_entry])
        flow._scan_network = None
        flow.async_step_manual = AsyncMock(return_value={"type": "form"})

        devices = [
            {"id": "device123456", "ip": "192.168.1.50", "version": "3.4"},
        ]
        flow.hass.async_add_executor_job = AsyncMock(return_value=devices)

        await flow.async_step_scan(user_input=None)

        flow.async_step_manual.assert_awaited_once_with(
            _show_scan_failed=True, _all_configured=True
        )

    @pytest.mark.asyncio
    async def test_scan_filters_by_ip(self):
        """Test that devices with a configured IP are filtered even if ID differs."""
        configured_entry = MagicMock()
        configured_entry.data = {
            "device_id": "some_other_id",
            "ip_address": "192.168.1.50",
        }

        flow = self._make_flow(configured_entries=[configured_entry])
        flow._scan_network = None

        devices = [
            {"id": "device_new", "ip": "192.168.1.50", "version": "3.4"},
            {"id": "device_other", "ip": "192.168.1.51", "version": "3.3"},
        ]
        flow.hass.async_add_executor_job = AsyncMock(return_value=devices)

        await flow.async_step_scan(user_input=None)

        assert len(flow._discovered_devices) == 1
        assert flow._discovered_devices[0]["id"] == "device_other"

    @pytest.mark.asyncio
    async def test_discovery_step_shows_credentials(self):
        """Test that discovery step goes straight to credentials."""
        flow = self._make_flow()

        discovery_data = {
            "ip_address": "192.168.1.50",
            "device_id": "device123456",
            "version": "3.4",
        }

        await flow.async_step_discovery(discovery_data)

        assert flow._selected_device is not None
        assert flow._selected_device["id"] == "device123456"
        assert flow._selected_device["ip"] == "192.168.1.50"
        # Should show the credentials form
        flow.async_show_form.assert_called_once()
        call_kwargs = flow.async_show_form.call_args
        assert call_kwargs.kwargs.get("step_id") == "credentials"

    @pytest.mark.asyncio
    async def test_discovery_step_aborts_if_configured(self):
        """Test that discovery step aborts for an already-configured device."""
        flow = self._make_flow()
        flow.async_set_unique_id = AsyncMock(return_value=None)
        flow._abort_if_unique_id_configured = MagicMock(
            side_effect=Exception("already_configured"),
        )

        discovery_data = {
            "ip_address": "192.168.1.50",
            "device_id": "device123456",
            "version": "3.4",
        }

        with pytest.raises(Exception, match="already_configured"):
            await flow.async_step_discovery(discovery_data)

    def test_fire_discovery_for_remaining(self):
        """Test that discovery flows are fired for remaining unconfigured devices."""
        flow = self._make_flow()
        flow.hass.async_create_task = MagicMock()

        # Simulate two remaining unconfigured devices
        flow._discovered_devices = [
            {"id": "device_aaa", "ip": "192.168.1.50", "version": "3.4"},
            {"id": "device_bbb", "ip": "192.168.1.51", "version": "3.3"},
        ]

        flow._fire_discovery_for_remaining()

        # Should fire two discovery tasks
        assert flow.hass.async_create_task.call_count == 2

    def test_fire_discovery_skips_configured(self):
        """Test that already-configured devices are not re-discovered."""
        configured_entry = MagicMock()
        configured_entry.data = {
            "device_id": "device_aaa",
            "ip_address": "192.168.1.50",
        }

        flow = self._make_flow(configured_entries=[configured_entry])
        flow.hass.async_create_task = MagicMock()

        flow._discovered_devices = [
            {"id": "device_aaa", "ip": "192.168.1.50", "version": "3.4"},
            {"id": "device_bbb", "ip": "192.168.1.51", "version": "3.3"},
        ]

        flow._fire_discovery_for_remaining()

        # Only device_bbb should get a discovery flow
        assert flow.hass.async_create_task.call_count == 1

    def test_fire_discovery_empty_list(self):
        """Test that no discovery flows are fired when no devices remain."""
        flow = self._make_flow()
        flow.hass.async_create_task = MagicMock()
        flow._discovered_devices = []

        flow._fire_discovery_for_remaining()

        flow.hass.async_create_task.assert_not_called()

    def test_fire_discovery_skips_devices_without_id(self):
        """Test that TCP-probed devices without an ID are skipped."""
        flow = self._make_flow()
        flow.hass.async_create_task = MagicMock()

        flow._discovered_devices = [
            {"id": "", "ip": "192.168.1.50", "version": "3.4", "discovered_via": "tcp_probe"},
            {"id": "device_bbb", "ip": "192.168.1.51", "version": "3.3"},
        ]

        flow._fire_discovery_for_remaining()

        # Only device_bbb should get a discovery flow (empty ID is skipped)
        assert flow.hass.async_create_task.call_count == 1
