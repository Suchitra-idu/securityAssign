# Flow: GET /public-key

Publish the Ed25519 public key for verifiers. **This is what makes cross-service trust work** — the banking service (or any verifier) needs this to check access tokens without ever seeing the private key.

## Request

```
GET /public-key
```

No authentication. This endpoint is deliberately public — the whole point of the split is that the verifier only needs the public key.

## Response

```
200 OK
Content-Type: application/json

{
  "public_key": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA…\n-----END PUBLIC KEY-----\n",
  "algorithm": "EdDSA"
}
```

- `public_key` — SubjectPublicKeyInfo PEM. Multi-line string. Escaped `\n` in the JSON body.
- `algorithm` — literal `"EdDSA"`. Present so a naive consumer doesn't guess.

## Code path

Route: [public_key_route in app.py](../../auth_service/src/auth_service/infrastructure/app.py):

```python
@app.get("/public-key", response_model=PublicKeyResponse)
def public_key_route() -> PublicKeyResponse:
    return PublicKeyResponse(public_key=config.signing_public_key_pem)
```

Key source: `AUTH_SIGNING_PUBLIC_KEY_PEM` env var, loaded via [Config](../../auth_service/src/auth_service/infrastructure/config.py).

## Verifier flow (banking, when built)

```
banking startup                       auth service
    │                                     │
    │──GET /public-key───────────────────▶│
    │◀──{public_key, algorithm:"EdDSA"}───│
    │
    │  cache public_key in memory
    │
    ...

per request:
    │
    │──GET /accounts, Authorization: Bearer <access_token>
    │
    │  call shared_security.tokens.verify_token(access_token, cached_public_key)
    │      → dict {sub, role, iat, exp}   on success
    │      → TokenError                   on any failure
    │
    │  enforce RBAC using claims["role"] before touching data
```

## Non-caching, non-rotation

- Auth does not currently offer a `kid`, `iss`, or issue timestamp for the key. A single "current" key at a time.
- Rotation is not implemented — see [flag 8](../../flags.md). If it were, this endpoint would return the new key and verifiers would need a strategy: refetch on 401, TTL the cache, or listen for a version signal.
- The banking service will need to cache the key at startup and refetch it if a verify unexpectedly fails — the exact policy is a banking-side decision, not enforced by auth.

## Failure modes

| Status | Cause |
|--------|-------|
| `200` | Always, in normal operation. |
| `500` | If `AUTH_SIGNING_PUBLIC_KEY_PEM` was somehow set to an invalid value. The failure is at process startup, not here — Pydantic-settings raises before the app is built. |

The route has no authentication and no rate-limiting on its own. Rate limiting is the WAF's job (not built).

## Tests

- Integration: `test_public_key_endpoint_returns_pem` in [test_integration.py](../../auth_service/tests/test_integration.py) — asserts the returned PEM equals the configured public key and the algorithm is `EdDSA`.
