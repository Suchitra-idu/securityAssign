# Domain layer

Pure data + errors. If you deleted every non-stdlib import tomorrow, this layer would not change.

Location: [auth_service/src/auth_service/domain/](../../auth_service/src/auth_service/domain/).

## Files

### `users.py`

```python
Role = Literal["customer", "admin"]

@dataclass(frozen=True)
class User:
    id: str
    username: str
    password_hash: str
    role: Role
```

- **`id`** — UUIDv4 string. Assigned by [register()](../../auth_service/src/auth_service/application/register.py) at creation, never mutated. Used as the `sub` claim in access tokens.
- **`username`** — user-supplied display identifier. Charset and length enforced at the HTTP boundary by [schemas.py](../../auth_service/src/auth_service/infrastructure/schemas.py). Uniqueness enforced by the users table.
- **`password_hash`** — bcrypt hash string. Never plaintext, ever.
- **`role`** — literal `"customer"` or `"admin"`. Type-checked and enforced by the database's `CHECK (role IN ('customer', 'admin'))` constraint.

`frozen=True` means once constructed the object cannot be mutated. Repositories construct fresh instances on read; use cases build fresh instances on register. Immutability rules out "someone changed the role on this user object after we made a decision from it" bugs.

### `refresh.py`

```python
@dataclass(frozen=True)
class RefreshRecord:
    token_hash: str
    user_id: str
    expires_at: int
```

- **`token_hash`** — SHA-256 hex digest of the raw refresh token. **The raw token is never stored.**
- **`user_id`** — foreign key to `users.id`.
- **`expires_at`** — Unix seconds. Refresh checks `expires_at <= clock.now()` and rejects if so.

The domain has no `RefreshToken` (raw string) type — that only exists in transit and is discarded server-side after the hash is stored.

### `errors.py`

```python
class UsernameTaken(Exception): pass
class InvalidCredentials(Exception): pass
class InvalidRefreshToken(Exception): pass
```

Three failure modes. Each is raised from exactly one use case (register, login, refresh respectively) and translated to HTTP 409/401/401 in [app.py](../../auth_service/src/auth_service/infrastructure/app.py).

**Why so few errors?** CLAUDE.md's "no defensive checks for conditions that cannot happen inside trusted internal code" applies. We do not need `InvalidRole`, `UserNotFound`, `RepositoryUnavailable` because:

- Role is a literal type — bad values are caught by pydantic at the boundary and by DB `CHECK`, not by the domain.
- User-not-found is folded into `InvalidCredentials` so the auth failure mode is timing-consistent (in principle — see [flag 1](../../flags.md) for the current gap).
- Repository unavailability is not a domain error — it is a 500 from Postgres, and the infrastructure layer handles it as an infrastructure failure.

## What the domain layer does not have

- No `Session` class — sessions are represented by the presence of a `RefreshRecord` row in the DB, not a domain concept.
- No `Token` type — tokens are strings shaped by the application layer's `TokenPair` dataclass, one layer up.
- No `Password` type — passwords never survive past the use case that hashes them.
- No `Timestamp` wrapper — `int` (Unix seconds) is used directly; no need for a wrapper type.

Keeping the domain deliberately thin is the point. All business rules that touch these types live in the application layer.

## Import discipline

Verify with:

```
$ grep -R "^import\|^from" auth_service/src/auth_service/domain/
```

You should see nothing besides `dataclasses` and `typing`. Any other import here is a layering violation.

## Tests that pin behaviour of the domain layer

There are no dedicated domain tests. The domain layer is trivial — it holds only data shapes. All meaningful behaviour is exercised via the application-layer tests ([test_register.py](../../auth_service/tests/test_register.py), etc.), which construct `User` and `RefreshRecord` values directly.
