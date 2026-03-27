"""Tests for tuya.crypto module."""

import os

import pytest

from custom_components.ha_ledvance_lights.tuya.crypto import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    aes_gcm_decrypt,
    aes_gcm_encrypt,
    pkcs7_pad,
    pkcs7_unpad,
)


class TestPKCS7:
    """Tests for PKCS7 padding."""

    def test_pad_full_block(self):
        data = b"0123456789abcdef"  # 16 bytes — needs full padding block
        padded = pkcs7_pad(data)
        assert len(padded) == 32
        assert padded[-1] == 16

    def test_pad_partial(self):
        data = b"hello"  # 5 bytes — needs 11 bytes padding
        padded = pkcs7_pad(data)
        assert len(padded) == 16
        assert padded[-1] == 11

    def test_pad_single_byte(self):
        data = b"x" * 15  # 15 bytes — needs 1 byte padding
        padded = pkcs7_pad(data)
        assert len(padded) == 16
        assert padded[-1] == 1

    def test_unpad_reverses_pad(self):
        data = b"hello world"
        assert pkcs7_unpad(pkcs7_pad(data)) == data

    def test_unpad_invalid_padding_returns_data(self):
        data = b"no valid padding"
        assert pkcs7_unpad(data) == data

    def test_pad_empty(self):
        padded = pkcs7_pad(b"")
        assert len(padded) == 16
        assert padded == bytes([16] * 16)


class TestAESECB:
    """Tests for AES-ECB encryption/decryption."""

    KEY = b"0123456789abcdef"

    def test_roundtrip(self):
        plaintext = b"Hello, Tuya!"
        encrypted = aes_ecb_encrypt(self.KEY, plaintext)
        decrypted = aes_ecb_decrypt(self.KEY, encrypted)
        assert decrypted == plaintext

    def test_roundtrip_exact_block(self):
        plaintext = b"exactly16bytes!!"
        encrypted = aes_ecb_encrypt(self.KEY, plaintext)
        decrypted = aes_ecb_decrypt(self.KEY, encrypted)
        assert decrypted == plaintext

    def test_roundtrip_multi_block(self):
        plaintext = b"A" * 100
        encrypted = aes_ecb_encrypt(self.KEY, plaintext)
        decrypted = aes_ecb_decrypt(self.KEY, encrypted)
        assert decrypted == plaintext

    def test_no_padding(self):
        plaintext = b"exactly16bytes!!"  # 16 bytes
        encrypted = aes_ecb_encrypt(self.KEY, plaintext, pad=False)
        assert len(encrypted) == 16
        decrypted = aes_ecb_decrypt(self.KEY, encrypted, unpad=False)
        assert decrypted == plaintext

    def test_wrong_key_produces_garbage(self):
        plaintext = b"secret data here"
        encrypted = aes_ecb_encrypt(self.KEY, plaintext)
        wrong_key = b"wrongkey12345678"
        decrypted = aes_ecb_decrypt(wrong_key, encrypted)
        assert decrypted != plaintext

    def test_empty_plaintext(self):
        encrypted = aes_ecb_encrypt(self.KEY, b"")
        decrypted = aes_ecb_decrypt(self.KEY, encrypted)
        assert decrypted == b""


class TestAESGCM:
    """Tests for AES-GCM encryption/decryption."""

    KEY = b"0123456789abcdef"

    def test_roundtrip(self):
        plaintext = b"Hello, GCM!"
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext)
        decrypted = aes_gcm_decrypt(self.KEY, ciphertext, iv, tag)
        assert decrypted == plaintext

    def test_roundtrip_with_aad(self):
        plaintext = b"authenticated data"
        aad = b"additional header"
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext, aad=aad)
        decrypted = aes_gcm_decrypt(self.KEY, ciphertext, iv, tag, aad=aad)
        assert decrypted == plaintext

    def test_wrong_aad_fails(self):
        plaintext = b"authenticated data"
        aad = b"correct header"
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext, aad=aad)
        with pytest.raises((ValueError, Exception)):
            aes_gcm_decrypt(self.KEY, ciphertext, iv, tag, aad=b"wrong header")

    def test_tampered_ciphertext_fails(self):
        plaintext = b"tamper test"
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext)
        tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
        with pytest.raises((ValueError, Exception)):
            aes_gcm_decrypt(self.KEY, tampered, iv, tag)

    def test_custom_iv(self):
        plaintext = b"custom iv test"
        custom_iv = b"\x01" * 12
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext, iv=custom_iv)
        assert iv == custom_iv
        decrypted = aes_gcm_decrypt(self.KEY, ciphertext, iv, tag)
        assert decrypted == plaintext

    def test_random_iv_is_unique(self):
        plaintext = b"random iv"
        iv1, _, _ = aes_gcm_encrypt(self.KEY, plaintext)
        iv2, _, _ = aes_gcm_encrypt(self.KEY, plaintext)
        assert iv1 != iv2  # IVs should be random

    def test_empty_plaintext(self):
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, b"")
        decrypted = aes_gcm_decrypt(self.KEY, ciphertext, iv, tag)
        assert decrypted == b""

    def test_large_plaintext(self):
        plaintext = os.urandom(4096)
        iv, ciphertext, tag = aes_gcm_encrypt(self.KEY, plaintext)
        decrypted = aes_gcm_decrypt(self.KEY, ciphertext, iv, tag)
        assert decrypted == plaintext
