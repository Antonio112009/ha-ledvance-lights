"""Tests for tuya.scanner module."""

import json
import socket
import time

from custom_components.ha_ledvance_lights.tuya.scanner import (
    UDP_PORT_31,
    _extract_device_info,
    _parse_network,
    _udp_listen_for_devices,
)


class TestParseNetwork:
    """Tests for network string parsing."""

    def test_cidr_24(self):
        ips = _parse_network("192.168.1.0/24")
        assert len(ips) == 254
        assert ips[0] == "192.168.1.1"
        assert ips[-1] == "192.168.1.254"

    def test_cidr_28(self):
        ips = _parse_network("192.168.1.0/28")
        assert len(ips) == 14
        assert ips[0] == "192.168.1.1"
        assert ips[-1] == "192.168.1.14"

    def test_cidr_32(self):
        ips = _parse_network("192.168.1.100/32")
        assert ips == ["192.168.1.100"]  # /32 is a single host

    def test_range_short_form(self):
        ips = _parse_network("192.168.1.10-20")
        assert len(ips) == 11
        assert ips[0] == "192.168.1.10"
        assert ips[-1] == "192.168.1.20"

    def test_range_full_form(self):
        ips = _parse_network("10.0.0.5-10.0.0.8")
        assert len(ips) == 4
        assert ips[0] == "10.0.0.5"
        assert ips[-1] == "10.0.0.8"

    def test_single_ip(self):
        ips = _parse_network("192.168.1.100")
        assert ips == ["192.168.1.100"]

    def test_invalid_string(self):
        assert _parse_network("not-an-ip") == []

    def test_empty_string(self):
        assert _parse_network("") == []

    def test_whitespace(self):
        ips = _parse_network("  192.168.1.1  ")
        assert ips == ["192.168.1.1"]

    def test_range_single(self):
        ips = _parse_network("192.168.1.5-5")
        assert ips == ["192.168.1.5"]


class TestExtractDeviceInfo:
    """Tests for broadcast payload extraction."""

    def test_full_broadcast(self):
        broadcast = {
            "gwId": "abc123def456",
            "ip": "192.168.1.50",
            "version": "3.3",
            "productKey": "pk001",
            "encrypt": True,
        }
        info = _extract_device_info(broadcast)
        assert info is not None
        assert info["id"] == "abc123def456"
        assert info["ip"] == "192.168.1.50"
        assert info["version"] == "3.3"
        assert info["product_key"] == "pk001"

    def test_devid_fallback(self):
        broadcast = {"devId": "dev999", "ip": "10.0.0.1"}
        info = _extract_device_info(broadcast)
        assert info["id"] == "dev999"

    def test_missing_id(self):
        broadcast = {"ip": "10.0.0.1"}
        assert _extract_device_info(broadcast) is None

    def test_missing_ip(self):
        broadcast = {"gwId": "abc123"}
        assert _extract_device_info(broadcast) is None

    def test_defaults(self):
        broadcast = {"gwId": "id1", "ip": "1.2.3.4"}
        info = _extract_device_info(broadcast)
        assert info["version"] == "3.3"
        assert info["product_key"] == ""
        assert info["encrypted"] is False


class TestUdpListenLoop:
    """Tests for the shared UDP listen loop."""

    def test_collects_broadcast_and_honours_deadline(self):
        """The loop must decode incoming broadcasts and run the full window.

        Uses an ephemeral localhost socket so no fixed discovery port is
        needed.  Traffic arriving early must not shorten the scan window
        (the old loop counted iterations, not wall-clock time).
        """
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.bind(("127.0.0.1", 0))
        recv_sock.setblocking(False)
        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        payload = json.dumps(
            {"gwId": "scan_test_id", "ip": "192.168.1.50", "version": "3.3"}
        ).encode()

        try:
            send_sock.sendto(payload, recv_sock.getsockname())
            start = time.monotonic()
            devices = _udp_listen_for_devices([(recv_sock, UDP_PORT_31)], timeout=0.4)
            elapsed = time.monotonic() - start
        finally:
            recv_sock.close()
            send_sock.close()

        assert "scan_test_id" in devices
        assert devices["scan_test_id"]["ip"] == "192.168.1.50"
        assert elapsed >= 0.4
