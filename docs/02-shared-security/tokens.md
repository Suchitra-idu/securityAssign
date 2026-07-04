# Tokens (Ed25519 JWT)

Asymmetric-signed JSON Web Tokens. Auth mints, banking verifies.

## API

```python
ALGORITHM = "EdDSA"

class TokenError(Exception): ...

def generate_signing_keypair() -> tuple[str, str]      # (private_pem, public_pem)
def sign_token(claims: dict, private_key: str) -> str  # returns compact JWT
def verify_token(token: str, public_key: str) -> dict  # raises TokenError on any failure
```

Implementation: {{ src("shared_security/src/shared_security/tokens.py") }}.

## Why Ed25519 (EdDSA)

- **Asymmetric** — auth can hold the private key; banking gets only the public key and can verify but never mint. That is what makes tokens trustable across the service boundary.
- **Small keys and signatures** — 32-byte public key, 64-byte signature. Faster to serialise and cache than RSA.
- **No parameter choices to get wrong.** Unlike RSA and ECDSA, EdDSA has no curve-and-hash tuple to misconfigure. There is one curve (Ed25519), one hash (SHA-512 internally), no encoding options to trip on.
- **Deterministic signatures.** EdDSA does not rely on per-signature randomness the way ECDSA does, so a poor RNG cannot leak the key.

## Key format

PEM-encoded strings. `generate_signing_keypair()` returns:

- **Private key** — PKCS#8, unencrypted PEM (`-----BEGIN PRIVATE KEY-----`).
- **Public key** — SubjectPublicKeyInfo PEM (`-----BEGIN PUBLIC KEY-----`).

Both are `str`, so they round-trip through env vars, JSON, and databases without binary handling.

Storage guidance for callers:
- **Private key** — env var or Docker secret. Never checked into git, never sent to another service. The auth service is the only holder.
- **Public key** — freely distributable. Auth exposes it at `GET /public-key`; banking caches it locally.

## Signing

```python
def sign_token(claims: dict, private_key: str) -> str:
    return jwt.encode(claims, private_key, algorithm=ALGORITHM)
```

Uses PyJWT with the algorithm pinned. The resulting compact JWT is three base64url segments: `header.payload.signature`. Header always looks like `{"alg":"EdDSA","typ":"JWT"}`.

Callers are responsible for the claim shape. See {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md#contract-2-token-payload", anchor="contract-2-token-payload") }} for the auth-service payload.

## Verification

```python
def verify_token(token: str, public_key: str) -> dict:
    try:
        return jwt.decode(token, public_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
```

Two important defenses in these three lines:

1. **`algorithms=[ALGORITHM]`** — the accepted-algorithms list is passed explicitly. The `alg` field in the incoming token header is only accepted if it matches. PyJWT enforces this.
2. **All PyJWT errors become `TokenError`.** Callers do not need to know about PyJWT's internal exception hierarchy. `verify_token` does not return `None` — it raises. That prevents the classic "forgot to check the result" bug.

`verify_token` returns the claims dict on success — never raises for a valid token. It raises `TokenError` for:

- Signature mismatch (forged or tampered).
- Expired token (`exp` in the past).
- Wrong algorithm in header (e.g. HS256 forgery).
- Malformed token (not three base64url segments).
- Missing or non-integer `exp`.

## The classic attack we defend against: algorithm confusion

If `algorithms=` were omitted or set to a list including HS256, an attacker could:

1. Read the public key (it is public).
2. Forge a token with `alg: HS256`, signed using the public key **as an HMAC secret**.
3. Present it to `verify_token`. A naive verifier would see `alg: HS256`, look up the "key" as an HMAC secret, and successfully verify a forged token.

Our verifier pins `algorithms=["EdDSA"]`, so an HS256 header is rejected regardless of the signature value. The test `test_algorithm_confusion_hs256_rejected` in {{ src("shared_security/tests/test_tokens.py") }} hand-crafts an HS256 forgery and asserts the verifier rejects it — the test explicitly hand-builds the JWT with base64+HMAC because modern PyJWT refuses to *encode* an HS256 token when the "secret" is a PEM asymmetric key, which would otherwise mask the vulnerability we are testing for.

## What this defends against

- **Forgery.** No private key, no valid signature. Asymmetric.
- **Tampering.** Any change to header or payload invalidates the signature.
- **Algorithm confusion.** Pinned algorithm.
- **Expired tokens.** `exp` claim is checked against wall clock during verify.
- **Cross-service abuse.** Banking can verify but not mint. A compromised banking process cannot issue tokens for other users.

## What this does *not* defend against

- **Private-key theft.** The private key is the trust root. If it leaks, everything is forgeable until keys rotate. Rotation is not implemented ({{ src("flags.md", text="flag 8") }} covers key handling hardening).
- **Replay of a valid non-expired token.** Once a token is issued, anyone holding it can present it up to `exp`. TLS termination at the proxy is the defense in transit. There is no server-side revocation of access tokens — they are stateless.
- **Refresh token theft.** Access tokens are stateless; refresh tokens are opaque and stored. Refresh-token theft is mitigated only by "rotation invalidates the old token" and short TTLs. Reuse-detection (stolen-token detection by seeing a rotated token used again) is not implemented — see {{ src("03-auth-service/flow-refresh.md", text="../03-auth-service/flow-refresh.md") }}.

## Configurable via TokenSettings

The auth service wraps `sign_token` / `verify_token` in the `mint_token_pair` helper in {{ src("auth_service/src/auth_service/application/tokens.py") }}. TTLs come from `TokenSettings` ({{ src("auth_service/src/auth_service/application/settings.py") }}):

- `access_ttl` — how long a signed token is valid, in seconds. Default 300 (5 minutes).
- `refresh_ttl` — how long a refresh token is valid, in seconds. Default 86 400 (24 hours).

## Tests that pin this behaviour

{{ src("shared_security/tests/test_tokens.py") }}:

- Round trip preserves `sub`, `role`, `exp`.
- A token signed with an attacker's private key fails verification.
- Tampering with the signature bytes fails.
- Expired tokens fail (with `exp` in the past).
- **Algorithm confusion**: a hand-crafted HS256 token signed with the public key as the HMAC secret is rejected.
