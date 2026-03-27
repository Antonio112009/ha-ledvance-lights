"""Tests for const.py conversion helpers."""

from custom_components.ha_ledvance_lights.const import (
    ha_brightness_to_tuya,
    hs_to_tuya_hex,
    kelvin_to_tuya_ct,
    parse_hsv_hex,
    tuya_brightness_to_ha,
    tuya_ct_to_kelvin,
)


class TestBrightnessConversion:
    """Tests for brightness conversion between HA (0-255) and Tuya (10-1000)."""

    def test_min(self):
        assert tuya_brightness_to_ha(10) == 0
        assert ha_brightness_to_tuya(0) == 10

    def test_max(self):
        assert tuya_brightness_to_ha(1000) == 255
        assert ha_brightness_to_tuya(255) == 1000

    def test_mid(self):
        ha_val = tuya_brightness_to_ha(505)
        assert 125 <= ha_val <= 130  # ~50%

    def test_roundtrip(self):
        for tuya_val in [10, 100, 500, 750, 1000]:
            ha_val = tuya_brightness_to_ha(tuya_val)
            back = ha_brightness_to_tuya(ha_val)
            assert abs(back - tuya_val) <= 4  # Allow small rounding error


class TestColorTempConversion:
    """Tests for color temperature conversion."""

    def test_warm(self):
        assert tuya_ct_to_kelvin(0) == 2700

    def test_cool(self):
        assert tuya_ct_to_kelvin(1000) == 6500

    def test_mid(self):
        kelvin = tuya_ct_to_kelvin(500)
        assert 4500 <= kelvin <= 4700

    def test_kelvin_to_tuya_warm(self):
        assert kelvin_to_tuya_ct(2700) == 0

    def test_kelvin_to_tuya_cool(self):
        assert kelvin_to_tuya_ct(6500) == 1000

    def test_kelvin_clamp_low(self):
        assert kelvin_to_tuya_ct(1000) == 0

    def test_kelvin_clamp_high(self):
        assert kelvin_to_tuya_ct(10000) == 1000

    def test_roundtrip(self):
        for tuya_val in [0, 250, 500, 750, 1000]:
            kelvin = tuya_ct_to_kelvin(tuya_val)
            back = kelvin_to_tuya_ct(kelvin)
            assert abs(back - tuya_val) <= 1


class TestHSVConversion:
    """Tests for HSV hex parsing and building."""

    def test_parse_red(self):
        # H=0, S=1000, V=1000
        h, s = parse_hsv_hex("000003e803e8")
        assert h == 0.0
        assert s == 100.0

    def test_parse_green(self):
        # H=120, S=1000, V=1000
        h, s = parse_hsv_hex("007803e803e8")
        assert h == 120.0
        assert s == 100.0

    def test_parse_blue(self):
        # H=240, S=1000, V=1000
        h, s = parse_hsv_hex("00f003e803e8")
        assert h == 240.0
        assert s == 100.0

    def test_parse_low_saturation(self):
        # H=180, S=500, V=800
        h, s = parse_hsv_hex("00b401f40320")
        assert h == 180.0
        assert s == 50.0

    def test_build_red(self):
        hexval = hs_to_tuya_hex(0, 100, 1000)
        assert hexval == "000003e803e8"

    def test_build_green(self):
        hexval = hs_to_tuya_hex(120, 100, 1000)
        assert hexval == "007803e803e8"

    def test_build_clamp_hue(self):
        hexval = hs_to_tuya_hex(400, 50, 500)
        assert hexval[:4] == "0168"  # clamped to 360

    def test_build_clamp_brightness(self):
        hexval = hs_to_tuya_hex(0, 100, 5)
        # Should clamp to minimum 10
        assert hexval[8:] == "000a"

    def test_roundtrip(self):
        h_in, s_in = 200.0, 75.0
        hexval = hs_to_tuya_hex(h_in, s_in, 500)
        h_out, s_out = parse_hsv_hex(hexval)
        assert h_out == h_in
        assert s_out == s_in
