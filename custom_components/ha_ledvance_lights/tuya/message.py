"""Tuya protocol message framing — pack, unpack, and parse."""

from __future__ import annotations

import binascii
import hashlib
import hmac
import struct
from dataclasses import dataclass

from .crypto import aes_gcm_decrypt, aes_gcm_encrypt

# ── Prefixes and suffixes ──
PREFIX_55AA = 0x000055AA
PREFIX_6699 = 0x00006699
SUFFIX_55AA = 0x0000AA55
SUFFIX_6699 = 0x00009966

PREFIX_55AA_BIN = struct.pack(">I", PREFIX_55AA)
PREFIX_6699_BIN = struct.pack(">I", PREFIX_6699)

# ── Struct formats ──
HEADER_FMT_55AA = ">4I"  # prefix, seqno, cmd, length (16 bytes)
HEADER_FMT_6699 = ">IHIII"  # prefix, unknown(2), seqno, cmd, length (18 bytes)
HEADER_SIZE_55AA = struct.calcsize(HEADER_FMT_55AA)  # 16
HEADER_SIZE_6699 = struct.calcsize(HEADER_FMT_6699)  # 18
RETCODE_FMT = ">I"  # 4 bytes
RETCODE_SIZE = struct.calcsize(RETCODE_FMT)

# ── Footer sizes ──
CRC_SIZE = 4
HMAC_SIZE = 32
GCM_TAG_SIZE = 16
SUFFIX_SIZE = 4
FOOTER_55AA = CRC_SIZE + SUFFIX_SIZE  # 8
FOOTER_HMAC = HMAC_SIZE + SUFFIX_SIZE  # 36
FOOTER_6699 = GCM_TAG_SIZE + SUFFIX_SIZE  # 20

# ── Command types ──
SESS_KEY_NEG_START = 0x03
SESS_KEY_NEG_RESP = 0x04
SESS_KEY_NEG_FINISH = 0x05
CONTROL = 0x07
STATUS = 0x08
HEART_BEAT = 0x09
DP_QUERY = 0x0A
CONTROL_NEW = 0x0D
DP_QUERY_NEW = 0x10
UPDATEDPS = 0x12
REQ_DEVINFO = 0x25

# ── Protocol version headers ──
PROTOCOL_3X_HEADER = 12 * b"\x00"
PROTOCOL_33_HEADER = b"3.3" + PROTOCOL_3X_HEADER  # 15 bytes
PROTOCOL_34_HEADER = b"3.4" + PROTOCOL_3X_HEADER
PROTOCOL_35_HEADER = b"3.5" + PROTOCOL_3X_HEADER

NO_PROTOCOL_HEADER_CMDS = {
    DP_QUERY,
    DP_QUERY_NEW,
    UPDATEDPS,
    HEART_BEAT,
    SESS_KEY_NEG_START,
    SESS_KEY_NEG_RESP,
    SESS_KEY_NEG_FINISH,
}

# Maximum sane payload size
MAX_PAYLOAD_SIZE = 4096


class DecodeError(Exception):
    """Error decoding a Tuya message."""


@dataclass
class TuyaMessage:
    """Represents a decoded Tuya protocol message."""

    seqno: int
    cmd: int
    retcode: int
    payload: bytes
    crc: bytes | int
    crc_good: bool
    prefix: int = PREFIX_55AA
    iv: bytes | None = None


def _crc32(data: bytes) -> int:
    """Calculate CRC32 matching Tuya's format."""
    return binascii.crc32(data) & 0xFFFFFFFF


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    """Calculate HMAC-SHA256."""
    return hmac.new(key, data, hashlib.sha256).digest()


# ─────────────────────────────────────────────
#  Packing
# ─────────────────────────────────────────────


def pack_message(msg: TuyaMessage, hmac_key: bytes | None = None) -> bytes:
    """Pack a TuyaMessage into wire-format bytes."""
    if msg.prefix == PREFIX_6699:
        return _pack_6699(msg, hmac_key or b"")
    return _pack_55aa(msg, hmac_key)


