"""Cryptographic helpers for the Tuya protocol."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    """Apply PKCS7 padding."""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS7 padding."""
    pad_len = data[-1]
    if pad_len < 1 or pad_len > 16:
        return data
    if data[-pad_len:] != bytes([pad_len] * pad_len):
        return data
    return data[:-pad_len]


def aes_ecb_encrypt(key: bytes, data: bytes, pad: bool = True) -> bytes:
    """Encrypt data with AES-128-ECB."""
    if pad:
        data = pkcs7_pad(data)
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()


def aes_ecb_decrypt(key: bytes, data: bytes, unpad: bool = True) -> bytes:
    """Decrypt data with AES-128-ECB."""
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    result = decryptor.update(data) + decryptor.finalize()
    if unpad:
        result = pkcs7_unpad(result)
    return result


def aes_gcm_encrypt(
    key: bytes,
    data: bytes,
    iv: bytes | None = None,
    aad: bytes | None = None,
) -> tuple[bytes, bytes, bytes]:
    """Encrypt with AES-128-GCM. Returns (iv, ciphertext, tag)."""
    if iv is None:
        iv = os.urandom(12)
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv))
    encryptor = cipher.encryptor()
    if aad is not None:
        encryptor.authenticate_additional_data(aad)
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return iv, ciphertext, encryptor.tag


def aes_gcm_decrypt(
    key: bytes,
    data: bytes,
    iv: bytes,
    tag: bytes,
    aad: bytes | None = None,
) -> bytes:
    """Decrypt with AES-128-GCM."""
    cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag))
    decryptor = cipher.decryptor()
    if aad is not None:
        decryptor.authenticate_additional_data(aad)
    return decryptor.update(data) + decryptor.finalize()
