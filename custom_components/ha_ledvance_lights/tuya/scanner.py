"""UDP broadcast scanner for Tuya devices on the local network."""

from __future__ import annotations

import hashlib
import json
import logging
import select
import socket
import struct

from .crypto import aes_ecb_decrypt, aes_gcm_decrypt
from .message import (
    PREFIX_55AA,
    PREFIX_6699,
    PREFIX_55AA_BIN,
    PREFIX_6699_BIN,
    HEADER_SIZE_55AA,
    HEADER_SIZE_6699,
    REQ_DEVINFO,
    TuyaMessage,
    pack_message,
    parse_header,
    DecodeError,
)

_LOGGER = logging.getLogger(__name__)

# Tuya UDP broadcast ports
UDP_PORT_31 = 6666  # v3.1 plaintext broadcasts
UDP_PORT_33 = 6667  # v3.3 encrypted broadcasts
UDP_PORT_APP = 7000  # v3.5 app discovery

# Fixed key for UDP broadcast decryption
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()

# GCM tag size
GCM_TAG_SIZE = 16


def _create_udp_socket(port: int) -> socket.socket | None:
    """Create a UDP socket bound to a port, or None if it fails."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Allow port reuse on macOS
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        sock.bind(("", port))
        return sock
    except OSError as exc:
        _LOGGER.debug("Cannot bind to UDP port %d: %s", port, exc)
        return None


def _send_discovery_broadcast(sock: socket.socket) -> None:
    """Send a v3.5 REQ_DEVINFO broadcast to trigger device responses."""
    payload = json.dumps({"from": "app", "ip": "0.0.0.0"}).encode()

    msg = TuyaMessage(
        seqno=0,
        cmd=REQ_DEVINFO,
        retcode=0,
        payload=payload,
        crc=0,
        crc_good=True,
        prefix=PREFIX_6699,
        iv=b"\x00" * 12,
    )

    packed = pack_message(msg, hmac_key=UDP_KEY)

    try:
        sock.sendto(packed, ("255.255.255.255", UDP_PORT_APP))
    except OSError as exc:
        _LOGGER.debug("Failed to send discovery broadcast: %s", exc)


def _decode_broadcast(data: bytes, port: int) -> dict | None:
    """Decode a UDP broadcast message from a Tuya device."""
    try:
        if port == UDP_PORT_31:
            # v3.1: plaintext JSON (possibly with 55AA framing)
            return _decode_plaintext(data)

        if port == UDP_PORT_33:
            # v3.3: AES-ECB encrypted with UDP_KEY
            return _decode_encrypted_ecb(data)

        if port == UDP_PORT_APP:
            # v3.5: may be 6699-framed GCM or 55AA-framed
            return _decode_app_broadcast(data)

    except (DecodeError, json.JSONDecodeError, ValueError, KeyError) as exc:
        _LOGGER.debug("Failed to decode broadcast on port %d: %s", port, exc)

    return None


def _decode_plaintext(data: bytes) -> dict | None:
    """Decode plaintext broadcast (port 6666)."""
    # May be raw JSON or wrapped in 55AA framing
    if data[:4] == PREFIX_55AA_BIN:
        _, _, _, payload_len, header_size = parse_header(data)
        payload = data[header_size : header_size + payload_len - 8]
        return json.loads(payload)

    # Raw JSON
    text = data.decode("utf-8", errors="ignore").strip()
    if text.startswith("{"):
        return json.loads(text)

    return None


def _decode_encrypted_ecb(data: bytes) -> dict | None:
    """Decode AES-ECB encrypted broadcast (port 6667)."""
    payload = data

    # Strip 55AA framing if present
    if data[:4] == PREFIX_55AA_BIN:
        _, _, _, payload_len, header_size = parse_header(data)
        payload = data[header_size : header_size + payload_len - 8]

    decrypted = aes_ecb_decrypt(UDP_KEY, payload)
    text = decrypted.decode("utf-8", errors="ignore").strip()
    return json.loads(text)


def _decode_app_broadcast(data: bytes) -> dict | None:
    """Decode app-port broadcast (port 7000)."""
    if data[:4] == PREFIX_6699_BIN:
        # v3.5 GCM format
        _, _, _, payload_len, header_size = parse_header(data)
        blob = data[header_size : header_size + payload_len]

        if len(blob) < 12 + GCM_TAG_SIZE:
            return None

        iv = blob[:12]
        tag = blob[-GCM_TAG_SIZE:]
        ciphertext = blob[12:-GCM_TAG_SIZE]

        # Strip retcode (4 bytes) if present
        plaintext = aes_gcm_decrypt(UDP_KEY, ciphertext, iv, tag)
        if len(plaintext) >= 4:
            retcode = struct.unpack(">I", plaintext[:4])[0]
            if retcode in (0, 1, 2, 3):
                plaintext = plaintext[4:]

        text = plaintext.decode("utf-8", errors="ignore").strip()
        return json.loads(text)

    if data[:4] == PREFIX_55AA_BIN:
        # May be v3.3 format on port 7000
        return _decode_encrypted_ecb(data)

    # Try plaintext
    return _decode_plaintext(data)


def _extract_device_info(broadcast: dict) -> dict | None:
    """Extract relevant fields from a broadcast payload."""
    device_id = broadcast.get("gwId") or broadcast.get("devId")
    ip = broadcast.get("ip")

    if not device_id or not ip:
        return None

    return {
        "id": device_id,
        "ip": ip,
        "version": broadcast.get("version", "3.3"),
        "product_key": broadcast.get("productKey", ""),
        "encrypted": broadcast.get("encrypt", False),
    }


def scan_devices(timeout: float = 10.0) -> list[dict]:
    """Scan the local network for Tuya devices via UDP broadcasts.

    Returns a list of dicts with keys: id, ip, version, product_key.
    This is a blocking call — run it in an executor for async contexts.
    """
    devices: dict[str, dict] = {}
    sockets: list[tuple[socket.socket, int]] = []

    # Bind to all three ports
    for port in (UDP_PORT_31, UDP_PORT_33, UDP_PORT_APP):
        sock = _create_udp_socket(port)
        if sock:
            sockets.append((sock, port))

    if not sockets:
        _LOGGER.warning("Could not bind to any UDP discovery port")
        return []

    # Send discovery broadcast on port 7000
    for sock, port in sockets:
        if port == UDP_PORT_APP:
            _send_discovery_broadcast(sock)

    try:
        elapsed = 0.0
        poll_interval = 0.5

        while elapsed < timeout:
            readable, _, _ = select.select(
                [s for s, _ in sockets],
                [],
                [],
                min(poll_interval, timeout - elapsed),
            )

            for sock in readable:
                # Find the port for this socket
                port = next(p for s, p in sockets if s is sock)
                try:
                    data, addr = sock.recvfrom(4096)
                    broadcast = _decode_broadcast(data, port)
                    if broadcast:
                        info = _extract_device_info(broadcast)
                        if info and info["id"] not in devices:
                            _LOGGER.debug(
                                "Discovered device %s at %s (v%s)",
                                info["id"],
                                info["ip"],
                                info["version"],
                            )
                            devices[info["id"]] = info
                except OSError:
                    pass

            elapsed += poll_interval

            # Re-send discovery every 3 seconds
            if elapsed % 3.0 < poll_interval:
                for sock, port in sockets:
                    if port == UDP_PORT_APP:
                        _send_discovery_broadcast(sock)

    finally:
        for sock, _ in sockets:
            try:
                sock.close()
            except OSError:
                pass

    return list(devices.values())
