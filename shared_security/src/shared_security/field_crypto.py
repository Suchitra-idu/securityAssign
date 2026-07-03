import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12


class DecryptionError(Exception):
    pass


def generate_field_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt_field(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(_NONCE_SIZE)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_field(blob: bytes, key: bytes) -> bytes:
    nonce, ciphertext = blob[:_NONCE_SIZE], blob[_NONCE_SIZE:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise DecryptionError("field decryption failed") from exc
