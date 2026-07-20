# Infrastructure layer

FastAPI, Postgres, config, wiring. Where the outside world is bolted onto the pure inner layers.

Location: {{ src("banking_service/src/banking_service/infrastructure/", text="banking_service/src/banking_service/infrastructure/") }}.

## Config: `config.py`

{{ src("banking_service/src/banking_service/infrastructure/config.py") }}:

```python
class Config(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BANKING_", env_file=".env", extra="ignore")

    database_url: str

    auth_public_key_pem: str | None = None
    auth_public_key_path: str | None = None

    tx_signing_private_key_pem: str | None = None
    tx_signing_private_key_path: str | None = None
    tx_signing_public_key_pem: str | None = None
    tx_signing_public_key_path: str | None = None

    field_key_hex: str | None = None
    field_key_path: str | None = None

    pool_min_size: int = 1
    pool_max_size: int = 10
```

Sourced from `pydantic-settings`. Every field maps to a `BANKING_*` env var — see {{ src("04-deployment/env-vars.md", text="../04-deployment/env-vars.md") }}.

**Every key material accepts either an inline env var or a file path.** The `..._pem` / `..._hex` form is convenient for dev; the `..._path` form is what production uses with Docker secrets or mounted `tmpfs`. `_resolve` (a `model_validator(mode="after")`) reads the file into the corresponding `_pem` field if the path variant is set. Missing key material fails startup — the service refuses to run without a full crypto configuration.

Field-key handling is slightly different: hex string in env or hex string in a file. `Config.field_key()` decodes and enforces the 32-byte length at call time, not startup — but `create_app` calls it at startup, so an invalid field key still fails the container before any request runs.

## Clock: `clock.py`

{{ src("banking_service/src/banking_service/infrastructure/clock.py") }} — `SystemClock` returning `int(time.time())`. Same shape as auth. Exists as a class so tests substitute `FakeClock` for deterministic time.

## Database wiring: `db.py` + `schema.sql`

{{ src("banking_service/src/banking_service/infrastructure/db.py") }}:

```python
def build_pool(database_url, *, min_size, max_size) -> ConnectionPool
def apply_schema(pool) -> None
```

Sync psycopg3 pool, same reasoning as auth (see {{ src("03-auth-service/infrastructure-layer.md", text="../03-auth-service/infrastructure-layer.md") }}). Schema is idempotent (`CREATE TABLE IF NOT EXISTS`), applied once at startup. DDL lives at {{ src("banking_service/src/banking_service/infrastructure/schema.sql") }} — three tables: `accounts`, `transactions`, `audit_log`. Full DDL: [../04-deployment/database-schema.md](../04-deployment/database-schema.md).

Two things to notice in the schema:

- **`accounts.account_number`, `balance_minor`, `card_number` are `BYTEA`.** Not `TEXT`, not `BIGINT` — ciphertext bytes. The domain sees plaintext because the repository decrypts on read.
- **Foreign keys from `transactions` to `accounts` are UUID.** Both `from_account_id` and `to_account_id` reference `accounts.id`, so a transfer that lands in the DB has valid, existing endpoints.

## Repositories

Each repo takes a `Connection` (not a pool). FastAPI's dependency generator picks one from the pool per request and hands it to the repos. All queries in one request share a connection and can share a transaction.

### `accounts_repo.py` — the field-encryption boundary

