"""Tuya local device communication."""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import time
from typing import Any

from .crypto import aes_ecb_decrypt, aes_ecb_encrypt, aes_gcm_encrypt
from .message import (
    CONTROL,
    CONTROL_NEW,
    DP_QUERY,
    DP_QUERY_NEW,
    FOOTER_55AA,
    FOOTER_6699,
    FOOTER_HMAC,
    HEADER_SIZE_55AA,
    HEADER_SIZE_6699,
    NO_PROTOCOL_HEADER_CMDS,
    PREFIX_55AA,
    PREFIX_6699,
    PREFIX_55AA_BIN,
    PREFIX_6699_BIN,
    PROTOCOL_33_HEADER,
    PROTOCOL_34_HEADER,
    PROTOCOL_35_HEADER,
    SESS_KEY_NEG_FINISH,
    SESS_KEY_NEG_START,
    DecodeError,
    TuyaMessage,
    _hmac_sha256,
    pack_message,
    parse_header,
    unpack_message,
)

_LOGGER = logging.getLogger(__name__)

TUYA_PORT = 6668

# Error codes (matching TinyTuya format for compatibility)
ERR_CONNECT = "901"
ERR_TIMEOUT = "902"
ERR_PAYLOAD = "904"
ERR_OFFLINE = "905"
ERR_KEY_OR_VER = "914"


def _error_json(code: str, msg: str = "") -> dict:
    """Build an error response dict."""
    messages = {
        ERR_CONNECT: "Network Error: Unable to Connect",
        ERR_TIMEOUT: "Timeout Waiting for Device",
        ERR_PAYLOAD: "Unexpected Payload from Device",
        ERR_OFFLINE: "Network Error: Device Unreachable",
        ERR_KEY_OR_VER: "Check device key or version",
    }
    return {
        "Error": msg or messages.get(code, "Unknown Error"),
        "Err": code,
        "Payload": "",
    }


