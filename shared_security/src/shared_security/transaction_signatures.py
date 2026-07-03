from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from shared_security.canonical import canonical_json_bytes


def sign_transaction(tx: dict, private_key: str) -> bytes:
    key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
    return key.sign(canonical_json_bytes(tx))


def verify_transaction(tx: dict, signature: bytes, public_key: str) -> bool:
    key = serialization.load_pem_public_key(public_key.encode("utf-8"))
    try:
        key.verify(signature, canonical_json_bytes(tx))
        return True
    except InvalidSignature:
        return False
