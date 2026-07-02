"""Tests for tuya.device module."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from custom_components.ha_ledvance_lights.tuya.device import (
    ERR_CONNECT,
    ERR_OFFLINE,
    TuyaDevice,
    _error_json,
)
from custom_components.ha_ledvance_lights.tuya.message import (
    DP_QUERY_NEW,
    PREFIX_6699,
    TuyaMessage,
    pack_message,
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


class _FakeSocket:
    """Socket stub serving from a buffer; counts reads past the end."""

    def __init__(self, data: bytes) -> None:
        self._buffer = data
        self.reads_past_end = 0

    def recv(self, num_bytes: int) -> bytes:
        if not self._buffer:
            # A real socket would block here until the timeout fires.
            self.reads_past_end += 1
            raise TimeoutError
        chunk = self._buffer[:num_bytes]
        self._buffer = self._buffer[num_bytes:]
        return chunk

    def close(self) -> None:
        pass


class TestReceive6699:
    """The v3.5 receive path must read exactly one frame — no over-read."""

    KEY = b"0123456789abcdef"

    def test_receive_reads_exact_frame_length(self):
        """An over-read would block until the socket timeout on every poll."""
        dev = TuyaDevice("id", "1.2.3.4", self.KEY.decode(), version="3.5")
        packed = pack_message(
            TuyaMessage(
                seqno=2,
                cmd=DP_QUERY_NEW,
                retcode=0,
                payload=b'{"dps":{"20":true}}',
                crc=0,
                crc_good=True,
                prefix=PREFIX_6699,
                iv=bytes(range(12)),
            ),
            hmac_key=self.KEY,
        )
        fake = _FakeSocket(packed)
        dev._socket = fake

        msg = dev._receive_raw()

        assert msg is not None
        assert msg.payload == b'{"dps":{"20":true}}'
        assert fake.reads_past_end == 0


class TestSendReceiveSerialization:
    """Concurrent executor calls must not interleave on the device."""

    def test_send_receive_serialized(self):
        dev = TuyaDevice("id", "1.2.3.4", "key1234567890abc")
        active = 0
        max_active = 0

        def fake_exchange(cmd, data=None):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            time.sleep(0.02)
            active -= 1
            return {"dps": {}}

        dev._send_receive_locked = fake_exchange

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: dev._send_receive(0x0A), range(8)))

        assert all(r == {"dps": {}} for r in results)
        assert max_active == 1
