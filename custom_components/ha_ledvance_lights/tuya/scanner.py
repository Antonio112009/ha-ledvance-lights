"""UDP broadcast scanner and TCP probe scanner for Tuya devices."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import platform
import re
import select
import socket
import struct
import subprocess
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

    Connects, sends a DP_QUERY probe, and checks if the response is valid Tuya
    protocol. Extracts version and device ID when possible.
    """
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_PROBE_TIMEOUT)
        result = sock.connect_ex((ip, TCP_PORT))

        if result != 0:
            return None

        # Try to read auto-response (some devices send data on connect)
        try:
            sock.settimeout(1.5)
            data = sock.recv(1024)
            if data and _is_tuya_response(data):
                _LOGGER.debug("Tuya device confirmed at %s (auto-response)", ip)
                return _build_tcp_device(ip, data)
        except (TimeoutError, OSError):
            pass

        # Send a v3.3-style DP_QUERY probe to elicit a response
        try:
            probe = _build_probe_packet()
            sock.sendall(probe)
            sock.settimeout(2.0)
            data = sock.recv(1024)
            if data and _is_tuya_response(data):
                _LOGGER.debug("Tuya device confirmed at %s (probe response)", ip)
                return _build_tcp_device(ip, data)
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


def _detect_version_from_response(data: bytes) -> str:
    """Detect protocol version from a raw Tuya TCP response.

    Uses structural clues since the payload itself is encrypted:
    - 0x6699 prefix → v3.5
    - 0x55AA with payload_len indicating HMAC footer (36-byte) → v3.4
    - 0x55AA with payload_len indicating CRC footer (8-byte) → v3.3
    - Version string "3.x" at payload offset → explicit version
    """
    if len(data) < 16:
        return ""

    # v3.5 uses a completely different prefix
    if data[:4] == PREFIX_6699_BIN:
        return "3.5"

    if data[:4] != PREFIX_55AA_BIN:
        return ""

    # Check for explicit version string at payload start (offset 16)
    if len(data) > 19:
        ver_bytes = data[16:19]
        if ver_bytes in (b"3.3", b"3.4", b"3.5"):
            return ver_bytes.decode()

    # Infer from footer size: parse the header to get payload_len,
    # then check if total message matches CRC footer (v3.3) or HMAC (v3.4)
    try:
        _, _, _, payload_len, header_size = parse_header(data)
        total_len = header_size + payload_len
        actual_len = len(data)
        suffix_55aa = struct.pack(">I", 0x0000AA55)

        if actual_len == total_len and data[-4:] == suffix_55aa:
            # CRC footer (v3.3): 4-byte CRC + 4-byte suffix = 8
            encrypted_len = payload_len - 8
            if encrypted_len > 0 and encrypted_len % 16 == 0:
                return "3.3"
            # HMAC footer (v3.4): 32-byte HMAC + 4-byte suffix = 36
            if payload_len - 36 > 0:
                return "3.4"
    except (DecodeError, struct.error):
        pass

    return ""


def _extract_info_from_response(data: bytes) -> dict:
    """Extract device info from a raw Tuya TCP response.

    Returns a dict with whatever we can determine: version, device_id.
    """
    info: dict[str, str] = {}

    # Detect version from response structure
    ver = _detect_version_from_response(data)
    if ver:
        info["version"] = ver

    # Try to find a JSON payload with gwId/devId (works for unencrypted
    # or plaintext error responses)
    try:
        text = data.decode("latin-1")
        for marker in ('"gwId"', '"devId"'):
            idx = text.find(marker)
            if idx >= 0:
                start = text.rfind("{", 0, idx)
                end = text.find("}", idx)
                if start >= 0 and end >= 0:
                    snippet = text[start : end + 1]
                    try:
                        parsed = json.loads(snippet)
                        dev_id = parsed.get("gwId") or parsed.get("devId", "")
                        if dev_id:
                            info["id"] = dev_id
                        break
                    except json.JSONDecodeError:
                        pass
    except (UnicodeDecodeError, ValueError):
        pass

    return info


