"""Constants for the Ledvance Lights integration."""

from homeassistant.const import Platform

VERSION = "1.2.2"

DOMAIN = "ha_ledvance_lights"

PLATFORMS: list[Platform] = [Platform.LIGHT]

# Config entry keys
CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_IP_ADDRESS = "ip_address"
CONF_PROTOCOL_VERSION = "protocol_version"  # auto-detected, stored in entry data

# TinyTuya error codes
ERR_CONNECT = "901"
ERR_OFFLINE = "905"
ERR_PAYLOAD = "904"
ERR_KEY_OR_VER = "914"

# Polling interval (seconds)
DEFAULT_POLLING_INTERVAL = 30

# Tuya DP mappings for Ledvance Lights (Type B)
DP_POWER = 20
DP_MODE = 21
DP_BRIGHTNESS = 22
DP_COLOR_TEMP = 23
DP_COLOR_HSV = 24
DP_SCENE = 25
DP_SCENE_NUM = 26
DP_MUSIC = 41

# Tuya brightness range
TUYA_BRIGHTNESS_MIN = 10
TUYA_BRIGHTNESS_MAX = 1000

# Tuya color temperature range
TUYA_CT_MIN = 0
TUYA_CT_MAX = 1000

# Kelvin range
KELVIN_WARM = 2700
KELVIN_COOL = 6500

# Scene effects
SCENE_EFFECTS = ["Scene 1", "Scene 2", "Scene 3", "Scene 4"]


# --- Conversion helpers ---


def tuya_brightness_to_ha(value: int) -> int:
    """Convert Tuya brightness (10-1000) to HA brightness (0-255)."""
    return int((value - TUYA_BRIGHTNESS_MIN) / (TUYA_BRIGHTNESS_MAX - TUYA_BRIGHTNESS_MIN) * 255)


def ha_brightness_to_tuya(value: int) -> int:
    """Convert HA brightness (0-255) to Tuya brightness (10-1000)."""
    return int(TUYA_BRIGHTNESS_MIN + (value / 255) * (TUYA_BRIGHTNESS_MAX - TUYA_BRIGHTNESS_MIN))


def tuya_ct_to_kelvin(value: int) -> int:
    """Convert Tuya color temp (0-1000) to Kelvin (2700-6500)."""
    return int(KELVIN_WARM + (value / TUYA_CT_MAX) * (KELVIN_COOL - KELVIN_WARM))


def kelvin_to_tuya_ct(kelvin: int) -> int:
    """Convert Kelvin (2700-6500) to Tuya color temp (0-1000)."""
    kelvin = max(KELVIN_WARM, min(KELVIN_COOL, kelvin))
    return int((kelvin - KELVIN_WARM) / (KELVIN_COOL - KELVIN_WARM) * TUYA_CT_MAX)


def parse_hsv_hex(hex_str: str) -> tuple[float, float]:
    """Parse Tuya hsv16 hex string 'HHHHSSSSBBBB' to HA (h, s) tuple.

    H: 0-360 (kept as-is)
    S: 0-1000 mapped to 0-100
    V/B component is ignored (brightness comes from DP 22)
    """
    h = int(hex_str[0:4], 16)
    s = int(hex_str[4:8], 16) / 10.0
    return (float(h), float(s))


def hs_to_tuya_hex(h: float, s: float, brightness_tuya: int) -> str:
    """Build Tuya hsv16 hex string from HA hs_color + Tuya brightness.

    h: 0-360
    s: 0-100 mapped to 0-1000
    brightness_tuya: 10-1000 (used as V component)
    """
    h_int = max(0, min(360, int(h)))
    s_int = max(0, min(1000, int(s * 10)))
    v_int = max(TUYA_BRIGHTNESS_MIN, min(TUYA_BRIGHTNESS_MAX, brightness_tuya))
    return f"{h_int:04x}{s_int:04x}{v_int:04x}"