def _pack_55aa(msg: TuyaMessage, hmac_key: bytes | None) -> bytes:
    """Pack a 0x55AA-prefix message."""
    payload = msg.payload

    if hmac_key:
        # HMAC footer: 32-byte HMAC + 4-byte suffix
        footer_size = FOOTER_HMAC
    else:
        # CRC footer: 4-byte CRC + 4-byte suffix
        footer_size = FOOTER_55AA

    length = len(payload) + footer_size

    header = struct.pack(HEADER_FMT_55AA, PREFIX_55AA, msg.seqno, msg.cmd, length)
    header_payload = header + payload

    if hmac_key:
        mac = _hmac_sha256(hmac_key, header_payload)
        return header_payload + mac + struct.pack(">I", SUFFIX_55AA)
    else:
        crc = _crc32(header_payload)
        return header_payload + struct.pack(">2I", crc, SUFFIX_55AA)


def _pack_6699(msg: TuyaMessage, key: bytes) -> bytes:
    """Pack a 0x6699-prefix message (v3.5 GCM)."""
    payload = msg.payload

    # Retcode prefix
    if msg.retcode is not None:
        payload = struct.pack(RETCODE_FMT, msg.retcode) + payload

    # Build header first (without length) for AAD
    nonce = msg.iv if msg.iv else b"\x00" * 12
    header_no_len = struct.pack(">IHI", PREFIX_6699, 0, msg.seqno)

    # Encrypt with GCM — AAD is header from byte 4 onwards + cmd bytes
    # We need to know the total structure to compute AAD
    iv, ciphertext, tag = aes_gcm_encrypt(
        key, payload, iv=nonce, aad=None
    )

    # Payload area = IV + ciphertext + tag
    encrypted_blob = iv + ciphertext + tag
    length = len(encrypted_blob)

    header = struct.pack(HEADER_FMT_6699, PREFIX_6699, 0, msg.seqno, msg.cmd, length)
    return header + encrypted_blob + struct.pack(">I", SUFFIX_6699)


# ─────────────────────────────────────────────
#  Unpacking
# ─────────────────────────────────────────────


def find_prefix(data: bytes) -> tuple[int, int]:
    """Find the first valid prefix in data. Returns (prefix, offset)."""
    for i in range(len(data) - 3):
        if data[i : i + 4] == PREFIX_55AA_BIN:
            return PREFIX_55AA, i
        if data[i : i + 4] == PREFIX_6699_BIN:
            return PREFIX_6699, i
    raise DecodeError("No valid prefix found in data")


def parse_header(data: bytes) -> tuple[int, int, int, int, int]:
    """Parse message header. Returns (prefix, seqno, cmd, payload_len, header_size)."""
    if len(data) < 4:
        raise DecodeError("Not enough data for header prefix")

    prefix = struct.unpack(">I", data[:4])[0]

    if prefix == PREFIX_55AA:
        if len(data) < HEADER_SIZE_55AA:
            raise DecodeError("Not enough data for 55AA header")
        _, seqno, cmd, length = struct.unpack(HEADER_FMT_55AA, data[:HEADER_SIZE_55AA])
        if length > MAX_PAYLOAD_SIZE:
            raise DecodeError(f"Payload too large: {length}")
        return prefix, seqno, cmd, length, HEADER_SIZE_55AA

    if prefix == PREFIX_6699:
        if len(data) < HEADER_SIZE_6699:
            raise DecodeError("Not enough data for 6699 header")
        _, _, seqno, cmd, length = struct.unpack(
            HEADER_FMT_6699, data[:HEADER_SIZE_6699]
        )
        if length > MAX_PAYLOAD_SIZE:
            raise DecodeError(f"Payload too large: {length}")
        return prefix, seqno, cmd, length, HEADER_SIZE_6699

    raise DecodeError(f"Unknown prefix: 0x{prefix:08X}")