def _build_probe_packet() -> bytes:
    """Build a minimal Tuya DP_QUERY packet to probe a device."""
    from .message import DP_QUERY

    msg = TuyaMessage(
        seqno=1,
        cmd=DP_QUERY,
        retcode=0,
        payload=b'{"gwId":"","devId":""}',
        crc=0,
        crc_good=True,
    )
    return pack_message(msg)


def _build_tcp_device(ip: str, raw_response: bytes | None = None) -> dict:
    """Build a device info dict for a TCP-discovered Tuya device.

    Tries to extract version and device ID from the raw response data.
    """
    device: dict = {
        "id": "",
        "ip": ip,
        "version": "unknown",
        "product_key": "",
        "encrypted": True,
        "discovered_via": "tcp_probe",
    }

    if raw_response:
        extracted = _extract_info_from_response(raw_response)
        if extracted.get("version"):
            device["version"] = extracted["version"]
        if extracted.get("id"):
            device["id"] = extracted["id"]

    return device


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
#  MAC address resolution via ARP table
# ─────────────────────────────────────────────

# MAC address regex: xx:xx:xx:xx:xx:xx or xx-xx-xx-xx-xx-xx
_MAC_RE = re.compile(r"([0-9a-fA-F]{1,2}[:\-]){5}[0-9a-fA-F]{1,2}")


