# Application layer

Use cases + ports. Where the business rules live. No FastAPI, no psycopg — the use cases can run in a test without any of that.

Location: {{ src("auth_service/src/auth_service/application/", text="auth_service/src/auth_service/application/") }}.

## Ports — the swappable seams

{{ src("auth_service/src/auth_service/application/ports.py") }} declares four `typing.Protocol` interfaces:

```python
class UserRepository(Protocol):
    def get_by_username(self, username: str) -> User | None: ...
    def get_by_id(self, user_id: str) -> User | None: ...
    def add(self, user: User) -> None: ...

class RefreshTokenStore(Protocol):
    def add(self, record: RefreshRecord) -> None: ...
    def get(self, token_hash: str) -> RefreshRecord | None: ...
    def remove(self, token_hash: str) -> None: ...

class AuditLog(Protocol):
    def record(self, event: dict) -> None: ...

class Clock(Protocol):
    def now(self) -> int: ...
```

Two implementations of each:

| Port | Test impl | Production impl |
|------|-----------|-----------------|
| `UserRepository` | `FakeUserRepo` in {{ src("auth_service/tests/conftest.py") }} | {{ src("auth_service/src/auth_service/infrastructure/repositories/users_repo.py", text="PostgresUserRepository") }} |
| `RefreshTokenStore` | `FakeRefreshStore` in conftest.py | {{ src("auth_service/src/auth_service/infrastructure/repositories/refresh_repo.py", text="PostgresRefreshTokenStore") }} |
| `AuditLog` | `FakeAudit` in conftest.py | {{ src("auth_service/src/auth_service/infrastructure/audit_log.py", text="PostgresAuditLog") }} |
| `Clock` | `FakeClock` in conftest.py | {{ src("auth_service/src/auth_service/infrastructure/clock.py", text="SystemClock") }} |

## Deps container

{{ src("auth_service/src/auth_service/application/deps.py") }}:

```python
@dataclass(frozen=True)
class AuthDeps:
    users: UserRepository
    refresh_tokens: RefreshTokenStore
    audit: AuditLog
    clock: Clock
    settings: TokenSettings
```

Every use case takes `deps: AuthDeps`. Slight downside — a use case that only needs `users` still receives everything else — but the ergonomic win at every call site outweighs it. See {{ src("01-architecture/clean-architecture.md", text="../01-architecture/clean-architecture.md") }}.

## Token settings

{{ src("auth_service/src/auth_service/application/settings.py") }}:

```python
@dataclass(frozen=True)
class TokenSettings:
    private_key: str    # PEM
    public_key: str     # PEM
    access_ttl: int     # seconds
    refresh_ttl: int    # seconds
```

Application-layer type. Infrastructure layer builds it from env config in {{ src("auth_service/src/auth_service/infrastructure/config.py") }}.

## Shared helpers

### `tokens.py` — token minting

{{ src("auth_service/src/auth_service/application/tokens.py") }} provides:

```python
@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str

def hash_refresh_token(token: str) -> str
def mint_token_pair(user: User, deps: AuthDeps) -> TokenPair
```

`mint_token_pair` builds the access-token claims, signs via `shared_security.tokens.sign_token`, generates a fresh opaque refresh token (`secrets.token_urlsafe(32)`), hashes it, and stores the hashed record. Called from both `login` and `refresh` — shared code, one source of truth for the token shape.

Access claims:
```python
{
  "sub": user.id,
  "role": user.role,
  "iat": deps.clock.now(),
  "exp": deps.clock.now() + deps.settings.access_ttl,
}
```

