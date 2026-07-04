# Flow: POST /login

Exchange username + password for an access token (signed JWT) and a refresh token (opaque).

## Request

```
POST /login
Content-Type: application/json

{
  "username": "alice",
  "password": "correct-horse-battery"
}
```

## Response — success

```
200 OK
Content-Type: application/json

{
  "access_token":  "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9…",
  "refresh_token": "8VVRq8_pW…-approx-43-chars",
  "token_type":    "Bearer"
}
```

- Access token: EdDSA-signed JWT. Verifiable with the public key from `/public-key`. Default TTL 300 seconds.
- Refresh token: opaque random string (32 random bytes, URL-safe base64). Default TTL 24 hours.

## Sequence — success

```
Client               FastAPI      Pydantic        LoginUseCase          shared_security             Postgres
   │                   │             │                 │                       │                       │
   │──POST /login──────▶             │                 │                       │                       │
   │                   │──validate──▶│                 │                       │                       │
   │                   │◀────ok──────│                 │                       │                       │
   │                                                                                                   │
   │             [open main_conn + audit_conn, begin main txn]                                         │
   │                   │──login(username, password, deps)──▶│                                          │
   │                   │                                    │                                          │
   │                   │                                    │──users.get_by_username──▶                │
   │                   │                                    │◀──User(id, hash, role=customer)──        │
   │                   │                                    │                                          │
   │                   │                                    │──verify_password (bcrypt)─▶│             │
   │                   │                                    │◀────True──────────────────│             │
   │                   │                                    │                                          │
   │                   │                                    │──mint_token_pair(user, deps)             │
   │                   │                                    │   ├─sign_token via shared_security       │
   │                   │                                    │   ├─secrets.token_urlsafe(32)            │
   │                   │                                    │   ├─sha256 hash of the refresh token     │
   │                   │                                    │   └─refresh_tokens.add(RefreshRecord)─▶  │
   │                   │                                    │◀──TokenPair(access=jwt, refresh=opaque)  │
   │                   │                                    │                                          │
   │                   │                                    │──emit "login_success"                    │
   │                   │                                    │  [autocommit audit_conn writes chain row]│
   │                   │                                    │                                          │
   │                   │◀───TokenPair───────────────────────│                                          │
   │             [commit main txn]                                                                     │
   │◀──200 TokenResponse                                                                               │
```

## Sequence — wrong password

```
Client                 LoginUseCase                       PostgresAuditLog (autocommit conn)
   │                        │                                          │
   │─────login(…)──────────▶│                                          │
   │                        │──users.get_by_username──▶ User(…)        │
   │                        │──verify_password──▶ False                │
   │                        │──emit "login_failed"                     │
   │                        │       ──record────────────────────────▶  │
   │                        │       [own txn: LOCK + chain + INSERT + COMMIT]
   │                        │       ◀───────────ok────────────────────  │
   │                        │──raise InvalidCredentials                 │
   │                        │                                          │
   │◀──401                                                              │
   │
   │  Main txn rolls back on exception exit — but audit event
   │  is already committed on the audit connection.
```

That last point is the whole reason for the two-connection design. See [audit-log-durability.md](audit-log-durability.md).

## Code path

Route: {{ src("auth_service/src/auth_service/infrastructure/app.py", text="login_route in app.py") }}:

```python
@app.post("/login", response_model=TokenResponse)
def login_route(body: LoginRequest, deps: AuthDeps = Depends(deps_factory)):
    try:
        pair = login(username=body.username, password=body.password, deps=deps)
    except InvalidCredentials:
        raise HTTPException(401, "invalid credentials")
    return TokenResponse(access_token=pair.access, refresh_token=pair.refresh)
```

Use case: {{ src("auth_service/src/auth_service/application/login.py", text="login in application/login.py") }}.

## Access token claim shape

```json
{
  "sub": "b3d9142-b1bc-411a-813f-0b6534e793a8",
  "role": "customer",
  "iat": 1783072578,
  "exp": 1783072878
}
```

Locked as contract 2 — see {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md") }}.

## Refresh token storage

```
| token_hash (PK, TEXT)  | user_id (UUID, FK)                  | expires_at (BIGINT) | created_at |
|------------------------|--------------------------------------|----------------------|------------|
| 3ffb2a…64-hex-chars    | b3d9142-b1bc-411a-813f-0b6534e793a8  | 1783158978           | 2026-07-…  |
```

The raw token is never stored. The database sees only its SHA-256 hash. A database compromise does not immediately hand the attacker valid refresh tokens.

## Failure modes

| Status | Cause | Body |
|--------|-------|------|
| `200` | Success | `TokenResponse` |
| `401` | Unknown user OR wrong password | `{"detail":"invalid credentials"}` |
| `422` | Malformed body (missing fields, extras present, empty strings) | Pydantic error detail |
| `500` | Postgres unavailable, key material invalid at startup | Generic |

The 401 body is deliberately identical for "user does not exist" and "wrong password" — see {{ src("01-architecture/security-controls.md", text="../01-architecture/security-controls.md") }} point 5. However, the *response time* is currently not identical because unknown-user short-circuits bcrypt — {{ src("flags.md", text="flag 1") }}.

## Audit events

- `{"event":"login_success","user_id":"…","at":…}` on success.
- `{"event":"login_failed","username":"…","at":…}` on failure. `user_id` is deliberately omitted because for unknown usernames there is no id, and we want a uniform failure event shape.

Both are hash-chained. Failed attempts persist even if the request errors out.

Also emitted to stdout as `LOGIN_SUCCESS username=alice` / `LOGIN_FAILED username=alice` — grep-friendly for fail2ban.

## Tests that pin this flow

- Application-layer: {{ src("auth_service/tests/test_login.py") }} — verifiable access token with role, admin role variant, wrong password rejected with no refresh token stored, unknown user rejected, refresh token opaque and not stored plaintext, refresh record has correct expiry, audit events (success and failure), audit failure event does not leak plaintext password.
- Integration: `test_login_returns_tokens`, `test_login_wrong_password_returns_401` in {{ src("auth_service/tests/test_integration.py") }}.