{{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository") }} takes both the `Connection` and the 32-byte `field_key` in its constructor. Three columns are encrypted at the boundary:

```python
def add(self, account: Account) -> None:
    self._conn.execute(
        "INSERT INTO accounts (...) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            account.id,
            account.owner_id,
            encrypt_field(account.account_number.encode("utf-8"), self._key),
            encrypt_field(str(account.balance_minor).encode("utf-8"), self._key),
            encrypt_field(account.card_number.encode("utf-8"), self._key),
            account.status,
        ),
    )
```

Reads mirror it (`_to_account`):

```python
account_number = decrypt_field(bytes(row[2]), self._key).decode("utf-8")
balance_minor  = int(decrypt_field(bytes(row[3]), self._key).decode("utf-8"))
card_number    = decrypt_field(bytes(row[4]), self._key).decode("utf-8")
```

The crypto primitives are in {{ src("shared_security/src/shared_security/field_crypto.py") }} — AES-256-GCM with a random 12-byte nonce per row. Because the nonce is per-row, ciphertext for the same plaintext looks different each write, which rules out equality lookups on the ciphertext ({{ src("02-shared-security/field-crypto.md", text="../02-shared-security/field-crypto.md") }} explains why).

Two consequences worth spelling out:

**1. `get_by_account_number` is a scan.** No SQL predicate can filter on encrypted `account_number` — the ciphertext is different every row. So it reads every account, decrypts, and returns the first match:

```python
def get_by_account_number(self, account_number: str) -> Account | None:
    for account in self.list_all():
        if account.account_number == account_number:
            return account
    return None
```

Fine at demo scale. Production would add a deterministic search-hash column (HMAC of the number under a separate key) to make this a keyed lookup.

**2. `get` handles malformed UUIDs.** A caller supplying a non-UUID `account_id` would otherwise raise `psycopg.errors.InvalidTextRepresentation` and bubble up as a 500. The repo catches that (plus its `DataError` parent) and returns `None`, so the route sees "not found" and returns a clean 404:

```python
try:
    row = self._conn.execute("SELECT ... WHERE id = %s", (account_id,)).fetchone()
except (InvalidTextRepresentation, DataError):
    return None
```

Any state change is expressed as a fresh `Account` passed to `update`, which UPDATEs the row with freshly encrypted ciphertext. Freeze / unfreeze go through the same UPDATE — the status column is plaintext, so those calls re-encrypt fields that haven't changed. That's the price of never storing plaintext.

### `transactions_repo.py`

{{ src("banking_service/src/banking_service/infrastructure/repositories/transactions_repo.py") }}. Straightforward persistence — no encryption. The `signature` column is `BYTEA` and holds the raw 64-byte Ed25519 signature. `list_for_account` uses `WHERE from_account_id = %s OR to_account_id = %s` so a single query returns both incoming and outgoing.

Nothing here validates the signature — that's the application layer's job at read time, so the repo stays a dumb port.

### `audit_log.py`

{{ src("banking_service/src/banking_service/infrastructure/audit_log.py", text="PostgresAuditLog") }}. **Exact same pattern as auth's audit log**:

```python
def record(self, event: dict) -> None:
    with self._conn.transaction():
        self._conn.execute("LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE")
        row = self._conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev_hash = bytes(row[0]) if row else GENESIS_HASH
        new_hash = compute_chain_hash(prev_hash, canonical_json_bytes(event))
        self._conn.execute(
            "INSERT INTO audit_log (event, prev_hash, hash) VALUES (%s, %s, %s)",
            (Jsonb(event), prev_hash, new_hash),
        )
```

Two subtle things — both covered in depth in {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }} and applied identically here:

1. **Own transaction inside a caller-supplied autocommit connection.** Rejected transfers still get their `transfer_rejected` audit event even though the main transaction rolls back.
2. **`LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`.** Serialises concurrent writers so `SELECT last hash → compute → INSERT` cannot interleave and fork the chain.

The banking audit log is a **separate table in the `banking` database**. Auth's audit log lives in the `auth` database. Two independent hash chains, one per service, both verifiable by the same {{ src("shared_security/src/shared_security/audit_chain.py") }} helpers.

## Token verifier — the caller extractor

{{ src("banking_service/src/banking_service/infrastructure/token_verifier.py") }}:

```python
def bearer_caller(public_key: str):
    def _dep(authorization: str | None = Header(default=None)) -> Caller:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer token")
        token = authorization[len("Bearer "):].strip()
        try:
            claims = verify_token(token, public_key)
        except TokenError:
            raise HTTPException(401, "invalid token")
        role = claims.get("role")
        sub = claims.get("sub")
        if role not in ("customer", "admin") or not isinstance(sub, str):
            raise HTTPException(401, "malformed token claims")
        return Caller(user_id=sub, role=role)
    return _dep
```

- **`verify_token` is `shared_security.tokens.verify_token`** — the same function auth signs with, run in the "verify with public key" mode. Missing / malformed / expired / tampered → `TokenError` → 401.
- **Claim shape defensive check.** Even after signature verification passes, the code re-checks that `role` is one of the two allowed literals and `sub` is a string. That covers the "auth changes the claim shape without telling banking" failure mode — see {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md") }} for the locked token payload.
- **Returned `Caller` is the only auth signal the application layer sees.** Bad tokens fail before the use case runs. The use case can trust the caller struct.

Route wiring in `app.py` binds this as a FastAPI `Depends`:

```python
caller_dep = bearer_caller(banking_settings.auth_public_key)
...
def route(..., caller: Caller = Depends(caller_dep), ...): ...
```

Bound once at app startup, reused across every route.

## Pydantic schemas: `schemas.py`

{{ src("banking_service/src/banking_service/infrastructure/schemas.py") }}. `TransferRequest` uses `extra="forbid"` — full rules in [input-validation.md](input-validation.md). Response models (`AccountResponse`, `TransactionResponse`, `HealthResponse`) are declared for OpenAPI.

## FastAPI app factory: `app.py`

{{ src("banking_service/src/banking_service/infrastructure/app.py") }}. `create_app(config, deps_factory=None)`. If `deps_factory` is not supplied, the factory builds a Postgres-backed one that opens **two connections per request**:

```python
def deps_factory() -> Iterator[BankingDeps]:
    with pool.connection() as main_conn, pool.connection() as audit_conn:
        audit_conn.autocommit = True
        with main_conn.transaction():
            yield BankingDeps(
                accounts=PostgresAccountRepository(main_conn, field_key),
                transactions=PostgresTransactionRepository(main_conn),
                audit=PostgresAuditLog(audit_conn),
                clock=SystemClock(),
                settings=banking_settings,
            )
```

Same two-connection pattern as auth: main connection carries account + transaction writes under a per-request transaction; audit connection is autocommit so audit events survive `transfer_rejected` rollbacks.

Tests inject a fake factory that yields fake ports — that is how {{ src("banking_service/tests/test_integration.py") }} exercises the full FastAPI stack without Postgres or real crypto.

### Route → error mapping

| Route | Application errors → HTTP |
|-------|--------------------------|
| `POST /accounts` | – |
| `GET /accounts/me` | – |
| `GET /accounts/{id}` | `AccountNotFound` → 404, `NotAccountOwner` → 403 |
| `GET /accounts` | `Forbidden` → 403 (admin only) |
| `POST /accounts/{id}/freeze` | `Forbidden` → 403, `AccountNotFound` → 404 |
| `POST /accounts/{id}/unfreeze` | `Forbidden` → 403, `AccountNotFound` → 404 |
| `POST /transfers` | `AccountNotFound` → 404, `NotAccountOwner` → 403, `AccountFrozen` → 409, `InsufficientFunds` → 409, `InvalidTransfer` → 400 |
| `GET /transactions/{id}` | `AccountNotFound` → 404, `NotAccountOwner` → 403 |

The routes are thin — they catch the small set of domain exceptions and translate to `HTTPException`. Anything they don't catch is a genuine 500.

## Entry point: `main.py`

{{ src("banking_service/src/banking_service/infrastructure/main.py") }}:

```python
from banking_service.infrastructure.app import create_app
from banking_service.infrastructure.config import Config

app = create_app(Config())
```

Runs as `uvicorn banking_service.infrastructure.main:app`. `Config()` loads env vars at import time — a missing required env var (or a bad field key) fails the container before any request lands.

## Logging

Logger name `banking`. Stable prefixes so operators can grep:

- `ACCOUNT_OPENED ip=… user_id=… account_id=…`
- `ACCOUNT_FROZEN ip=… actor=… account_id=…`
- `ACCOUNT_UNFROZEN ip=… actor=… account_id=…`
- `TRANSFER ip=… user_id=… tx_id=…`
- `TRANSFER_REJECTED ip=… user_id=… from=… reason=…`

`_client_ip(request)` prefers `X-Real-IP` (set by Caddy) then falls back to `X-Forwarded-For` then the socket peer. Same helper shape as auth's `_client_ip`.

## Import discipline

Verify with:

```
$ grep -R "^import\|^from" banking_service/src/banking_service/infrastructure/ | grep banking_service
```

Every import from `banking_service.*` points at `domain.` or `application.`. Nothing else in `banking_service` depends on `infrastructure`.
