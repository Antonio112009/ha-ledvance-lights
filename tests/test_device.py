"""Tests for tuya.device module."""

import json

from custom_components.ha_ledvance_lights.tuya.device import (
    ERR_CONNECT,
    ERR_OFFLINE,
    TuyaDevice,
    _error_json,
)


class TestErrorJson:
    """Tests for error response formatting."""

    def test_known_error_code(self):
        err = _error_json(ERR_CONNECT)
        assert err["Err"] == "901"
        assert "Error" in err
        assert "Unable to Connect" in err["Error"]

    def test_custom_message(self):
        err = _error_json(ERR_CONNECT, "Custom message")
        assert err["Error"] == "Custom message"
        assert err["Err"] == "901"

    def test_all_error_codes(self):
        for code in ["901", "902", "904", "905", "914"]:
            err = _error_json(code)
            assert err["Err"] == code
            assert err["Error"] != ""


class TestTuyaDeviceInit:
    """Tests for TuyaDevice initialization."""

    def test_defaults(self):
        dev = TuyaDevice("test_id", "192.168.1.1", "0123456789abcdef")
        assert dev.dev_id == "test_id"
        assert dev.address == "192.168.1.1"
        assert dev.local_key == b"0123456789abcdef"
        assert dev.version == 3.3

    def test_custom_version(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc", version="3.4")
        assert dev.version == 3.4

    def test_set_version(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        dev.set_version(3.5)
        assert dev.version == 3.5

    def test_set_timeout(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        dev.set_socketTimeout(10)
        assert dev._timeout == 10

    def test_set_retry_limit(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        dev.set_socketRetryLimit(3)
        assert dev._retry_limit == 3


class TestTuyaDevicePayload:
    """Tests for payload building."""

    def test_build_control_v33(self):
        dev = TuyaDevice("mydev", "1.2.3.4", "key1234567890abc", version="3.3")
        cmd, payload = dev._build_payload(0x07, {"1": True})
        assert cmd == 0x07
        data = json.loads(payload)
        assert data["devId"] == "mydev"
        assert data["dps"] == {"1": True}

    def test_build_query_v33(self):
        dev = TuyaDevice("mydev", "1.2.3.4", "key1234567890abc", version="3.3")
        cmd, payload = dev._build_payload(0x0A)
        assert cmd == 0x0A
        data = json.loads(payload)
        assert data["gwId"] == "mydev"
        assert data["devId"] == "mydev"

    def test_build_control_v34(self):
        dev = TuyaDevice("mydev", "1.2.3.4", "key1234567890abc", version="3.4")
        cmd, payload = dev._build_payload(0x07, {"1": True})
        assert cmd == 0x0D  # CONTROL_NEW
        data = json.loads(payload)
        assert data["protocol"] == 5
        assert data["data"]["dps"] == {"1": True}

    def test_build_query_v34(self):
        dev = TuyaDevice("mydev", "1.2.3.4", "key1234567890abc", version="3.4")
        cmd, payload = dev._build_payload(0x0A)
        assert cmd == 0x10  # DP_QUERY_NEW
        assert payload == b"{}"


class TestTuyaDeviceConnection:
    """Tests for connection error handling."""

    def test_status_connection_refused(self):
        dev = TuyaDevice("id", "192.168.255.255", "key1234567890abc")
        dev.set_socketTimeout(1)
        dev.set_socketRetryLimit(0)
        result = dev.status()
        assert "Err" in result
        assert result["Err"] in (ERR_CONNECT, ERR_OFFLINE)

    def test_set_status_builds_correct_payload(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        _cmd, payload = dev._build_payload(0x07, {"20": True})
        data = json.loads(payload)
        assert data["dps"]["20"] is True

    def test_set_value_builds_correct_payload(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        _cmd, payload = dev._build_payload(0x07, {"22": 500})
        data = json.loads(payload)
        assert data["dps"]["22"] == 500
