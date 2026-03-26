"""Config flow for Ledvance Smart+ WiFi."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import tinytuya
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

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
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
        device = tinytuya.BulbDevice(
            dev_id=data[CONF_DEVICE_ID],
            address=data[CONF_IP_ADDRESS],
            local_key=data[CONF_LOCAL_KEY],
        )
        device.set_version(float(version))
        device.set_socketTimeout(5)
        device.set_socketRetryLimit(1)

        result = device.status()

        if result and "dps" in result:
            return ConnectionResult(
                success=True,
                version=version,
                dps=result["dps"],
            )

        # Check error code
        err_code = result.get("Err", "") if result else ""

        if err_code in (ERR_CONNECT, ERR_OFFLINE):
            # No device at this IP — no point trying other versions
            return ConnectionResult(
                success=False,
                error="device_not_found",
            )

        if err_code in (ERR_PAYLOAD, ERR_KEY_OR_VER):
            # Wrong key or version — try next version
            last_error = "invalid_key"
            continue

        # Unknown error
        last_error = "cannot_connect"

    # All versions failed
    return ConnectionResult(success=False, error=last_error or "cannot_connect")


class LedvanceWifiConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Ledvance Smart+ WiFi."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured()

            try:
                result = await self.hass.async_add_executor_job(
                    _test_connection, user_input
                )
            except Exception:
                _LOGGER.exception("Unexpected error connecting to Ledvance device")
                errors["base"] = "cannot_connect"
            else:
                if result.success:
                    # Auto-generate device name
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
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