def _get_arp_table() -> dict[str, str]:
    """Read the system ARP table and return a mapping of IP → MAC address.

    Works on macOS, Linux, and Windows.
    """
    arp_map: dict[str, str] = {}
    system = platform.system()

    try:
        if system == "Linux":
            # /proc/net/arp is the fastest source on Linux
            try:
                with open("/proc/net/arp") as f:
                    for line in f.readlines()[1:]:  # skip header
                        parts = line.split()
                        if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                            arp_map[parts[0]] = parts[3].lower()
            except FileNotFoundError:
                # Fallback to arp command
                result = subprocess.run(
                    ["arp", "-n"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                for line in result.stdout.splitlines():
                    parts = line.split()
                    if len(parts) >= 3:
                        mac_match = _MAC_RE.search(line)
                        if mac_match:
                            ip = parts[0]
                            mac = mac_match.group().lower().replace("-", ":")
                            if mac != "00:00:00:00:00:00":
                                arp_map[ip] = mac
        else:
            # macOS / Windows: use `arp -a`
            result = subprocess.run(
                ["arp", "-a"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                mac_match = _MAC_RE.search(line)
                if not mac_match:
                    continue
                mac = mac_match.group().lower().replace("-", ":")
                if mac == "ff:ff:ff:ff:ff:ff" or mac == "00:00:00:00:00:00":
                    continue
                # Extract IP: look for (x.x.x.x) or just x.x.x.x
                ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", line)
                if ip_match:
                    arp_map[ip_match.group(1)] = mac
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _LOGGER.debug("Failed to read ARP table: %s", exc)

    return arp_map


def _normalize_mac(mac: str) -> str:
    """Normalize a MAC address to colon-separated lowercase with zero-padding.

    e.g., "a:b:c:d:e:f" → "0a:0b:0c:0d:0e:0f"
    """
    parts = mac.replace("-", ":").split(":")
    return ":".join(p.zfill(2) for p in parts).lower()


def resolve_mac_addresses(devices: list[dict]) -> list[dict]:
    """Enrich a list of device dicts with MAC addresses from the ARP table.

    For cross-VLAN devices (not in the local ARP table), the MAC field
    will be empty since ARP is a Layer 2 protocol and can't resolve
    addresses across routed networks.
    """
    arp_table = _get_arp_table()

    # Determine local subnets so we can tell cross-VLAN apart
    local_subnets = _get_local_subnets()

    for dev in devices:
        ip = dev.get("ip", "")
        mac = arp_table.get(ip, "")
        dev["mac"] = _normalize_mac(mac) if mac else ""
        # Mark cross-VLAN devices so the UI can explain why MAC is missing
        if not mac and ip:
            is_local = any(_ip_in_subnet(ip, net, mask) for net, mask in local_subnets)
            dev["cross_vlan"] = not is_local

    return devices


def _get_local_subnets() -> list[tuple[str, str]]:
    """Get local network interfaces and their subnets.

    Returns a list of (network_address, netmask) tuples.
    """
    subnets: list[tuple[str, str]] = []
    try:
        import array
        import fcntl

        # Linux: use ioctl to get interface addresses
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Get list of interfaces
        max_possible = 128
        buf = array.array("B", b"\0" * max_possible * 40)
        # SIOCGIFCONF
        result = fcntl.ioctl(
            sock.fileno(),
            0x8912,
            struct.pack("iL", max_possible * 40, buf.buffer_info()[0]),
        )
        out_bytes = struct.unpack("iL", result)[0]
        data = buf.tobytes()[:out_bytes]
        offset = 0
        while offset < len(data):
            name = data[offset : offset + 16].split(b"\0", 1)[0]
            ip_bytes = data[offset + 20 : offset + 24]
            ip_addr = socket.inet_ntoa(ip_bytes)
            # Get netmask via SIOCGIFNETMASK
            try:
                mask_result = fcntl.ioctl(
                    sock.fileno(),
                    0x891B,
                    struct.pack("256s", name),
                )
                mask = socket.inet_ntoa(mask_result[20:24])
                subnets.append((ip_addr, mask))
            except OSError:
                pass
            offset += 40
        sock.close()
    except (ImportError, OSError):
        # macOS / fallback: parse ifconfig output
        try:
            result = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            current_ip = ""
            for line in result.stdout.splitlines():
                inet_match = re.search(
                    r"inet (\d+\.\d+\.\d+\.\d+).*?netmask\s+(0x[0-9a-f]+|\d+\.\d+\.\d+\.\d+)",
                    line,
                )
                if inet_match:
                    current_ip = inet_match.group(1)
                    mask_str = inet_match.group(2)
                    if mask_str.startswith("0x"):
                        # macOS hex netmask: 0xffffff00
                        mask_int = int(mask_str, 16)
                        mask = socket.inet_ntoa(struct.pack(">I", mask_int))
                    else:
                        mask = mask_str
                    if current_ip != "127.0.0.1":
                        subnets.append((current_ip, mask))
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    return subnets


def _ip_in_subnet(ip: str, network_ip: str, netmask: str) -> bool:
    """Check if an IP address is within a subnet."""
    try:
        ip_int = struct.unpack(">I", socket.inet_aton(ip))[0]
        net_int = struct.unpack(">I", socket.inet_aton(network_ip))[0]
        mask_int = struct.unpack(">I", socket.inet_aton(netmask))[0]
        return (ip_int & mask_int) == (net_int & mask_int)
    except (OSError, struct.error):
        return False


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

    result = list(devices.values())

    # Ping discovered IPs to populate the ARP table, then resolve MACs
    _ping_ips([d["ip"] for d in result])
    resolve_mac_addresses(result)

    return result


def _ping_ips(ips: list[str]) -> None:
    """Send a single ping to each IP to populate the ARP table.

    Uses concurrent execution for speed. Failures are silently ignored
    since the only purpose is to populate the ARP cache.
    """
    if not ips:
        return

    system = platform.system()
    count_flag = "-c" if system != "Windows" else "-n"
    timeout_flag = "-W" if system == "Linux" else "-t" if system == "Windows" else "-W"
    # macOS -W uses milliseconds, Linux uses seconds
    timeout_val = "500" if system == "Darwin" else "1"

    def _ping_one(ip: str) -> None:
        import contextlib

        with contextlib.suppress(subprocess.TimeoutExpired, FileNotFoundError, OSError):
            subprocess.run(
                ["ping", count_flag, "1", timeout_flag, timeout_val, ip],
                capture_output=True,
                timeout=2,
            )

    with ThreadPoolExecutor(max_workers=min(20, len(ips))) as executor:
        list(executor.map(_ping_one, ips))
