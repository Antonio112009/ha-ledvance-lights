"""UDP broadcast scanner and TCP probe scanner for Tuya devices."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import select
import socket
import struct
from concurrent.futures import ThreadPoolExecutor, as_completed

from .crypto import aes_ecb_decrypt, aes_gcm_decrypt
from .message import (
    PREFIX_55AA_BIN,
    PREFIX_6699,
    PREFIX_6699_BIN,
    REQ_DEVINFO,
    DecodeError,
    TuyaMessage,
    pack_message,
    parse_header,
)

_LOGGER = logging.getLogger(__name__)

# Tuya UDP broadcast ports
UDP_PORT_31 = 6666  # v3.1 plaintext broadcasts
UDP_PORT_33 = 6667  # v3.3 encrypted broadcasts
UDP_PORT_APP = 7000  # v3.5 app discovery

# Tuya TCP port
TCP_PORT = 6668

# Fixed key for UDP broadcast decryption
UDP_KEY = hashlib.md5(b"yGAdlopoPVldABfn").digest()

# GCM tag size
GCM_TAG_SIZE = 16

# TCP probe settings
TCP_PROBE_TIMEOUT = 1.0
TCP_PROBE_MAX_WORKERS = 50


def _create_udp_socket(port: int) -> socket.socket | None:
    """Create a UDP socket bound to a port, or None if it fails."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        import contextlib

        with contextlib.suppress(AttributeError, OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
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
            return _decode_plaintext(data)
        if port == UDP_PORT_33:
            return _decode_encrypted_ecb(data)
        if port == UDP_PORT_APP:
            return _decode_app_broadcast(data)
    except (DecodeError, json.JSONDecodeError, ValueError, KeyError) as exc:
        _LOGGER.debug("Failed to decode broadcast on port %d: %s", port, exc)
    return None


def _decode_plaintext(data: bytes) -> dict | None:
    """Decode plaintext broadcast (port 6666)."""
    if data[:4] == PREFIX_55AA_BIN:
        _, _, _, payload_len, header_size = parse_header(data)
        payload = data[header_size : header_size + payload_len - 8]
        return json.loads(payload)
    text = data.decode("utf-8", errors="ignore").strip()
    if text.startswith("{"):
        return json.loads(text)
    return None


def _decode_encrypted_ecb(data: bytes) -> dict | None:
    """Decode AES-ECB encrypted broadcast (port 6667)."""
    payload = data
    if data[:4] == PREFIX_55AA_BIN:
        _, _, _, payload_len, header_size = parse_header(data)
        payload = data[header_size : header_size + payload_len - 8]
    decrypted = aes_ecb_decrypt(UDP_KEY, payload)
    text = decrypted.decode("utf-8", errors="ignore").strip()
    return json.loads(text)


def _decode_app_broadcast(data: bytes) -> dict | None:
    """Decode app-port broadcast (port 7000)."""
    if data[:4] == PREFIX_6699_BIN:
        _, _, _, payload_len, header_size = parse_header(data)
        blob = data[header_size : header_size + payload_len]
        if len(blob) < 12 + GCM_TAG_SIZE:
            return None
        iv = blob[:12]
        tag = blob[-GCM_TAG_SIZE:]
        ciphertext = blob[12:-GCM_TAG_SIZE]
        plaintext = aes_gcm_decrypt(UDP_KEY, ciphertext, iv, tag)
        if len(plaintext) >= 4:
            retcode = struct.unpack(">I", plaintext[:4])[0]
            if retcode in (0, 1, 2, 3):
                plaintext = plaintext[4:]
        text = plaintext.decode("utf-8", errors="ignore").strip()
        return json.loads(text)

    if data[:4] == PREFIX_55AA_BIN:
        return _decode_encrypted_ecb(data)
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


# ─────────────────────────────────────────────
#  TCP port probe (works cross-VLAN)
# ─────────────────────────────────────────────


def _probe_ip(ip: str) -> dict | None:
    """Probe a single IP for a real Tuya device on TCP port 6668.

    Connects, sends a simple DP_QUERY-style probe, and checks if the response
    starts with a valid Tuya prefix (0x000055AA or 0x00006699).
    Only returns a result if the device actually speaks Tuya protocol.
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_PROBE_TIMEOUT)
        result = sock.connect_ex((ip, TCP_PORT))

        if result != 0:
            return None

        # Connection succeeded — now verify it's actually a Tuya device
        # by reading whatever the device sends (Tuya devices often send
        # a heartbeat or respond to connection). If nothing comes, send
        # a minimal probe packet and check the response prefix.
        try:
            # Some Tuya devices send data immediately on connect
            sock.settimeout(1.5)
            data = sock.recv(64)
            if data and _is_tuya_response(data):
                _LOGGER.debug("Tuya device confirmed at %s (auto-response)", ip)
                return _build_tcp_device(ip)
        except (TimeoutError, OSError):
            pass

        # Send a v3.3-style DP_QUERY probe to elicit a response
        try:
            probe = _build_probe_packet()
            sock.sendall(probe)
            sock.settimeout(2.0)
            data = sock.recv(64)
            if data and _is_tuya_response(data):
                _LOGGER.debug("Tuya device confirmed at %s (probe response)", ip)
                return _build_tcp_device(ip)
        except (TimeoutError, OSError):
            pass

        _LOGGER.debug("Port 6668 open at %s but not a Tuya device", ip)
    except OSError:
        pass
    finally:
        if sock:
            import contextlib

            with contextlib.suppress(OSError):
                sock.close()
    return None


def _is_tuya_response(data: bytes) -> bool:
    """Check if data starts with a valid Tuya protocol prefix."""
    if len(data) < 4:
        return False
    return data[:4] in (PREFIX_55AA_BIN, PREFIX_6699_BIN)


def _build_probe_packet() -> bytes:
    """Build a minimal Tuya DP_QUERY packet to probe a device."""
    from .message import DP_QUERY, pack_message

    msg = TuyaMessage(
        seqno=1,
        cmd=DP_QUERY,
        retcode=0,
        payload=b'{"gwId":"","devId":""}',
        crc=0,
        crc_good=True,
    )
    return pack_message(msg)


def _build_tcp_device(ip: str) -> dict:
    """Build a device info dict for a TCP-discovered Tuya device."""
    return {
        "id": "",  # Unknown until user provides credentials
        "ip": ip,
        "version": "unknown",
        "product_key": "",
        "encrypted": True,
        "discovered_via": "tcp_probe",
    }


def _parse_network(network: str) -> list[str]:
    """Parse a network string into a list of host IPs to scan.

    Accepts:
      - CIDR: "192.168.1.0/24"
      - Range: "192.168.1.1-192.168.1.254"
      - Single IP: "192.168.1.100"
    """
    network = network.strip()

    # CIDR notation
    if "/" in network:
        try:
            net = ipaddress.IPv4Network(network, strict=False)
            return [str(ip) for ip in net.hosts()]
        except ValueError:
            pass

    # Range notation: "start-end"
    if "-" in network:
        parts = network.split("-", 1)
        try:
            start = ipaddress.IPv4Address(parts[0].strip())
            end_str = parts[1].strip()

            # Support "192.168.1.1-254" (short form)
            if "." not in end_str:
                base = str(start).rsplit(".", 1)[0]
                end = ipaddress.IPv4Address(f"{base}.{end_str}")
            else:
                end = ipaddress.IPv4Address(end_str)

            ips = []
            current = int(start)
            while current <= int(end):
                ips.append(str(ipaddress.IPv4Address(current)))
                current += 1
            return ips
        except ValueError:
            pass

    # Single IP
    try:
        ipaddress.IPv4Address(network)
        return [network]
    except ValueError:
        pass

    return []


def scan_network(network: str, timeout: float = 30.0) -> list[dict]:
    """Scan a specific network/IP range for Tuya devices via TCP probe.

    Works across VLANs since it uses direct TCP connections, not UDP broadcasts.
    This is a blocking call — run it in an executor for async contexts.
    """
    ips = _parse_network(network)
    if not ips:
        _LOGGER.warning("Invalid network specification: %s", network)
        return []

    _LOGGER.debug("TCP probing %d IPs for Tuya devices", len(ips))
    devices: list[dict] = []

    max_workers = min(TCP_PROBE_MAX_WORKERS, len(ips))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_probe_ip, ip): ip for ip in ips}
        for future in as_completed(futures, timeout=timeout):
            try:
                result = future.result()
                if result:
                    devices.append(result)
            except Exception:
                pass

    return devices


# ─────────────────────────────────────────────
#  Combined scan: UDP broadcast + optional TCP probe
# ─────────────────────────────────────────────


def scan_devices(
    timeout: float = 10.0,
    network: str | None = None,
) -> list[dict]:
    """Scan for Tuya devices.

    1. Always runs UDP broadcast scan on the local network (same subnet).
    2. If `network` is provided, also runs TCP port probe on that range
       (works cross-VLAN: CIDR "192.168.2.0/24", range "10.0.0.1-254",
       or single IP "192.168.2.50").

    Returns a list of dicts with keys: id, ip, version, product_key.
    This is a blocking call — run it in an executor for async contexts.
    """
    devices: dict[str, dict] = {}

    # ── UDP broadcast scan (same network) ──
    sockets: list[tuple[socket.socket, int]] = []

    for port in (UDP_PORT_31, UDP_PORT_33, UDP_PORT_APP):
        sock = _create_udp_socket(port)
        if sock:
            sockets.append((sock, port))

    if sockets:
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
                    port = next(p for s, p in sockets if s is sock)
                    try:
                        data, _addr = sock.recvfrom(4096)
                        broadcast = _decode_broadcast(data, port)
                        if broadcast:
                            info = _extract_device_info(broadcast)
                            if info and info["id"] not in devices:
                                _LOGGER.debug(
                                    "UDP: Discovered %s at %s (v%s)",
                                    info["id"],
                                    info["ip"],
                                    info["version"],
                                )
                                devices[info["id"]] = info
                    except OSError:
                        pass

                elapsed += poll_interval

                if elapsed % 3.0 < poll_interval:
                    for sock, port in sockets:
                        if port == UDP_PORT_APP:
                            _send_discovery_broadcast(sock)
        finally:
            import contextlib

            for sock, _ in sockets:
                with contextlib.suppress(OSError):
                    sock.close()
    else:
        _LOGGER.warning("Could not bind to any UDP discovery port")

    # ── TCP probe scan (cross-VLAN) ──
    if network:
        tcp_devices = scan_network(network, timeout=30.0)
        for dev in tcp_devices:
            # Deduplicate by IP (TCP probe doesn't know device ID)
            if not any(d["ip"] == dev["ip"] for d in devices.values()):
                # Use IP as key since we don't have device ID
                devices[f"tcp_{dev['ip']}"] = dev

    return list(devices.values())