class TuyaDevice:
    """Communicate with a Tuya device over the local network."""

    def __init__(
        self,
        dev_id: str,
        address: str,
        local_key: str,
        version: str = "3.3",
    ) -> None:
        self.dev_id = dev_id
        self.address = address
        self.local_key = local_key.encode("latin1")
        self.version = float(version)

        self._socket: socket.socket | None = None
        self._session_key: bytes | None = None
        self._seqno = 1
        self._timeout = 5
        self._retry_limit = 1

        # Version-specific header
        self._version_header = self._get_version_header()

    def set_version(self, version: float) -> None:
        """Set the protocol version."""
        self.version = version
        self._version_header = self._get_version_header()

    def set_socketTimeout(self, timeout: int) -> None:
        """Set socket timeout in seconds."""
        self._timeout = timeout

    def set_socketRetryLimit(self, limit: int) -> None:
        """Set socket retry limit."""
        self._retry_limit = limit

    def _get_version_header(self) -> bytes:
        if self.version >= 3.5:
            return PROTOCOL_35_HEADER
        if self.version >= 3.4:
            return PROTOCOL_34_HEADER
        return PROTOCOL_33_HEADER

    @property
    def _encrypt_key(self) -> bytes:
        """Return the key used for payload encryption."""
        return self._session_key or self.local_key

    # ─────────────────────────────────────────
    #  Connection
    # ─────────────────────────────────────────

    def _connect(self) -> bool:
        """Open TCP connection and negotiate session key if needed."""
        self._close()
        self._session_key = None

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(self._timeout)
            sock.connect((self.address, TUYA_PORT))
            self._socket = sock
        except socket.timeout:
            return False
        except OSError:
            return False

        # Session key negotiation for v3.4+
        if self.version >= 3.4:
            if not self._negotiate_session_key():
                self._close()
                return False

        return True

    def _close(self) -> None:
        """Close the socket."""
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None

    def _negotiate_session_key(self) -> bool:
        """Three-step session key handshake for v3.4+."""
        try:
            local_nonce = os.urandom(16)

            # Step 1: Send local nonce
            msg = TuyaMessage(
                seqno=self._next_seqno(),
                cmd=SESS_KEY_NEG_START,
                retcode=0,
                payload=local_nonce,
                crc=0,
                crc_good=True,
                prefix=PREFIX_55AA if self.version < 3.5 else PREFIX_6699,
            )
            self._send_raw(pack_message(msg, hmac_key=self.local_key))

            # Step 2: Receive remote nonce
            response = self._receive_raw()
            if response is None:
                return False

            payload = response.payload
            if self.version < 3.5:
                # v3.4: payload is encrypted with local_key
                try:
                    payload = aes_ecb_decrypt(self.local_key, payload, unpad=False)
                except Exception:
                    return False

            if len(payload) < 48:
                return False

            remote_nonce = payload[:16]
            remote_hmac = payload[16:48]

            # Verify HMAC
            expected_hmac = _hmac_sha256(self.local_key, local_nonce)
            if remote_hmac != expected_hmac:
                _LOGGER.debug("Session key HMAC verification failed")
                return False

            # Step 3: Send our HMAC of remote nonce
            our_hmac = _hmac_sha256(self.local_key, remote_nonce)
            msg = TuyaMessage(
                seqno=self._next_seqno(),
                cmd=SESS_KEY_NEG_FINISH,
                retcode=0,
                payload=our_hmac,
                crc=0,
                crc_good=True,
                prefix=PREFIX_55AA if self.version < 3.5 else PREFIX_6699,
            )
            self._send_raw(pack_message(msg, hmac_key=self.local_key))

            # Derive session key: XOR nonces then encrypt
            xored = bytes(a ^ b for a, b in zip(local_nonce, remote_nonce))

            if self.version >= 3.5:
                _, ct, _ = aes_gcm_encrypt(
                    self.local_key, xored, iv=local_nonce[:12]
                )
                self._session_key = ct[12:28] if len(ct) >= 28 else ct[:16]
            else:
                self._session_key = aes_ecb_encrypt(
                    self.local_key, xored, pad=False
                )

            return True

        except (OSError, DecodeError) as exc:
            _LOGGER.debug("Session negotiation failed: %s", exc)
            return False

    # ─────────────────────────────────────────
    #  Low-level I/O
    # ─────────────────────────────────────────

    def _next_seqno(self) -> int:
        seq = self._seqno
        self._seqno += 1
        return seq

    def _send_raw(self, data: bytes) -> None:
        """Send raw bytes over the socket."""
        if self._socket is None:
            raise OSError("Not connected")
        self._socket.sendall(data)

    def _receive_raw(self) -> TuyaMessage | None:
        """Read and unpack a single message from the socket."""
        if self._socket is None:
            return None

        try:
            # Read enough for a header
            data = self._recv_bytes(32)
            if not data:
                return None

            # Find prefix
            prefix_offset = -1
            for i in range(len(data) - 3):
                if data[i : i + 4] in (PREFIX_55AA_BIN, PREFIX_6699_BIN):
                    prefix_offset = i
                    break

            if prefix_offset < 0:
                return None

            data = data[prefix_offset:]

            # Parse header to find total length
            prefix, seqno, cmd, payload_len, header_size = parse_header(data)

            if prefix == PREFIX_6699:
                total_len = header_size + payload_len + FOOTER_6699
            elif self._session_key and self.version >= 3.4:
                total_len = header_size + payload_len
            else:
                total_len = header_size + payload_len

            # Read more if needed
            if len(data) < total_len:
                remaining = self._recv_bytes(total_len - len(data))
                if remaining:
                    data = data + remaining

            # Determine HMAC key for unpacking
            hmac_key = None
            if prefix == PREFIX_6699:
                hmac_key = self._encrypt_key
            elif self._session_key and self.version >= 3.4:
                hmac_key = self._session_key

            return unpack_message(data, hmac_key=hmac_key)

        except (OSError, DecodeError) as exc:
            _LOGGER.debug("Receive error: %s", exc)
            return None

    def _recv_bytes(self, num_bytes: int) -> bytes:
        """Read exactly num_bytes from socket, or as many as available."""
        if self._socket is None:
            return b""
        data = b""
        try:
            while len(data) < num_bytes:
                chunk = self._socket.recv(num_bytes - len(data))
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        return data

    # ─────────────────────────────────────────
    #  Payload encoding / decoding
    # ─────────────────────────────────────────

    def _build_payload(self, cmd: int, data: dict | None = None) -> tuple[int, bytes]:
        """Build JSON payload for a command. Returns (wire_cmd, payload_bytes)."""
        ts = str(int(time.time()))

        if self.version >= 3.4:
            if cmd == CONTROL:
                payload = {
                    "protocol": 5,
                    "t": int(ts),
                    "data": {"dps": data},
                }
                return CONTROL_NEW, json.dumps(payload).encode()
            if cmd == DP_QUERY:
                return DP_QUERY_NEW, b"{}"
        else:
            if cmd == CONTROL:
                payload = {
                    "devId": self.dev_id,
                    "uid": self.dev_id,
                    "t": ts,
                    "dps": data,
                }
                return CONTROL, json.dumps(payload).encode()
            if cmd == DP_QUERY:
                payload = {
                    "gwId": self.dev_id,
                    "devId": self.dev_id,
                    "uid": self.dev_id,
                    "t": ts,
                }
                return DP_QUERY, json.dumps(payload).encode()

        return cmd, json.dumps(data or {}).encode()

    def _encrypt_payload(self, cmd: int, payload: bytes) -> bytes:
        """Encrypt and frame the payload for the wire."""
        key = self._encrypt_key

        if self.version >= 3.5:
            # v3.5: GCM encryption via pack_message
            if cmd not in NO_PROTOCOL_HEADER_CMDS:
                payload = self._version_header + payload
            msg = TuyaMessage(
                seqno=self._next_seqno(),
                cmd=cmd,
                retcode=0,
                payload=payload,
                crc=0,
                crc_good=True,
                prefix=PREFIX_6699,
                iv=os.urandom(12),
            )
            return pack_message(msg, hmac_key=key)

        if self.version >= 3.4:
            # v3.4: ECB with session key + HMAC
            if cmd not in NO_PROTOCOL_HEADER_CMDS:
                payload = self._version_header + payload
            encrypted = aes_ecb_encrypt(key, payload)
            msg = TuyaMessage(
                seqno=self._next_seqno(),
                cmd=cmd,
                retcode=0,
                payload=encrypted,
                crc=0,
                crc_good=True,
            )
            return pack_message(msg, hmac_key=key)

        # v3.3 and below: ECB with local_key + CRC
        encrypted = aes_ecb_encrypt(self.local_key, payload)
        if cmd not in NO_PROTOCOL_HEADER_CMDS:
            encrypted = self._version_header + encrypted
        msg = TuyaMessage(
            seqno=self._next_seqno(),
            cmd=cmd,
            retcode=0,
            payload=encrypted,
            crc=0,
            crc_good=True,
        )
        return pack_message(msg)

    def _decrypt_payload(self, msg: TuyaMessage) -> dict:
        """Decrypt message payload and parse JSON."""
        payload = msg.payload
        key = self._encrypt_key

        if not payload:
            return {}

        try:
            if msg.prefix == PREFIX_6699:
                # v3.5: already decrypted by unpack_message
                pass
            elif self.version >= 3.4 and self._session_key:
                # v3.4: ECB decrypt with session key
                payload = aes_ecb_decrypt(key, payload)
            else:
                # v3.3: strip version header, then ECB decrypt
                if payload[:3] in (b"3.3", b"3.4", b"3.5"):
                    payload = payload[15:]
                payload = aes_ecb_decrypt(self.local_key, payload)

            # Strip version header if still present
            if payload[:3] in (b"3.3", b"3.4", b"3.5"):
                payload = payload[15:]

            # Strip retcode if present
            if len(payload) >= 4:
                retcode = struct.unpack(">I", payload[:4])[0]
                if retcode in (0, 1, 2, 3):
                    payload = payload[4:]

            # Parse JSON
            text = payload.decode("utf-8", errors="ignore").strip()
            if not text:
                return {}

            result = json.loads(text)

            # Promote nested data.dps to top-level dps (v3.4+ format)
            if "data" in result and "dps" in result.get("data", {}):
                result["dps"] = result["data"]["dps"]

            return result

        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            _LOGGER.debug("Payload decode error: %s", exc)
            return {}

    # ─────────────────────────────────────────
    #  Send / Receive
    # ─────────────────────────────────────────

    def _send_receive(self, cmd: int, data: dict | None = None) -> dict:
        """Connect, send command, receive response, close. Returns parsed dict."""
        for attempt in range(self._retry_limit + 1):
            try:
                if not self._connect():
                    if attempt < self._retry_limit:
                        continue
                    return _error_json(ERR_OFFLINE)

                wire_cmd, payload = self._build_payload(cmd, data)
                raw = self._encrypt_payload(wire_cmd, payload)
                self._send_raw(raw)

                # Read response(s) — skip heartbeat ACKs
                response = None
                for _ in range(3):
                    msg = self._receive_raw()
                    if msg is None:
                        break
                    # Skip empty ACKs and heartbeats
                    if msg.cmd == SESS_KEY_NEG_FINISH:
                        continue
                    if msg.payload:
                        response = msg
                        break

                self._close()

                if response is None:
                    if attempt < self._retry_limit:
                        continue
                    return _error_json(ERR_PAYLOAD)

                result = self._decrypt_payload(response)
                if result:
                    return result
                if attempt < self._retry_limit:
                    continue
                return _error_json(ERR_PAYLOAD)

            except socket.timeout:
                self._close()
                if attempt < self._retry_limit:
                    continue
                return _error_json(ERR_OFFLINE)
            except OSError:
                self._close()
                if attempt < self._retry_limit:
                    continue
                return _error_json(ERR_CONNECT)

        return _error_json(ERR_KEY_OR_VER)

    # ─────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────

    def status(self) -> dict:
        """Query device status. Returns dict with 'dps' key or error dict."""
        return self._send_receive(DP_QUERY)

    def set_status(self, on: bool, switch: int = 1) -> dict:
        """Set a boolean status (e.g., power on/off)."""
        return self._send_receive(CONTROL, {str(switch): on})

    def set_value(self, index: int, value: Any) -> dict:
        """Set a single DP value."""
        return self._send_receive(CONTROL, {str(index): value})

    def set_multiple_values(self, data: dict[str, Any]) -> dict:
        """Set multiple DP values at once."""
        return self._send_receive(CONTROL, data)