def unpack_message(
    data: bytes, hmac_key: bytes | None = None
) -> TuyaMessage:
    """Unpack wire-format bytes into a TuyaMessage."""
    prefix, seqno, cmd, payload_len, header_size = parse_header(data)

    if prefix == PREFIX_6699:
        return _unpack_6699(data, seqno, cmd, payload_len, header_size, hmac_key)
    return _unpack_55aa(data, seqno, cmd, payload_len, header_size, hmac_key)


def _unpack_55aa(
    data: bytes,
    seqno: int,
    cmd: int,
    payload_len: int,
    header_size: int,
    hmac_key: bytes | None,
) -> TuyaMessage:
    """Unpack a 0x55AA message."""
    # Determine footer type
    if hmac_key:
        footer_size = FOOTER_HMAC
    else:
        footer_size = FOOTER_55AA

    payload_end = header_size + payload_len - footer_size
    payload = data[header_size:payload_end]

    # Check for retcode (first 4 bytes if present)
    retcode = 0
    if len(payload) >= RETCODE_SIZE:
        possible_retcode = struct.unpack(RETCODE_FMT, payload[:RETCODE_SIZE])[0]
        # Retcodes are typically 0 or small error numbers
        if possible_retcode in (0, 1, 2, 3):
            retcode = possible_retcode
            # Don't strip retcode from payload — the caller handles this

    # Verify CRC/HMAC
    crc_good = True
    if hmac_key:
        mac_start = header_size + payload_len - FOOTER_HMAC
        mac_end = mac_start + HMAC_SIZE
        received_mac = data[mac_start:mac_end]
        expected_mac = _hmac_sha256(hmac_key, data[:mac_start])
        crc_good = hmac.compare_digest(received_mac, expected_mac)
        crc = received_mac
    else:
        crc_start = header_size + payload_len - FOOTER_55AA
        received_crc = struct.unpack(">I", data[crc_start : crc_start + CRC_SIZE])[0]
        expected_crc = _crc32(data[:crc_start])
        crc_good = received_crc == expected_crc
        crc = received_crc

    return TuyaMessage(
        seqno=seqno,
        cmd=cmd,
        retcode=retcode,
        payload=payload,
        crc=crc,
        crc_good=crc_good,
        prefix=PREFIX_55AA,
    )


def _unpack_6699(
    data: bytes,
    seqno: int,
    cmd: int,
    payload_len: int,
    header_size: int,
    key: bytes | None,
) -> TuyaMessage:
    """Unpack a 0x6699 message (v3.5 GCM)."""
    if not key:
        raise DecodeError("Key required for 6699 decryption")

    blob_start = header_size
    blob_end = header_size + payload_len

    blob = data[blob_start:blob_end]

    if len(blob) < 12 + GCM_TAG_SIZE:
        raise DecodeError("GCM payload too short")

    iv = blob[:12]
    tag = blob[-GCM_TAG_SIZE:]
    ciphertext = blob[12:-GCM_TAG_SIZE]

    try:
        plaintext = aes_gcm_decrypt(key, ciphertext, iv, tag)
    except Exception as exc:
        raise DecodeError(f"GCM decryption failed: {exc}") from exc

    # Strip retcode if present
    retcode = 0
    payload = plaintext
    if len(plaintext) >= RETCODE_SIZE:
        possible_retcode = struct.unpack(RETCODE_FMT, plaintext[:RETCODE_SIZE])[0]
        if possible_retcode in (0, 1, 2, 3):
            retcode = possible_retcode
            payload = plaintext[RETCODE_SIZE:]

    return TuyaMessage(
        seqno=seqno,
        cmd=cmd,
        retcode=retcode,
        payload=payload,
        crc=tag,
        crc_good=True,
        prefix=PREFIX_6699,
        iv=iv,
    )
