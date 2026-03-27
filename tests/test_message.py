"""Tests for tuya.message module."""

import struct

import pytest

from custom_components.ha_ledvance_lights.tuya.message import (
    CONTROL,
    DP_QUERY,
    HEADER_SIZE_55AA,
    PREFIX_55AA,
    SUFFIX_55AA,
    DecodeError,
    TuyaMessage,
    _crc32,
    _hmac_sha256,
    find_prefix,
    pack_message,
    parse_header,
    unpack_message,
)


class TestCRC32:
    """Tests for CRC32 calculation."""

    def test_known_value(self):
        crc = _crc32(b"hello")
        assert isinstance(crc, int)
        assert crc == 0x3610A686

    def test_empty(self):
        crc = _crc32(b"")
        assert crc == 0


class TestHMACSHA256:
    """Tests for HMAC-SHA256."""

    def test_produces_32_bytes(self):
        mac = _hmac_sha256(b"key", b"data")
        assert len(mac) == 32

    def test_deterministic(self):
        mac1 = _hmac_sha256(b"key", b"data")
        mac2 = _hmac_sha256(b"key", b"data")
        assert mac1 == mac2

    def test_different_key(self):
        mac1 = _hmac_sha256(b"key1", b"data")
        mac2 = _hmac_sha256(b"key2", b"data")
        assert mac1 != mac2


class TestPackUnpack55AA:
    """Tests for 55AA message packing/unpacking."""

    def test_pack_basic(self):
        msg = TuyaMessage(
            seqno=1,
            cmd=DP_QUERY,
            retcode=0,
            payload=b'{"test":1}',
            crc=0,
            crc_good=True,
        )
        packed = pack_message(msg)

        # Verify prefix
        assert packed[:4] == struct.pack(">I", PREFIX_55AA)
        # Verify suffix
        assert packed[-4:] == struct.pack(">I", SUFFIX_55AA)

    def test_roundtrip_no_hmac(self):
        payload = b'{"dps":{"1":true}}'
        msg = TuyaMessage(
            seqno=42,
            cmd=CONTROL,
            retcode=0,
            payload=payload,
            crc=0,
            crc_good=True,
        )
        packed = pack_message(msg)
        unpacked = unpack_message(packed)

        assert unpacked.seqno == 42
        assert unpacked.cmd == CONTROL
        assert unpacked.payload == payload
        assert unpacked.crc_good is True

    def test_roundtrip_with_hmac(self):
        key = b"0123456789abcdef"
        payload = b'{"status":"ok"}'
        msg = TuyaMessage(
            seqno=10,
            cmd=DP_QUERY,
            retcode=0,
            payload=payload,
            crc=0,
            crc_good=True,
        )
        packed = pack_message(msg, hmac_key=key)
        unpacked = unpack_message(packed, hmac_key=key)

        assert unpacked.seqno == 10
        assert unpacked.cmd == DP_QUERY
        assert unpacked.payload == payload
        assert unpacked.crc_good is True

    def test_hmac_verification_fails_with_wrong_key(self):
        key = b"0123456789abcdef"
        msg = TuyaMessage(
            seqno=1,
            cmd=DP_QUERY,
            retcode=0,
            payload=b"test",
            crc=0,
            crc_good=True,
        )
        packed = pack_message(msg, hmac_key=key)
        unpacked = unpack_message(packed, hmac_key=b"wrongkey12345678")
        assert unpacked.crc_good is False

    def test_seqno_preserved(self):
        for seqno in [0, 1, 255, 65535, 0xFFFFFFFF]:
            msg = TuyaMessage(
                seqno=seqno,
                cmd=DP_QUERY,
                retcode=0,
                payload=b"{}",
                crc=0,
                crc_good=True,
            )
            packed = pack_message(msg)
            unpacked = unpack_message(packed)
            assert unpacked.seqno == seqno

    def test_empty_payload(self):
        msg = TuyaMessage(
            seqno=1,
            cmd=DP_QUERY,
            retcode=0,
            payload=b"",
            crc=0,
            crc_good=True,
        )
        packed = pack_message(msg)
        unpacked = unpack_message(packed)
        assert unpacked.payload == b""


class TestParseHeader:
    """Tests for header parsing."""

    def test_55aa_header(self):
        header = struct.pack(">4I", PREFIX_55AA, 1, DP_QUERY, 100)
        prefix, seqno, cmd, length, hdr_size = parse_header(header)
        assert prefix == PREFIX_55AA
        assert seqno == 1
        assert cmd == DP_QUERY
        assert length == 100
        assert hdr_size == HEADER_SIZE_55AA

    def test_too_short(self):
        with pytest.raises(DecodeError, match="Not enough data"):
            parse_header(b"\x00\x00")

    def test_unknown_prefix(self):
        with pytest.raises(DecodeError, match="Unknown prefix"):
            parse_header(b"\x00\x00\x00\x01" + b"\x00" * 20)

    def test_payload_too_large(self):
        header = struct.pack(">4I", PREFIX_55AA, 1, DP_QUERY, 10000)
        with pytest.raises(DecodeError, match="Payload too large"):
            parse_header(header)


class TestFindPrefix:
    """Tests for prefix finding in data."""

    def test_find_55aa_at_start(self):
        data = struct.pack(">I", PREFIX_55AA) + b"\x00" * 20
        prefix, offset = find_prefix(data)
        assert prefix == PREFIX_55AA
        assert offset == 0

    def test_find_55aa_with_garbage(self):
        data = b"\xff\xff" + struct.pack(">I", PREFIX_55AA) + b"\x00" * 20
        prefix, offset = find_prefix(data)
        assert prefix == PREFIX_55AA
        assert offset == 2

    def test_no_prefix(self):
        with pytest.raises(DecodeError, match="No valid prefix"):
            find_prefix(b"\x00" * 20)
