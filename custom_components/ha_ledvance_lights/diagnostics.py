"""Diagnostics support for Ledvance Lights."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DEVICE_ID,
    CONF_IP_ADDRESS,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    DP_BRIGHTNESS,
    DP_COLOR_HSV,
    DP_COLOR_TEMP,
    DP_MODE,
    DP_MUSIC,
    DP_POWER,
    DP_SCENE,
    DP_SCENE_NUM,
    VERSION,
    parse_hsv_hex,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)
from .coordinator import LedvanceDataUpdateCoordinator

# Keys to redact from diagnostics output
TO_REDACT_CONFIG = {CONF_LOCAL_KEY}

# Human-readable DP names
DP_NAMES = {
    str(DP_POWER): "power",
    str(DP_MODE): "mode",
    str(DP_BRIGHTNESS): "brightness",
    str(DP_COLOR_TEMP): "color_temp",
    str(DP_COLOR_HSV): "color_hsv",
    str(DP_SCENE): "scene_data",
    str(DP_SCENE_NUM): "scene_number",
    str(DP_MUSIC): "music_mode",
}


def _format_device_status(dps: dict[str, Any] | None) -> dict[str, Any]:
    """Format raw DPS into human-readable status."""
    if not dps:
        return {"raw": None, "error": "No data available"}

    formatted: dict[str, Any] = {}

    # Power
    power = dps.get(str(DP_POWER))
    if power is not None:
        formatted["power"] = "ON" if power else "OFF"

    # Mode
    mode = dps.get(str(DP_MODE))
    if mode is not None:
        formatted["mode"] = mode

    # Brightness
    brightness = dps.get(str(DP_BRIGHTNESS))
    if brightness is not None:
        formatted["brightness"] = {
            "tuya_value": brightness,
            "ha_value": tuya_brightness_to_ha(brightness),
            "percent": round((brightness - 10) / (1000 - 10) * 100, 1),
        }

    # Color temperature
    color_temp = dps.get(str(DP_COLOR_TEMP))
    if color_temp is not None:
        formatted["color_temperature"] = {
            "tuya_value": color_temp,
            "kelvin": tuya_ct_to_kelvin(color_temp),
        }

    # Color HSV
    color_hsv = dps.get(str(DP_COLOR_HSV))
    if color_hsv is not None:
        hsv_info: dict[str, Any] = {"raw_hex": color_hsv}
        if isinstance(color_hsv, str) and len(color_hsv) >= 12:
            try:
                h, s = parse_hsv_hex(color_hsv)
                v_raw = int(color_hsv[8:12], 16)
                hsv_info["hue"] = h
                hsv_info["saturation"] = s
                hsv_info["value_raw"] = v_raw
                hsv_info["value_percent"] = round(v_raw / 10, 1)
            except ValueError:
                pass
        formatted["color_hsv"] = hsv_info

    # Scene
    scene_num = dps.get(str(DP_SCENE_NUM))
    if scene_num is not None:
        formatted["scene_number"] = scene_num

    scene_data = dps.get(str(DP_SCENE))
    if scene_data is not None:
        formatted["scene_data"] = scene_data

    # Music mode
    music = dps.get(str(DP_MUSIC))
    if music is not None:
        formatted["music_mode"] = "ON" if music else "OFF"

    # Include any unknown DPs
    known_dps = {
        str(dp)
        for dp in (
            DP_POWER,
            DP_MODE,
            DP_BRIGHTNESS,
            DP_COLOR_TEMP,
            DP_COLOR_HSV,
            DP_SCENE,
            DP_SCENE_NUM,
            DP_MUSIC,
        )
    }
    unknown = {k: v for k, v in dps.items() if k not in known_dps}
    if unknown:
        formatted["unknown_dps"] = unknown

    return formatted


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: LedvanceDataUpdateCoordinator = entry.runtime_data

    # Connection health
    health: dict[str, Any] = {
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
    }

    if coordinator.last_update_success_time:
        health["last_successful_update"] = coordinator.last_update_success_time.isoformat()
    if hasattr(coordinator, "last_exception") and coordinator.last_exception:
        health["last_error"] = str(coordinator.last_exception)

    # Adaptive polling state
    health["fast_polling"] = coordinator._device_unavailable
    if coordinator._device_unavailable and coordinator._fast_poll_start is not None:
        import time

        health["fast_poll_elapsed_seconds"] = round(
            time.monotonic() - coordinator._fast_poll_start, 1
        )

    # Count known vs unknown DPs
    dp_summary: dict[str, Any] = {}
    if coordinator.data:
        known_dp_keys = {
            str(dp)
            for dp in (
                DP_POWER,
                DP_MODE,
                DP_BRIGHTNESS,
                DP_COLOR_TEMP,
                DP_COLOR_HSV,
                DP_SCENE,
                DP_SCENE_NUM,
                DP_MUSIC,
            )
        }
        all_keys = set(coordinator.data.keys())
        dp_summary = {
            "total": len(all_keys),
            "known": len(all_keys & known_dp_keys),
            "unknown": len(all_keys - known_dp_keys),
            "dp_map": {k: DP_NAMES.get(k, f"unknown_dp_{k}") for k in sorted(all_keys)},
        }

    return {
        "integration_version": VERSION,
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT_CONFIG),
        "connection": {
            "ip_address": entry.data.get(CONF_IP_ADDRESS),
            "device_id": entry.data.get(CONF_DEVICE_ID),
            "protocol_version": entry.data.get(CONF_PROTOCOL_VERSION),
        },
        "health": health,
        "data_points": dp_summary,
        "device_status": _format_device_status(coordinator.data),
        "raw_dps": coordinator.data,
    }
