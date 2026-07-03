# Input validation

Every request body is validated by Pydantic **before** the use case runs. Malformed input → 422 with a field-scoped error detail; nothing else executes.

Location: [schemas.py](../../auth_service/src/auth_service/infrastructure/schemas.py).

## Global setting: `extra="forbid"`

Every request model uses:

```python
model_config = ConfigDict(extra="forbid")
```

This is the single most valuable line in the file. It means unknown fields cause 422 rather than being silently ignored. Concretely:

- A client sending `{"username": "alice", "password": "…", "role": "admin"}` to `/register` gets 422 — `role` is not declared on `RegisterRequest`. The client cannot smuggle a role. Locked by [test_register_forbids_role_field_from_request](../../auth_service/tests/test_integration.py).
- Same defense against smuggled `id`, `sub`, or anything else a caller might imagine matters.

Rejecting unknown fields is stricter than the JSON RFC requires and stricter than most APIs default to. That is deliberate. Explicit contract, no room for parameter smuggling.

## Model-by-model rules

### `RegisterRequest`

```python
username: str = Field(min_length=3, max_length=32)
password: str = Field(min_length=12, max_length=128)

@field_validator("username")
def _username_charset(cls, v: str) -> str:
    if not _USERNAME_RE.fullmatch(v):
        raise ValueError(...)
    return v
```

Where `_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")`.

- **Username length 3–32.** Enough for real names, capped to avoid gigantic identifiers polluting logs.
- **Username charset**: letters, digits, underscore, dot, dash. Rules out SQL fragments (`'`, `;`), URL/path components (`/`, `?`), whitespace, control chars, and unicode confusables. Not because our SQL is unsafe (it uses parameterised queries — see [users_repo.py](../../auth_service/src/auth_service/infrastructure/repositories/users_repo.py)) but because a restrictive charset avoids any downstream ambiguity in logs, URL routing, and file names.
- **Password 12–128.** Twelve is a common minimum-that-doesn't-feel-punitive. 128 is a hard upper bound to keep bcrypt hashing time predictable (though bcrypt itself truncates at 72 bytes — see [../02-shared-security/passwords.md](../02-shared-security/passwords.md#what-this-does-not-defend-against)).
- **No `role` field.** Role is hardcoded to `customer` at the route layer.

### `LoginRequest`

```python
username: str = Field(min_length=1, max_length=32)
password: str = Field(min_length=1, max_length=128)
```

Deliberately loose. Any non-empty value passes. The use case does the actual credential check. Rejecting valid-form-but-wrong credentials with 422 would tell the client "this format was wrong" instead of "credentials wrong" — an information leak we avoid.

The length upper bounds are still applied to prevent absurdly large payloads.

### `RefreshRequest`

```python
refresh_token: str = Field(min_length=1, max_length=256)
```

Refresh tokens produced by the auth service are ~43 characters, but the field allows up to 256 to accommodate any future encoding change. Below 1 or above 256 → 422.

### `UserResponse`, `TokenResponse`, `PublicKeyResponse`

Response models. Field types are declared for FastAPI to generate accurate OpenAPI schema. `TokenResponse.token_type` defaults to `"Bearer"`.

## What happens on 422

FastAPI catches Pydantic `ValidationError` and returns:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 12 characters",
      "input": "short",
      "ctx": {"min_length": 12}
    }
  ]
}
```

Structured errors with field paths. Useful for clients; not information the attacker didn't already know.

## What input validation does *not* do

- **Content-based password checks.** No dictionary word rejection, no zxcvbn scoring. Users can pick `aaaaaaaaaaaa` and it's accepted. A real deployment would add a strength check.
- **NFC normalisation.** Two visually identical usernames from different unicode encodings would validate independently. Not currently a problem because the charset regex is ASCII-only.
- **CSRF, replay, or origin checks.** Those are the WAF's job. Not built.
- **JSON body size limits.** FastAPI's underlying starlette default applies (16 MiB). For production, a Caddy directive would cap this earlier.
- **Rate limiting per client.** WAF concern.

## Why input validation belongs in infrastructure, not domain

The domain does not know about "the HTTP request that carried this data". It receives already-validated primitive types (`str`, `int`, `bool`). Pushing validation up to the infrastructure edge means:

- The use cases never have to defensively re-check that a `username` matches a regex.
- Validation errors return the appropriate HTTP status (422) automatically — no manual translation.
- The set of accepted inputs is a single-page reference (this doc), scoped to the delivery mechanism.

If a second delivery mechanism ever appears (CLI, gRPC), it applies its own edge validation before calling the same use cases.

## Tests that pin this

- `test_register_rejects_short_password` — 422 on password < 12 chars.
- `test_register_rejects_bad_username` — 422 on username with SQL fragment.
- `test_register_forbids_role_field_from_request` — 422 on unknown `role` field.

All in [test_integration.py](../../auth_service/tests/test_integration.py).
