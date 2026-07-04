# Contract: Token payload

**Owner**: Person A (auth service).
**Consumer**: Person B (banking service, when built).

This contract locks the shape of the tokens auth mints and any consumer verifies. **A change here is a conversation between Person A and Person B, not a silent edit.**

Full explanation lives in the docs — see [docs/01-architecture/contracts.md](../docs/01-architecture/contracts.md#contract-2-token-payload). This file is the short pinned reference so both people can find it at a glance.

---

## Access token

- **Format**: compact JWT (`header.payload.signature`, base64url).
- **Algorithm**: `EdDSA` (Ed25519). Pinned by name; consumers must pass `algorithms=["EdDSA"]` when verifying.
- **Signature**: Ed25519 by the auth service's private key.
- **Verifier**: Ed25519 public key. Fetched once from `GET /public-key` on the auth service; cached by the consumer.

### Claims

| Claim | Type | Meaning |
|-------|------|---------|
| `sub` | `str` (UUID) | User ID. Stable per user. Authorization decisions use this, not `username`. |
| `role` | `"customer"` \| `"admin"` | Role at the time the token was minted. Not automatically refreshed on `exp` — the consumer receives whatever role was in effect at login / refresh. |
| `iat` | `int` | Issued-at, Unix seconds. |
| `exp` | `int` | Expiry, Unix seconds. Enforced by `verify_token` against real wall-clock time. |

### TTL

- **Default**: 300 seconds (5 minutes).
- **Configurable**: `AUTH_ACCESS_TTL_SECONDS`, minimum 60.

---

## Refresh token

- **Format**: opaque high-entropy string. Not a JWT. ~43 characters (32 random bytes via `secrets.token_urlsafe`, URL-safe base64).
- **Server-side storage**: SHA-256 hex hash in the `refresh_tokens` table, paired with `user_id` and `expires_at`. The raw token is never persisted.
- **Rotation**: `POST /refresh` deletes the presented row and issues a fresh access + refresh pair. Presenting the old token afterward → 401.
- **TTL default**: 86 400 seconds (24 hours). Configurable: `AUTH_REFRESH_TTL_SECONDS`, minimum 3600.

Refresh tokens have **no claims and no metadata**. The consumer does not verify them locally. Presenting one to auth is what checks it.

---

## Verification steps on the consumer side

```python
# once at startup:
public_key = fetch("/public-key")["public_key"]  # PEM

# per request:
try:
    claims = shared_security.tokens.verify_token(bearer_token, public_key)
except TokenError:
    raise Unauthorized

user_id = claims["sub"]
role = claims["role"]
# enforce RBAC before touching data
```

`verify_token` handles: signature check, algorithm pinning, `exp` check. Any failure raises `TokenError`.

---

## What is *not* in this contract

- Exact character count of the refresh token.
- Whether refresh tokens carry metadata (they do not).
- Auth-internal audit event shapes (auth-only, not read by the consumer).
- HTTP-level details (status codes, error bodies). Those are separate.

---

## Changing this contract

1. Announce (PR, message, meeting).
2. Update this file.
3. Update the tests that pin the contract — see [auth_service/tests/test_login.py](../auth_service/tests/test_login.py) and [auth_service/tests/test_refresh.py](../auth_service/tests/test_refresh.py).
4. Update the consumer.
5. Ship in one coordinated change.
