# Database schema

Three tables. All in the default `public` schema. DDL lives in [schema.sql](../../auth_service/src/auth_service/infrastructure/schema.sql) and is applied idempotently by `apply_schema` in [db.py](../../auth_service/src/auth_service/infrastructure/db.py) at service startup.

## `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer', 'admin')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

| Column | Notes |
|--------|-------|
| `id` | UUIDv4, assigned in [register.py](../../auth_service/src/auth_service/application/register.py). Used as the JWT `sub` claim. |
| `username` | Unique. Charset and length enforced at the HTTP boundary; DB unique constraint catches the check-then-insert race. |
| `password_hash` | Bcrypt hash string (starts with `$2b$12$…`). Never plaintext. |
| `role` | `CHECK` constraint defends against direct SQL insertions with bad roles. Application-level, `Role = Literal["customer", "admin"]` provides the same guarantee at boundaries. |
| `created_at` | For audit reconstruction; not read by the app. |

Constraint names:
- Primary key `users_pkey`.
- Unique constraint `users_username_key` — the psycopg `UniqueViolation` raised on duplicate insert is caught by [PostgresUserRepository.add](../../auth_service/src/auth_service/infrastructure/repositories/users_repo.py) and re-raised as `UsernameTaken`.

## `refresh_tokens`

```sql
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS refresh_tokens_user_id_idx ON refresh_tokens(user_id);
```

| Column | Notes |
|--------|-------|
| `token_hash` | Primary key. SHA-256 hex of the raw refresh token. **The raw token is never persisted.** |
| `user_id` | FK to `users.id`. `ON DELETE CASCADE` so removing a user removes their sessions in one step. |
| `expires_at` | Unix seconds. `refresh_ttl` seconds after issue. BIGINT because Postgres INT would run out in 2038. |
| `created_at` | Not read by the app. Useful for forensic queries. |

The user_id index supports "remove all refresh tokens for user X" queries — not called by the current app but useful for future "log out everywhere" or reuse-detection logic.

## `audit_log`

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    event JSONB NOT NULL,
    prev_hash BYTEA NOT NULL,
    hash BYTEA NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

| Column | Notes |
|--------|-------|
| `id` | `BIGSERIAL` — monotonic insertion order. `ORDER BY id` reproduces the chain. |
| `event` | JSONB. The full canonical event dict. Queryable if needed. |
| `prev_hash` | 32-byte SHA-256. `GENESIS_HASH` (32 zero bytes) for the very first row. |
| `hash` | 32-byte SHA-256 of `prev_hash || canonical_json_bytes(event)`. |
| `created_at` | Wall-clock timestamp. Not used for verification (`event["at"]` is the canonical time). |

Chain-integrity design and concurrency handling: [../03-auth-service/audit-log-durability.md](../03-auth-service/audit-log-durability.md).

Chain math: [../02-shared-security/audit-chain.md](../02-shared-security/audit-chain.md).

## Migration story

Currently there is no migration tool — no Alembic, no separate migration files. `apply_schema` runs on every auth_service start and executes `schema.sql`. Because every `CREATE TABLE` uses `IF NOT EXISTS`, and no schema change is ever made once shipped, this is safe today.

**Non-trivial schema evolution will need a migration tool.** For the demo timeline, `schema.sql` is enough. If banking service also uses the same Postgres, banking maintains its own schema file that its own service applies on startup.

## Row counts (expected orders of magnitude)

- `users` — user-count. Bounded by real user growth.
- `refresh_tokens` — up to one row per active refresh token per user. Rotated (deleted + reinserted) on every refresh. In steady state, one row per active session.
- `audit_log` — grows with every event. Register + login + refresh + failures. Grows unbounded; retention policy is not built. Deletion breaks the chain, so a real retention strategy would archive old segments to an append-only bucket rather than DELETE.

## Backup considerations

Not implemented — the encrypted backup job is a separate assignment security point (not yet built). When built, dump options:

- `pg_dump` for a logical snapshot.
- `pg_basebackup` for a physical snapshot.
- Ship encrypted with an offline key.

The audit log is the most sensitive: preserving order across restore matters for chain verification. `pg_dump --data-only` preserves order via `COPY`, but `pg_dump --inserts` does not always — a restore-verify pass is worth adding.

## Direct inspection

While iterating, useful queries:

```sql
-- users
SELECT id, username, role, created_at FROM users ORDER BY created_at DESC LIMIT 10;

-- active sessions
SELECT user_id, expires_at, to_timestamp(expires_at) AS expires_at_wall
  FROM refresh_tokens ORDER BY expires_at DESC LIMIT 10;

-- last N audit events
SELECT id, event->>'event' AS kind, event, encode(prev_hash, 'hex') AS prev, encode(hash, 'hex') AS h
  FROM audit_log ORDER BY id DESC LIMIT 10;

-- verify chain end-to-end (needs a script — the primitive is in shared_security.audit_chain.verify_chain)
```
