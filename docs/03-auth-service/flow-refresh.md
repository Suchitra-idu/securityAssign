# Flow: POST /refresh

Rotate the refresh token. Issue a new access + refresh pair.

## Request

```
POST /refresh
Content-Type: application/json

{
  "refresh_token": "8VVRq8_pW…"
}
```

## Response — success

```
200 OK
{
  "access_token":  "eyJhbGciOiJFZERTQSI…",
  "refresh_token": "aa4tw12Q…-new-opaque-string",
  "token_type":    "Bearer"
}
```

Both tokens are *new*. The presented refresh token is invalidated as part of the same request.

## Sequence — success

```
Client                   FastAPI      RefreshUseCase                                             Postgres
   │                        │              │                                                        │
   │──POST /refresh─────────▶              │                                                        │
   │                        │──validate───▶│                                                        │
   │                                       │                                                        │
   │                  [open connections, begin main txn]                                            │
   │                        │──refresh(token, deps)──▶│                                             │
   │                        │                         │                                             │
   │                        │                         │──hash = sha256(token)                       │
   │                        │                         │──refresh_tokens.get(hash)──▶ RefreshRecord  │
   │                        │                         │      (user_id, expires_at)                  │
   │                        │                         │                                             │
   │                        │                         │──users.get_by_id(record.user_id)──▶ User    │
   │                        │                         │                                             │
   │                        │                         │──refresh_tokens.remove(hash)──▶ (delete)    │
   │                        │                         │                                             │
   │                        │                         │──mint_token_pair(user, deps)                │
   │                        │                         │   ├─ sign new access token                  │
   │                        │                         │   ├─ generate new opaque refresh token      │
   │                        │                         │   └─ refresh_tokens.add(new record)──▶      │
   │                        │                         │                                             │
   │                        │                         │──emit "refresh_success"                     │
   │                        │                         │   [audit_conn autocommit]                   │
   │                        │◀──TokenPair─────────────│                                             │
   │                  [commit main txn — DELETE + INSERT land together]                             │
   │◀──200 TokenResponse                                                                            │
```

## Sequence — reused token (after rotation)

```
Client                    RefreshUseCase                                Postgres
   │                            │                                          │
   │──POST /refresh (old tok)──▶│                                          │
   │                            │──hash = sha256(old_tok)                  │
   │                            │──refresh_tokens.get(hash)──▶ None        │
   │                            │       (row was deleted on prior refresh) │
   │                            │──emit "refresh_failed"                   │
   │                            │──raise InvalidRefreshToken               │
   │◀──401
```

## Code path

Route: {{ src("auth_service/src/auth_service/infrastructure/app.py", text="refresh_route in app.py") }}:

```python
@app.post("/refresh", response_model=TokenResponse)
def refresh_route(body: RefreshRequest, deps: AuthDeps = Depends(deps_factory)):
    try:
        pair = refresh(token=body.refresh_token, deps=deps)
    except InvalidRefreshToken:
        raise HTTPException(401, "invalid refresh token")
    return TokenResponse(access_token=pair.access, refresh_token=pair.refresh)
```

Use case: {{ src("auth_service/src/auth_service/application/refresh.py", text="refresh in application/refresh.py") }}.

## Rotation semantics

- **Every successful refresh deletes the presented row.** After success, the old token is dead.
- Concurrent refreshes with the same token: whichever transaction acquires the row lock first proceeds; the second sees no row (row was deleted) and returns 401. Order is not guaranteed but exactly one wins.
- Rotation atomicity is protected by the main transaction wrapping DELETE + INSERT. If any step raises, both are rolled back and the old token remains valid — the client can retry.

## Non-rotation semantics (things we do *not* do)

- **No reuse detection.** If a stolen refresh token is used before the legitimate client refreshes, the thief becomes the new legitimate holder — until the legitimate client's next refresh, which will 401. The classic mitigation is "if a refresh token is used and then the same token is used again, invalidate all sessions for that user". Not implemented — would require keeping a short-lived history of rotated hashes. Documented as a potential enhancement in the report.
- **No family / lineage tracking.** Each rotated pair is independent.
- **No refresh on expired access token.** The refresh endpoint takes the refresh token, not the access token. Clients decide when to refresh — typically before the access token's `exp`.
- **No access-token revocation.** Access tokens are stateless. If a user should be logged out immediately, the current mechanism is: delete their refresh tokens (so no more refreshes) and wait out the ≤5-minute access token TTL. A revocation list would require a lookup on every verify — not built.

## Refresh-record hashing rationale

The database stores `sha256(refresh_token)` as hex. Not the raw token. Rationale:

- **Compromise of the DB does not immediately yield valid tokens.** An attacker who reads the `refresh_tokens` table sees hashes, not usable tokens. To use them the attacker would have to preimage SHA-256 — computationally infeasible for random 32-byte inputs.
- **SHA-256 is fast to compute on lookup.** No adaptive-cost hash like bcrypt is needed — the input is already random 256-bit-equivalent, so brute forcing the preimage is intractable.
- **Same-token equality check works** — we look up by the sha256 hex.

## Failure modes

| Status | Cause | Body |
|--------|-------|------|
| `200` | Rotation success | `TokenResponse` |
| `401` | Unknown token / expired / rotated (row already deleted) / user deleted since token issued | `{"detail":"invalid refresh token"}` |
| `422` | Missing / empty refresh_token, extras present | Pydantic error |

## Audit events

- `{"event":"refresh_success","user_id":"…","at":…}` on success.
- `{"event":"refresh_failed","at":…}` on any failure. Deliberately does *not* include user_id or the presented token — we do not want an audit event to reveal a bogus token to log inspectors, and for unknown tokens there is no user id to include.

`REFRESH_FAILED` also emitted to stdout for fail2ban.

## Tests that pin this flow

- Application-layer: {{ src("auth_service/tests/test_refresh.py") }} — rotation produces different tokens, old token rejected after rotation, expired token rejected, unknown token rejected, subject and role preserved, audit events, reuse never mints anything.
- Integration: `test_refresh_rotates_tokens`, `test_refresh_old_token_after_rotation_returns_401` in {{ src("auth_service/tests/test_integration.py") }}.
