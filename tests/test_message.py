"""Tests for tuya.message module."""

import struct

import pytest

from custom_components.ha_ledvance_lights.tuya.message import (
    CONTROL,
    DP_QUERY,
    DP_QUERY_NEW,
    HEADER_SIZE_55AA,
    PREFIX_55AA,
    PREFIX_6699,
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


class TestPackUnpack6699:
    """Tests for 6699 (v3.5 GCM) message packing/unpacking.

    The wire-format vectors below were generated with the reference
    tinytuya 1.17.6 implementation, so these tests pin our framing (header
    AAD, no retcode in client requests, length field semantics) to the real
    protocol rather than to our own round-trip.
    """

    KEY = b"0123456789abcdef"
    IV = bytes(range(12))

    # tinytuya.pack_message(TuyaMessage(1, DP_QUERY_NEW, None, b"{}", 0, True,
    #                                   PREFIX_6699, IV), hmac_key=KEY)
    CLIENT_PACKED = bytes.fromhex(
        "00006699000000000001000000100000001e000102030405060708090a0b"
        "8642cb923f4c8a8cfd11f0db64e3112dcccf00009966"
    )

    # tinytuya.pack_message(TuyaMessage(2, DP_QUERY_NEW, 0,
    #                                   b'{"dps":{"20":true,"22":500}}',
    #                                   0, True, PREFIX_6699, IV), hmac_key=KEY)
    DEVICE_PACKED = bytes.fromhex(
        "00006699000000000002000000100000003c000102030405060708090a0b"
        "fd3fc41d65565f469b043d61e2a9800f3aa3258f629f6879454bd0c6df9bd611"
        "f774689fd8b3a1c6a6ee46d0ed8dabd400009966"
    )

    def test_client_pack_matches_reference(self):
        """Client request (no retcode) must match reference bytes exactly."""
        msg = TuyaMessage(
            seqno=1,
            cmd=DP_QUERY_NEW,
            retcode=None,
            payload=b"{}",
            crc=0,
            crc_good=True,
            prefix=PREFIX_6699,
            iv=self.IV,
        )
        assert pack_message(msg, hmac_key=self.KEY) == self.CLIENT_PACKED

    def test_unpack_reference_device_response(self):
        """A device-style response packed by the reference must decode."""
        unpacked = unpack_message(self.DEVICE_PACKED, hmac_key=self.KEY)
        assert unpacked.seqno == 2
        assert unpacked.cmd == DP_QUERY_NEW
        assert unpacked.retcode == 0
        assert unpacked.payload == b'{"dps":{"20":true,"22":500}}'
        assert unpacked.prefix == PREFIX_6699

    def test_roundtrip(self):
        payload = b'{"dps":{"20":true}}'
        msg = TuyaMessage(
            seqno=7,
            cmd=DP_QUERY_NEW,
            retcode=None,
            payload=payload,
            crc=0,
            crc_good=True,
            prefix=PREFIX_6699,
            iv=self.IV,
        )
        packed = pack_message(msg, hmac_key=self.KEY)
        unpacked = unpack_message(packed, hmac_key=self.KEY)
        assert unpacked.seqno == 7
        assert unpacked.payload == payload

    def test_random_iv_when_not_given(self):
        """Without an explicit IV, packing must not reuse a fixed nonce."""
        msg = TuyaMessage(
            seqno=1,
            cmd=DP_QUERY_NEW,
            retcode=None,
            payload=b"{}",
            crc=0,
            crc_good=True,
            prefix=PREFIX_6699,
            iv=None,
        )
        packed_a = pack_message(msg, hmac_key=self.KEY)
        packed_b = pack_message(msg, hmac_key=self.KEY)
        assert packed_a[18:30] != packed_b[18:30]

    def test_tampered_header_fails_auth(self):
        """The header is GCM AAD — altering it must break decryption."""
        tampered = bytearray(self.DEVICE_PACKED)
        tampered[8] ^= 0x01  # flip a bit in the seqno field
        with pytest.raises(DecodeError, match="GCM decryption failed"):
            unpack_message(bytes(tampered), hmac_key=self.KEY)

    def test_wrong_key_fails(self):
        with pytest.raises(DecodeError, match="GCM decryption failed"):
            unpack_message(self.DEVICE_PACKED, hmac_key=b"wrongkey12345678")


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
