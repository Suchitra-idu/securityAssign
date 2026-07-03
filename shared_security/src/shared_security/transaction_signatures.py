import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization


def _canonical(tx: dict) -> bytes:
    return json.dumps(tx, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_transaction(tx: dict, private_key: str) -> bytes:
    key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
    return key.sign(_canonical(tx))


def verify_transaction(tx: dict, signature: bytes, public_key: str) -> bool:
    key = serialization.load_pem_public_key(public_key.encode("utf-8"))
    try:
        key.verify(signature, _canonical(tx))
        return True
    except InvalidSignature:
        return False