The claim shape is contract 2 in {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md") }}.

### `audit.py` — audit emit

{{ src("auth_service/src/auth_service/application/audit.py") }}:

```python
def emit(deps: AuthDeps, event: str, **fields) -> None:
    deps.audit.record({"event": event, "at": deps.clock.now(), **fields})
```

Extracted in the DRY pass — six audit call sites across register/login/refresh all follow the same shape. Enforcing that every event carries `event` and `at` at a single point rules out "someone forgot the timestamp" bugs.

## Use cases

### `register`

{{ src("auth_service/src/auth_service/application/register.py") }}:

```python
def register(*, username, password, role, deps) -> User:
    if deps.users.get_by_username(username) is not None:
        raise UsernameTaken(username)
    user = User(
        id=str(uuid4()),
        username=username,
        password_hash=hash_password(password),
        role=role,
    )
    deps.users.add(user)
    emit(deps, "register", user_id=user.id, username=username)
    return user
```

Rules:
- Check uniqueness first.
- Assign a fresh UUID.
- Hash the password before construction — the `password_hash` field always contains a bcrypt hash, never plaintext.
- Insert.
- Emit audit event.

Note the race: two concurrent `register` calls with the same username could both pass the `get_by_username` check and both call `add`. The **repository** handles this race — {{ src("auth_service/src/auth_service/infrastructure/repositories/users_repo.py", text="PostgresUserRepository.add") }} catches `UniqueViolation` and re-raises `UsernameTaken`, so the use case's contract holds regardless.

Called from: {{ src("auth_service/src/auth_service/infrastructure/app.py", text="POST /register") }}. Full flow: [flow-register.md](flow-register.md).

### `login`

{{ src("auth_service/src/auth_service/application/login.py") }}:

```python
def login(*, username, password, deps) -> TokenPair:
    user = deps.users.get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        emit(deps, "login_failed", username=username)
        raise InvalidCredentials
    pair = mint_token_pair(user, deps)
    emit(deps, "login_success", user_id=user.id)
    return pair
```

Rules:
- Look up by username.
- Verify password. Both "user does not exist" and "password wrong" collapse into `InvalidCredentials` — clients cannot distinguish them.
- Emit audit event (success or failure).
- On success, mint access + refresh pair.

Note: **failed logins get an audit event even though the operation fails.** For that to actually persist, `PostgresAuditLog` uses a separate autocommit connection — see [audit-log-durability.md](audit-log-durability.md).

Note: unknown-user branch short-circuits bcrypt, which is a user-enumeration timing side-channel. Documented in {{ src("flags.md", text="flag 1") }}.

Called from: {{ src("auth_service/src/auth_service/infrastructure/app.py", text="POST /login") }}. Full flow: [flow-login.md](flow-login.md).

### `refresh`

{{ src("auth_service/src/auth_service/application/refresh.py") }}:

```python
def refresh(*, token, deps) -> TokenPair:
    token_hash = hash_refresh_token(token)
    record = deps.refresh_tokens.get(token_hash)
    if record is None or record.expires_at <= deps.clock.now():
        emit(deps, "refresh_failed")
        raise InvalidRefreshToken
    user = deps.users.get_by_id(record.user_id)
    if user is None:
        emit(deps, "refresh_failed")
        raise InvalidRefreshToken
    deps.refresh_tokens.remove(token_hash)
    pair = mint_token_pair(user, deps)
    emit(deps, "refresh_success", user_id=user.id)
    return pair
```

Rules:
- Hash the presented token and look it up.
- Reject if unknown, expired, or if the associated user no longer exists.
- **Delete the row** before minting the new pair. This is the "rotation" — reusing the old token after this fails because the row is gone.
- Mint new access + refresh pair.

Called from: {{ src("auth_service/src/auth_service/infrastructure/app.py", text="POST /refresh") }}. Full flow: [flow-refresh.md](flow-refresh.md).

## What is not in the application layer

- **No transactions.** The use cases do not know they run inside a psycopg transaction. That is an infrastructure concern — the FastAPI dependency generator wraps each request in one. See [audit-log-durability.md](audit-log-durability.md).
- **No HTTP status codes.** Domain errors propagate up; the route in {{ src("auth_service/src/auth_service/infrastructure/app.py") }} translates them to `HTTPException(status_code=…)`.
- **No config loading.** Use cases receive already-materialised `TokenSettings`.
- **No key material generation.** Keys are generated once and passed through env → config → settings. `generate_signing_keypair` from shared_security is used only in tests and in the `.env` bootstrap.

## Tests over the application layer

23 tests in {{ src("auth_service/tests/test_register.py") }}, {{ src("auth_service/tests/test_login.py") }}, {{ src("auth_service/tests/test_refresh.py") }}. Full walkthrough: {{ src("05-testing/what-tests-prove.md", text="../05-testing/what-tests-prove.md") }}.
