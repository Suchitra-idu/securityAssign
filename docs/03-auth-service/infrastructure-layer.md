# Infrastructure layer

FastAPI, Postgres, config. Where the outside world is bolted onto the pure inner layers.

Location: [auth_service/src/auth_service/infrastructure/](../../auth_service/src/auth_service/infrastructure/).

## Config: `config.py`

[config.py](../../auth_service/src/auth_service/infrastructure/config.py):

```python
class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    database_url: str
    signing_private_key_pem: str
    signing_public_key_pem: str
    access_ttl_seconds: int = Field(default=300, ge=60)
    refresh_ttl_seconds: int = Field(default=86_400, ge=3_600)
    pool_min_size: int = 1
    pool_max_size: int = 10

    def tokens(self) -> TokenSettings: ...
```

Sourced from `pydantic-settings`. Every field maps to an env var — see [../04-deployment/env-vars.md](../04-deployment/env-vars.md).

`Config.tokens()` builds the application-layer `TokenSettings` from the underlying fields. This is the single conversion point between "env-driven infra config" and "domain-friendly settings".

## Clock: `clock.py`

[clock.py](../../auth_service/src/auth_service/infrastructure/clock.py):

```python
class SystemClock:
    def now(self) -> int:
        return int(time.time())
```

Trivial, but important that it exists as a separate class so tests can substitute `FakeClock` for deterministic time in the application-layer tests.

## Database wiring: `db.py` + `schema.sql`

[db.py](../../auth_service/src/auth_service/infrastructure/db.py):

```python
def build_pool(database_url, *, min_size, max_size) -> ConnectionPool
def apply_schema(pool) -> None
```

- **Pool** — psycopg3 sync `ConnectionPool`. Sync mode chosen because the application layer is sync and FastAPI runs sync handlers in a thread pool automatically. Async would leak up into the use cases and buy nothing at the traffic level this service will see. See [../04-deployment/env-vars.md](../04-deployment/env-vars.md) for `AUTH_POOL_MIN_SIZE` / `AUTH_POOL_MAX_SIZE`.
- **Schema application** — reads `schema.sql` from package resources and executes it. Idempotent (uses `CREATE TABLE IF NOT EXISTS`). Runs once at startup inside `create_app` if a Postgres factory is being built. See [../04-deployment/database-schema.md](../04-deployment/database-schema.md) for the DDL.

## Repositories

Each repo takes a `Connection` (not a pool). The FastAPI dependency generator picks a connection from the pool per request and hands it to the repo. This means all queries in one request share a connection, and can share a transaction.

### `users_repo.py`

[PostgresUserRepository](../../auth_service/src/auth_service/infrastructure/repositories/users_repo.py) implements `UserRepository`. Three methods, each one SQL statement.

Notable: `add()` catches `psycopg.errors.UniqueViolation` on the `users_username_key` constraint and re-raises `UsernameTaken`. This is the infrastructure-to-domain error translation for the check-then-insert race in `register` (see [application-layer.md](application-layer.md#register)).

### `refresh_repo.py`

[PostgresRefreshTokenStore](../../auth_service/src/auth_service/infrastructure/repositories/refresh_repo.py) implements `RefreshTokenStore`. Three methods:

- `add(record)` — INSERT with the SHA-256 hex of the raw refresh token, user id, expiry.
- `get(token_hash)` — lookup by hash.
- `remove(token_hash)` — DELETE. Idempotent (deletes zero rows if the hash isn't present).

## Hash-chained audit sink: `audit_log.py`

[PostgresAuditLog](../../auth_service/src/auth_service/infrastructure/audit_log.py) implements `AuditLog`. One method:

```python
def record(self, event: dict) -> None:
    with self._conn.transaction():
        self._conn.execute("LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE")
        row = self._conn.execute(
            "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = bytes(row[0]) if row else GENESIS_HASH
        new_hash = compute_chain_hash(prev_hash, canonical_json_bytes(event))
        self._conn.execute(
            "INSERT INTO audit_log (event, prev_hash, hash) VALUES (%s, %s, %s)",
            (Jsonb(event), prev_hash, new_hash),
        )
```

Two subtle things here — both covered in depth in [audit-log-durability.md](audit-log-durability.md):

1. **Own transaction inside a caller-supplied autocommit connection.** Audit writes commit independently of the caller's main transaction, so failed operations (login failures, refresh failures) still persist their audit event.
2. **`LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`.** Serialises concurrent writers so `SELECT last hash → compute → INSERT` cannot interleave and fork the chain.

## Pydantic schemas: `schemas.py`

[schemas.py](../../auth_service/src/auth_service/infrastructure/schemas.py) declares the request and response models. Every model uses `extra="forbid"` — unknown fields are rejected with 422 rather than silently ignored. That is what prevents a client from smuggling `{"role": "admin"}` into `/register`. Full rules: [input-validation.md](input-validation.md).

## FastAPI app factory: `app.py`

[app.py](../../auth_service/src/auth_service/infrastructure/app.py):

```python
def create_app(config: Config, deps_factory: DepsFactory | None = None) -> FastAPI:
    ...
```

If `deps_factory` is not supplied, the factory builds a Postgres-backed one that opens two connections per request:

```python
def deps_factory() -> Iterator[AuthDeps]:
    with pool.connection() as main_conn, pool.connection() as audit_conn:
        audit_conn.autocommit = True
        with main_conn.transaction():
            yield AuthDeps(
                users=PostgresUserRepository(main_conn),
                refresh_tokens=PostgresRefreshTokenStore(main_conn),
                audit=PostgresAuditLog(audit_conn),
                clock=SystemClock(),
                settings=config.tokens(),
            )
```

Tests inject a fake factory that yields fake ports — that is how [test_integration.py](../../auth_service/tests/test_integration.py) exercises the full FastAPI stack without Postgres.

## Entry point: `main.py`

[main.py](../../auth_service/src/auth_service/infrastructure/main.py):

```python
from auth_service.infrastructure.app import create_app
from auth_service.infrastructure.config import Config

app = create_app(Config())
```

Runs as `uvicorn auth_service.infrastructure.main:app`. The `Config()` call loads env vars at import time — if a required env var is missing, the process fails to start with a pydantic-settings error, which is what we want.

## Logging

Logger name `auth` at module level in [app.py](../../auth_service/src/auth_service/infrastructure/app.py). Log lines use a stable prefix so fail2ban can grep them later:

- `LOGIN_FAILED username=%s`
- `LOGIN_SUCCESS username=%s`
- `REFRESH_FAILED`
- `REGISTER user_id=%s username=%s`

fail2ban config not shipped yet — [flag 3](../../flags.md).

## Import discipline

Verify with:

```
$ grep -R "^import\|^from" auth_service/src/auth_service/infrastructure/ | grep auth_service
```

Every import from `auth_service.*` points at `domain.` or `application.`. Nothing else in `auth_service` depends on `infrastructure`.
