import pytest

from shared_security.field_crypto import (
    DecryptionError,
    decrypt_field,
    encrypt_field,
    generate_field_key,
)


@pytest.fixture
def key():
    return generate_field_key()


def test_round_trip_returns_plaintext(key):
    plaintext = b"card-number-4111111111111111"
    assert decrypt_field(encrypt_field(plaintext, key), key) == plaintext


def test_fresh_nonce_per_call(key):
    assert encrypt_field(b"same input", key) != encrypt_field(b"same input", key)


def test_tampered_ciphertext_fails(key):
    ct = encrypt_field(b"secret", key)
    tampered = ct[:-1] + bytes([ct[-1] ^ 0x01])
    with pytest.raises(DecryptionError):
        decrypt_field(tampered, key)


def test_wrong_key_fails(key):
    ct = encrypt_field(b"secret", key)
    with pytest.raises(DecryptionError):
        decrypt_field(ct, generate_field_key())
