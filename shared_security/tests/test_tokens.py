import base64
import hashlib
import hmac
import json
import time

import pytest

from shared_security.tokens import (
    TokenError,
    generate_signing_keypair,
    sign_token,
    verify_token,
)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _forge_hs256(claims: dict, secret: str) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps(claims).encode())
    signing_input = f"{header}.{payload}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"


def _claims(**overrides):
    base = {"sub": "user-1", "role": "customer", "exp": int(time.time()) + 60}
    base.update(overrides)
    return base


def test_round_trip_preserves_claims(keypair):
    priv, pub = keypair
    claims = _claims()
    verified = verify_token(sign_token(claims, priv), pub)
    assert verified["sub"] == claims["sub"]
    assert verified["role"] == claims["role"]
    assert verified["exp"] == claims["exp"]


def test_forged_token_fails_verification(keypair):
    _, pub = keypair
    attacker_priv, _ = generate_signing_keypair()
    forged = sign_token(_claims(), attacker_priv)
    with pytest.raises(TokenError):
        verify_token(forged, pub)


def test_tampered_payload_fails(keypair):
    priv, pub = keypair
    token = sign_token(_claims(), priv)
    tampered = token[:-4] + "AAAA"
    with pytest.raises(TokenError):
        verify_token(tampered, pub)


def test_expired_token_fails(keypair):
    priv, pub = keypair
    expired = sign_token(_claims(exp=int(time.time()) - 1), priv)
    with pytest.raises(TokenError):
        verify_token(expired, pub)


def test_algorithm_confusion_hs256_rejected(keypair):
    # Classic JWT attack: attacker crafts an HS256 token using the public key
    # as the HMAC secret. verify_token must pin the asymmetric algorithm and
    # reject anything else, regardless of the token header's alg claim. The
    # forgery is built by hand because modern PyJWT refuses to encode HS256
    # with a PEM key on the encode side.
    _, pub = keypair
    forged = _forge_hs256(_claims(), pub)
    with pytest.raises(TokenError):
        verify_token(forged, pub)
