"""Light platform for Ledvance Lights."""

from __future__ import annotations

from typing import Any, ClassVar

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_DEVICE_ID,
    DOMAIN,
    DP_BRIGHTNESS,
    DP_COLOR_HSV,
    DP_COLOR_TEMP,
    DP_MODE,
    DP_POWER,
    DP_SCENE_NUM,
    KELVIN_COOL,
    KELVIN_WARM,
    SCENE_EFFECTS,
    TUYA_BRIGHTNESS_MAX,
    ha_brightness_to_tuya,
    hs_to_tuya_hex,
    kelvin_to_tuya_ct,
    parse_hsv_hex,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)
from .coordinator import LedvanceConfigEntry, LedvanceDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LedvanceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Ledvance light from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([LedvanceLight(coordinator, entry)])


class LedvanceLight(CoordinatorEntity[LedvanceDataUpdateCoordinator], LightEntity):
    """Representation of a Ledvance Lights light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes: ClassVar[set[ColorMode]] = {ColorMode.COLOR_TEMP, ColorMode.HS}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_min_color_temp_kelvin = KELVIN_WARM
    _attr_max_color_temp_kelvin = KELVIN_COOL

    def __init__(
        self,
        coordinator: LedvanceDataUpdateCoordinator,
        entry: LedvanceConfigEntry,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator)

        device_id = entry.data[CONF_DEVICE_ID]
        self._attr_unique_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Ledvance",
            model="Smart+ WiFi",
            name=entry.title,
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether the light is on."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(str(DP_POWER))

    def _is_scene_mode(self) -> bool:
        """Return True if the device is currently running a scene/effect."""
        if self.coordinator.data is None:
            return False
        return self.coordinator.data.get(str(DP_MODE)) == "scene"

    @property
    def brightness(self) -> int | None:
        """Return the brightness (0-255).

        In white/CT mode brightness comes from DP22 (DP_BRIGHTNESS).
        In colour mode brightness is the V component of the HSV hex (DP24).
        Ledvance devices do NOT update DP22 when in colour mode, so reading
        DP22 would return a stale white-mode value.
        In scene/effect mode brightness is device-controlled and unknown.
        """
        if self.coordinator.data is None:
            return None

        mode = self.coordinator.data.get(str(DP_MODE))
        if mode == "scene":
            return None
        if mode == "colour":
            hex_str = self.coordinator.data.get(str(DP_COLOR_HSV), "")
            if hex_str and len(hex_str) >= 12:
                v_tuya = int(hex_str[8:12], 16)
                return tuya_brightness_to_ha(v_tuya)
            return None

        value = self.coordinator.data.get(str(DP_BRIGHTNESS))
        if value is None:
            return None
        return tuya_brightness_to_ha(value)

    @property
    def color_mode(self) -> ColorMode | None:
        """Return the current color mode.

        In scene mode the device runs a built-in effect; HA still requires a
        valid ``color_mode``, so we report the underlying CT mode but the
        per-attribute properties (brightness, color_temp, hs_color) all return
        None to avoid surfacing stale values.
        """
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.get(str(DP_MODE))
        if mode == "colour":
            return ColorMode.HS
        return ColorMode.COLOR_TEMP

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        if self.coordinator.data is None:
            return None
        if self._is_scene_mode():
            return None
        if self.color_mode != ColorMode.COLOR_TEMP:
            return None
        value = self.coordinator.data.get(str(DP_COLOR_TEMP))
        if value is None:
            return None
        return tuya_ct_to_kelvin(value)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue/saturation color."""
        if self.coordinator.data is None:
            return None
        if self._is_scene_mode():
            return None
        if self.color_mode != ColorMode.HS:
            return None
        hex_str = self.coordinator.data.get(str(DP_COLOR_HSV))
        if not hex_str or len(hex_str) < 12:
            return None
        return parse_hsv_hex(hex_str)

    @property
    def effect_list(self) -> list[str]:
        """Return the list of supported effects."""
        return SCENE_EFFECTS

    @property
    def effect(self) -> str | None:
        """Return the current effect."""
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.get(str(DP_MODE))
        if mode != "scene":
            return None
        scene_num = self.coordinator.data.get(str(DP_SCENE_NUM))
        if scene_num is not None and 1 <= scene_num <= len(SCENE_EFFECTS):
            return SCENE_EFFECTS[scene_num - 1]
        return None

    def _current_brightness_tuya(self) -> int:
        """Return the current brightness on the Tuya scale (10-1000).

        In colour mode the live value is the V component of the HSV hex —
        DP22 is stale there (the device stops updating it).  Fall back to
        DP22 for white mode, then to max.
        """
        data = self.coordinator.data or {}
        if data.get(str(DP_MODE)) == "colour":
            hex_str = data.get(str(DP_COLOR_HSV), "")
            if isinstance(hex_str, str) and len(hex_str) >= 12:
                try:
                    return int(hex_str[8:12], 16)
                except ValueError:
                    pass
        value = data.get(str(DP_BRIGHTNESS))
        if isinstance(value, int):
            return value
        return TUYA_BRIGHTNESS_MAX

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional attributes."""
        brightness_tuya: int | None = None
        color_temp_tuya: int | None = None
        hsv_hex: str | None = None
        scene_num: int | None = None

        if ATTR_BRIGHTNESS in kwargs:
            brightness_tuya = ha_brightness_to_tuya(kwargs[ATTR_BRIGHTNESS])

        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            if effect_name in SCENE_EFFECTS:
                scene_num = SCENE_EFFECTS.index(effect_name) + 1

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            color_temp_tuya = kelvin_to_tuya_ct(kwargs[ATTR_COLOR_TEMP_KELVIN])

        if ATTR_HS_COLOR in kwargs:
            h, s = kwargs[ATTR_HS_COLOR]
            # Use provided brightness or current brightness for V component
            v = brightness_tuya if brightness_tuya is not None else self._current_brightness_tuya()
            hsv_hex = hs_to_tuya_hex(h, s, v)
        elif brightness_tuya is not None and self.color_mode == ColorMode.HS:
            # Brightness-only change while in colour mode: update the HSV hex
            # with the new V value so the device stays in colour mode instead
            # of switching to white mode via DP_BRIGHTNESS.
            data = self.coordinator.data or {}
            current_hsv = data.get(str(DP_COLOR_HSV), "")
            if current_hsv and len(current_hsv) >= 12:
                h_cur, s_cur = parse_hsv_hex(current_hsv)
                hsv_hex = hs_to_tuya_hex(h_cur, s_cur, brightness_tuya)
            else:
                # No existing colour data — default to red at requested brightness
                hsv_hex = hs_to_tuya_hex(0.0, 100.0, brightness_tuya)

        await self.coordinator.async_turn_on_with_attrs(
            brightness=brightness_tuya,
            color_temp=color_temp_tuya,
            hsv_hex=hsv_hex,
            scene_num=scene_num,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        await self.coordinator.async_turn_off()
