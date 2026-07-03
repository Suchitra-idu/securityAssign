# Flow: POST /register

New customer account. Public endpoint. Role is hardcoded to `customer` — admins are seeded out-of-band.

## Request

```
POST /register
Content-Type: application/json

{
  "username": "alice",
  "password": "correct-horse-battery"
}
```

## Response — success

```
201 Created
Content-Type: application/json

{
  "user_id": "b3d9142-b1bc-411a-813f-0b6534e793a8",
  "username": "alice",
  "role": "customer"
}
```

## Sequence

```
Client                    FastAPI           Pydantic          RegisterUseCase       shared_security          Postgres
   │                         │                  │                    │                     │                   │
   │──POST /register─────────▶                  │                    │                     │                   │
   │                         │──validate body──▶│                    │                     │                   │
   │                         │◀─valid model─────│                    │                     │                   │
   │                         │                                                                                 │
   │                     [open main_conn + audit_conn from pool, begin main txn]                               │
   │                         │                                                                                 │
   │                         │──register(username, password, "customer", deps)──▶│                             │
   │                         │                                                    │                            │
   │                         │                                                    │──users.get_by_username──▶  │
   │                         │                                                    │◀──None (no such user)───   │
   │                         │                                                    │                            │
   │                         │                                                    │──hash_password (bcrypt)─▶│ │
   │                         │                                                    │◀──"$2b$12$…"────────────│ │
   │                         │                                                    │                            │
   │                         │                                                    │──users.add(User(…))─────▶  │
   │                         │                                                    │◀──ok────────────────────   │
   │                         │                                                    │                            │
   │                         │                                                    │──audit.record({event:      │
   │                         │                                                    │   "register", user_id, at})│
   │                         │                                                    │  [LOCK + chain + INSERT on audit_conn, autocommit]
   │                         │                                                    │◀──ok────────────────────   │
   │                         │                                                    │                            │
   │                         │◀────User (frozen dataclass)─────────────────────── │                            │
   │                         │                                                                                 │
   │                     [commit main txn on generator exit]                                                    │
   │                         │                                                                                 │
   │◀────201 UserResponse────│                                                                                  │
```

## Code path

Route: [register_route in app.py](../../auth_service/src/auth_service/infrastructure/app.py):

```python
@app.post("/register", response_model=UserResponse, status_code=201)
def register_route(body: RegisterRequest, deps: AuthDeps = Depends(deps_factory)):
    try:
        user = register(username=body.username, password=body.password, role="customer", deps=deps)
    except UsernameTaken:
        raise HTTPException(409, "username taken")
    return UserResponse(user_id=user.id, username=user.username, role=user.role)
```

Use case: [register in application/register.py](../../auth_service/src/auth_service/application/register.py). See [application-layer.md](application-layer.md#register).

## Failure modes

### 422 — Pydantic rejects the body

Fired *before* the use case runs. See [input-validation.md](input-validation.md) for exact rules. Common causes:

- `password` shorter than 12 characters.
- `username` shorter than 3 characters, longer than 32, or containing characters outside `[A-Za-z0-9_.-]`.
- Missing `username` or `password`.
- Extra field in the body (e.g. `"role": "admin"`) — the model uses `extra="forbid"`.

Body:
```json
{"detail": [{"loc": [...], "msg": "...", "type": "..."}, ...]}
```

### 409 — Username already taken

The use case's initial `get_by_username` check returns a user, or the INSERT hits the unique constraint on `users.username`. Either way, `UsernameTaken` bubbles up and the route returns 409.

Body:
```json
{"detail": "username taken"}
```

### 500 — Postgres unavailable, pool exhausted, etc.

Not surfaced with structured detail; FastAPI returns a generic 500 and the exception is logged.

## Role hardcoding — the security point

The public endpoint always calls `register(..., role="customer", ...)`. A client cannot ask for `role="admin"` because:

1. The route ignores `body.role` — it does not read that field.
2. The Pydantic model does not declare a `role` field.
3. `extra="forbid"` means any additional field (including `role`) causes 422.

Locked by [test_register_forbids_role_field_from_request in test_integration.py](../../auth_service/tests/test_integration.py). Admin accounts must be created via seeded SQL or a bootstrap CLI (not yet built — [flag 2](../../flags.md)).

## Audit event

```json
{"event": "register", "user_id": "b3d9142-…", "username": "alice", "at": 1783072578}
```

Persisted through the hash-chained audit log via the autocommit audit connection. See [audit-log-durability.md](audit-log-durability.md).

## Tests that pin this flow

- Application-layer: [test_register.py](../../auth_service/tests/test_register.py) — password hashed, role stored, duplicate rejected, audit event emitted, audit event never carries plaintext password.
- Integration: `test_register_returns_201_with_customer_role`, `test_register_duplicate_returns_409`, `test_register_rejects_short_password`, `test_register_rejects_bad_username`, `test_register_forbids_role_field_from_request` in [test_integration.py](../../auth_service/tests/test_integration.py).
