"""Config flow for Ledvance Lights."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DOMAIN,
    ERR_CONNECT,
    ERR_KEY_OR_VER,
    ERR_OFFLINE,
    ERR_PAYLOAD,
)
from .tuya import TuyaDevice, scan_devices

_LOGGER = logging.getLogger(__name__)

STEP_MANUAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_IP_ADDRESS): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
    }
)

# Protocol versions to try (newest first)
PROTOCOL_VERSIONS = ["3.5", "3.4", "3.3"]


@dataclass
class ConnectionResult:
    """Result of a connection test."""

    success: bool
    version: str | None = None
    dps: dict | None = None
    error: str | None = None


def _test_connection(data: dict[str, Any]) -> ConnectionResult:
    """Test connection, auto-detect protocol version, return DPS on success."""
    last_error: str | None = None

    for version in PROTOCOL_VERSIONS:
        device = TuyaDevice(
            dev_id=data[CONF_DEVICE_ID],
            address=data[CONF_IP_ADDRESS],
            local_key=data[CONF_LOCAL_KEY],
            version=version,
        )
        device.set_socketTimeout(5)
        device.set_socketRetryLimit(1)

        result = device.status()

        if result and "dps" in result:
            return ConnectionResult(
                success=True,
                version=version,
                dps=result["dps"],
            )

        err_code = result.get("Err", "") if result else ""

        if err_code in (ERR_CONNECT, ERR_OFFLINE):
            return ConnectionResult(success=False, error="device_not_found")

        if err_code in (ERR_PAYLOAD, ERR_KEY_OR_VER):
            last_error = "invalid_key"
            continue

        last_error = "cannot_connect"

    return ConnectionResult(success=False, error=last_error or "cannot_connect")


class LedvanceWifiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ledvance Lights."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: list[dict] = []
        self._selected_device: dict | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Initial step — choose scan (with optional network) or manual."""
        if user_input is not None:
            action = user_input.get("action", "manual")
            if action == "scan":
                # Store network for the scan step
                self._scan_network = user_input.get("network", "").strip() or None
                return await self.async_step_scan()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="scan"): vol.In(
                        {
                            "scan": "Scan network for devices",
                            "manual": "Enter device details manually",
                        }
                    ),
                    vol.Optional("network"): str,
                }
            ),
        )

    async def async_step_scan(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Scan the network for Tuya devices."""
        if user_input is not None:
            # User selected a device from the scan results
            selected_id = user_input.get("device")
            if selected_id:
                self._selected_device = next(
                    (
                        d
                        for d in self._discovered_devices
                        if d["id"] == selected_id or f"tcp_{d['ip']}" == selected_id
                    ),
                    None,
                )
                if self._selected_device:
                    return await self.async_step_credentials()

        # Run the scan
        try:
            network = getattr(self, "_scan_network", None)
            self._discovered_devices = await self.hass.async_add_executor_job(
                scan_devices, 10.0, network
            )
        except Exception:
            _LOGGER.exception("Error scanning for devices")
            self._discovered_devices = []

        if not self._discovered_devices:
            # No devices found — go straight to manual entry
            return await self.async_step_manual(_show_scan_failed=True)

        # Build device selection list
        device_options = {}
        for d in self._discovered_devices:
            discovered_via = d.get("discovered_via", "udp")
            if discovered_via == "tcp_probe":
                # TCP probe: no device ID, show IP only
                key = f"tcp_{d['ip']}"
                label = f"{d['ip']} (found via network scan)"
            else:
                # UDP broadcast: has device ID and version
                key = d["id"]
                label = f"{d['ip']} (v{d['version']}) — {d['id'][-8:]}"
            device_options[key] = label

        return self.async_show_form(
            step_id="scan",
            data_schema=vol.Schema({vol.Required("device"): vol.In(device_options)}),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter credentials for the selected device."""
        errors: dict[str, str] = {}
        dev = self._selected_device or {}
        ip = dev.get("ip", "unknown")
        dev_id = dev.get("id", "")
        is_tcp_probe = dev.get("discovered_via") == "tcp_probe"

        # TCP probe devices need both device_id and local_key
        # UDP discovered devices only need local_key
        if is_tcp_probe:
            schema = vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): str,
                    vol.Required(CONF_LOCAL_KEY): str,
                }
            )
        else:
            schema = vol.Schema({vol.Required(CONF_LOCAL_KEY): str})

        if user_input is not None:
            connection_data = {
                CONF_IP_ADDRESS: ip,
                CONF_DEVICE_ID: user_input.get(CONF_DEVICE_ID, dev_id),
                CONF_LOCAL_KEY: user_input[CONF_LOCAL_KEY],
            }

            await self.async_set_unique_id(connection_data[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            try:
                result = await self.hass.async_add_executor_job(_test_connection, connection_data)
            except Exception:
                _LOGGER.exception("Unexpected error connecting to device")
                errors["base"] = "cannot_connect"
            else:
                if result.success:
                    device_id = connection_data[CONF_DEVICE_ID]
                    device_name = f"Ledvance Light {device_id[-4:]}"

                    return self.async_create_entry(
                        title=device_name,
                        data={
                            **connection_data,
                            CONF_PROTOCOL_VERSION: result.version,
                        },
                    )
                errors["base"] = result.error or "cannot_connect"

        return self.async_show_form(
            step_id="credentials",
            data_schema=schema,
            errors=errors,
            description_placeholders={"ip": ip, "device_id": dev_id or "unknown"},
        )

    async def async_step_manual(
        self,
        user_input: dict[str, Any] | None = None,
        _show_scan_failed: bool = False,
    ) -> ConfigFlowResult:
        """Manual device entry."""
        errors: dict[str, str] = {}

        if _show_scan_failed:
            errors["base"] = "no_devices_found"

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            try:
                result = await self.hass.async_add_executor_job(_test_connection, user_input)
            except Exception:
                _LOGGER.exception("Unexpected error connecting to Ledvance device")
                errors["base"] = "cannot_connect"
            else:
                if result.success:
                    device_id = user_input[CONF_DEVICE_ID]
                    device_name = f"Ledvance Light {device_id[-4:]}"

                    return self.async_create_entry(
                        title=device_name,
                        data={
                            **user_input,
                            CONF_PROTOCOL_VERSION: result.version,
                        },
                    )
                errors["base"] = result.error or "cannot_connect"

        return self.async_show_form(
            step_id="manual",
            data_schema=STEP_MANUAL_SCHEMA,
            errors=errors,
        )
