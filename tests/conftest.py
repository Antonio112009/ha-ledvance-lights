"""Shared pytest fixtures for ha_ledvance_lights integration tests.

Sets up mock homeassistant modules so that the integration code can be
imported without a real Home Assistant installation.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub out homeassistant before any integration code is imported.
# This lets us import and test the integration logic without HA installed.
# ---------------------------------------------------------------------------


def _create_mock_module(name, attrs=None):
    """Create a MagicMock that behaves like a module."""
    mod = ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _setup_ha_stubs():
    """Register minimal homeassistant stubs in sys.modules."""
    if "homeassistant" in sys.modules and not isinstance(sys.modules["homeassistant"], ModuleType):
        return  # Already set up as a real module

    # --- Platform enum ---
    class Platform:
        LIGHT = "light"

    # --- ColorMode enum ---
    class ColorMode:
        COLOR_TEMP = "color_temp"
        HS = "hs"
        BRIGHTNESS = "brightness"
        ONOFF = "onoff"
        UNKNOWN = "unknown"

    # --- LightEntityFeature ---
    class LightEntityFeature:
        EFFECT = 4
        FLASH = 8
        TRANSITION = 32

    # --- LightEntity ---
    class LightEntity:
        def __init__(self, *args, **kwargs):
            pass

    # --- CoordinatorEntity ---
    class CoordinatorEntity:
        def __init__(self, *args, **kwargs):
            pass

        def __class_getitem__(cls, item):
            return cls

    # --- ConfigEntry ---
    class ConfigEntry:
        def __init__(self):
            self.data = {}
            self.title = ""
            self.entry_id = ""
            self.runtime_data = None

        def __class_getitem__(cls, item):
            return cls

    # --- ConfigFlow ---
    class ConfigFlow:
        domain = ""

        def __init__(self, *args, **kwargs):
            pass

        def __init_subclass__(cls, domain=None, **kwargs):
            if domain:
                cls.domain = domain

    # --- DataUpdateCoordinator ---
    class DataUpdateCoordinator:
        def __init__(
            self,
            hass=None,
            logger=None,
            *,
            name="",
            update_interval=None,
            config_entry=None,
        ):
            self.hass = hass
            self.name = name
            self.update_interval = update_interval
            self.config_entry = config_entry
            self.data = None
            self.last_update_success = True
            self.last_update_success_time = None

        async def async_config_entry_first_refresh(self):
            pass

        async def async_request_refresh(self):
            pass

        def __class_getitem__(cls, item):
            return cls

    class UpdateFailedError(Exception):
        pass

    # --- DeviceInfo ---
    class DeviceInfo(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(**kwargs)

    # --- async_redact_data ---
    def async_redact_data(data, to_redact):
        """Simple redaction implementation for testing."""
        result = dict(data)
        for key in to_redact:
            if key in result:
                result[key] = "**REDACTED**"
        return result

    # ATTR constants (stored in a dict to avoid N806 lint warnings)
    attr_constants = {
        "ATTR_BRIGHTNESS": "brightness",
        "ATTR_COLOR_TEMP_KELVIN": "color_temp_kelvin",
        "ATTR_EFFECT": "effect",
        "ATTR_HS_COLOR": "hs_color",
    }

    # --- HomeAssistant ---
    class HomeAssistant:
        pass

    # Register all the stub modules
    _create_mock_module("homeassistant")
    _create_mock_module("homeassistant.core", {"HomeAssistant": HomeAssistant})
    _create_mock_module("homeassistant.const", {"Platform": Platform})
    _create_mock_module(
        "homeassistant.config_entries",
        {
            "ConfigEntry": ConfigEntry,
            "ConfigFlow": ConfigFlow,
            "ConfigFlowResult": dict,
        },
    )
    _create_mock_module(
        "homeassistant.helpers",
    )
    _create_mock_module(
        "homeassistant.helpers.update_coordinator",
        {
            "DataUpdateCoordinator": DataUpdateCoordinator,
            "UpdateFailed": UpdateFailedError,
            "CoordinatorEntity": CoordinatorEntity,
        },
    )
    _create_mock_module(
        "homeassistant.helpers.device_registry",
        {"DeviceInfo": DeviceInfo},
    )
    _create_mock_module(
        "homeassistant.helpers.entity_platform",
        {"AddEntitiesCallback": type("AddEntitiesCallback", (), {})},
    )
    _create_mock_module("homeassistant.components", {})
    _create_mock_module(
        "homeassistant.components.light",
        {
            **attr_constants,
            "ColorMode": ColorMode,
            "LightEntity": LightEntity,
            "LightEntityFeature": LightEntityFeature,
        },
    )
    _create_mock_module(
        "homeassistant.components.diagnostics",
        {
            "async_redact_data": async_redact_data,
        },
    )

    # voluptuous stub (needed by config_flow)
    if "voluptuous" not in sys.modules:
        vol = _create_mock_module("voluptuous")

        class _Schema:
            def __init__(self, schema=None):
                self.schema = schema

        class _Required:
            def __init__(self, key, default=None):
                self.key = key
                self.default = default

        class _Optional:
            def __init__(self, key, default=None):
                self.key = key
                self.default = default

        class _In:
            def __init__(self, options):
                self.options = options

        vol.Schema = _Schema
        vol.Required = _Required
        vol.Optional = _Optional
        vol.In = _In


# Run the stub setup before any test collection
_setup_ha_stubs()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_entry_data():
    """Return typical config entry data."""
    return {
        "device_id": "bf3a09ef3b5eddce45qwer",
        "ip_address": "192.168.1.100",
        "local_key": "abcdef1234567890",
        "protocol_version": "3.4",
    }


@pytest.fixture
def mock_config_entry(mock_entry_data):
    """Create a mock ConfigEntry-like object."""
    entry = MagicMock()
    entry.data = mock_entry_data
    entry.title = "Ledvance Light qwer"
    entry.entry_id = "test_entry_id"
    entry.runtime_data = None
    return entry


@pytest.fixture
def mock_tuya_device():
    """Create a mock TuyaDevice."""
    device = MagicMock()
    device.status.return_value = {
        "dps": {
            "20": True,
            "21": "white",
            "22": 500,
            "23": 500,
            "24": "00b401f40320",
            "26": 1,
        }
    }
    device.set_status = MagicMock()
    device.set_multiple_values = MagicMock()
    device._close = MagicMock()
    return device


@pytest.fixture
def sample_dps():
    """Return a typical DPS dict from a Ledvance light."""
    return {
        "20": True,
        "21": "white",
        "22": 500,
        "23": 500,
        "24": "00b401f40320",
        "25": "000e0d0000000000000000c80000",
        "26": 1,
        "41": False,
    }


@pytest.fixture
def sample_dps_colour():
    """Return a DPS dict with colour mode active."""
    return {
        "20": True,
        "21": "colour",
        "22": 800,
        "23": 0,
        "24": "007803e803e8",
        "26": 1,
    }


@pytest.fixture
def sample_dps_scene():
    """Return a DPS dict with scene mode active."""
    return {
        "20": True,
        "21": "scene",
        "22": 500,
        "23": 500,
        "24": "000003e803e8",
        "26": 2,
    }
