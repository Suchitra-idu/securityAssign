# auth_service — overview

FastAPI service that owns identity and tokens. Signs. Never verifies for external consumers directly — the public key is published so banking_service can verify offline. Every state-changing event lands in the hash-chained audit log.

## Responsibilities

- **Register** — create users with bcrypt-hashed passwords. Public endpoint locks role to `customer`.
- **Login** — verify password, mint access token + refresh token.
- **Refresh** — rotate refresh token, mint new access + refresh pair.
- **Expose public key** — so token verifiers (banking, later) can check signatures.
- **Validate all input at the edge** — Pydantic rejects malformed requests with 422 before use cases run.
- **Audit-log every auth event** — success and failure, hash-chained.

## Three layers

Per {{ src("01-architecture/clean-architecture.md", text="../01-architecture/clean-architecture.md") }}, dependencies point inward only:

```
auth_service/
├── pyproject.toml
├── Dockerfile
├── src/auth_service/
│   ├── domain/                   ← pure data + errors, no imports beyond stdlib
│   │   ├── users.py              ← User, Role
│   │   ├── refresh.py            ← RefreshRecord
│   │   └── errors.py             ← UsernameTaken, InvalidCredentials, InvalidRefreshToken
│   ├── application/              ← use cases + ports + settings
│   │   ├── ports.py              ← UserRepository, RefreshTokenStore, AuditLog, Clock (Protocols)
│   │   ├── settings.py           ← TokenSettings
│   │   ├── deps.py               ← AuthDeps
│   │   ├── tokens.py             ← TokenPair, mint_token_pair, hash_refresh_token
│   │   ├── audit.py              ← emit() — enforces {"event", "at", ...} shape
│   │   ├── register.py           ← register use case
│   │   ├── login.py              ← login use case
│   │   └── refresh.py            ← refresh use case
│   └── infrastructure/           ← FastAPI, Postgres, config, wiring
│       ├── config.py             ← env-driven Config via pydantic-settings
│       ├── clock.py              ← SystemClock
│       ├── db.py                 ← psycopg3 pool + schema loader
│       ├── schema.sql            ← DDL for users, refresh_tokens, audit_log
│       ├── schemas.py            ← Pydantic request/response models
│       ├── repositories/
│       │   ├── users_repo.py     ← PostgresUserRepository
│       │   └── refresh_repo.py   ← PostgresRefreshTokenStore
│       ├── audit_log.py          ← PostgresAuditLog (hash-chained)
│       ├── app.py                ← create_app factory + routes
│       └── main.py               ← uvicorn entry
└── tests/
    ├── conftest.py               ← fake ports + fixtures
    ├── test_register.py          ← application-layer tests
    ├── test_login.py
    ├── test_refresh.py
    └── test_integration.py       ← FastAPI TestClient + fake deps
```

Each layer's contract:

- **Domain** — data shapes and errors only. Domain files import nothing beyond `dataclasses` and `typing`.
- **Application** — use cases orchestrate domain + ports. Depends on `shared_security` for crypto and on domain types. Does not know about HTTP or SQL.
- **Infrastructure** — FastAPI routes, Postgres implementations, config from env. Depends inward.

Deep dives:
- [Domain layer](domain-layer.md)
- [Application layer](application-layer.md)
- [Infrastructure layer](infrastructure-layer.md)

## Endpoints

| Method | Path | Purpose | Response |
|--------|------|---------|----------|
| `POST` | `/register` | Create a customer | `201 UserResponse` |
| `POST` | `/login` | Exchange credentials for tokens | `200 TokenResponse` |
| `POST` | `/refresh` | Rotate refresh token, issue new pair | `200 TokenResponse` |
| `GET`  | `/public-key` | Return Ed25519 public key + algorithm | `200 PublicKeyResponse` |
| `GET`  | `/health` | Liveness probe | `200 {"status":"ok"}` |

Flow docs:
- [Register flow](flow-register.md)
- [Login flow](flow-login.md)
- [Refresh flow](flow-refresh.md)
- [Public-key flow](flow-public-key.md)

## Two special design decisions

Two things about this service are worth understanding independently:

1. **[Audit-log durability model](audit-log-durability.md)** — why the audit sink runs on a *separate* autocommit connection, and why every write holds `LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`.
2. **[Input validation rules](input-validation.md)** — the character sets, length bounds, and `extra="forbid"` rejection that Pydantic enforces before any use case runs.

## Testing

Two test tiers:

- **Unit tests over the application layer** ({{ src("auth_service/tests/test_register.py") }}, {{ src("auth_service/tests/test_login.py") }}, {{ src("auth_service/tests/test_refresh.py") }}) — use fake ports, no HTTP, no database. Fast (~7 seconds). Test-first per CLAUDE.md.
- **Integration tests via TestClient** ({{ src("auth_service/tests/test_integration.py") }}) — real FastAPI app, still fake ports (injected via `deps_factory` override). Covers route wiring, Pydantic validation, error → HTTP translation. Not test-first per CLAUDE.md.

See {{ src("05-testing/what-tests-prove.md", text="../05-testing/what-tests-prove.md") }} for a walkthrough.

## What is not built here

- Postgres integration tests. Real DB round-trips are smoke-tested via `docker compose up`. Automated Postgres integration is a follow-up ({{ src("flags.md", text="flag 6") }}).
- Timing-safe unknown-user login ({{ src("flags.md", text="flag 1") }}).
- Admin bootstrap ({{ src("flags.md", text="flag 2") }}).
- fail2ban filter ({{ src("flags.md", text="flag 3") }}).

## Configuration

All via env vars, `AUTH_` prefix. See {{ src("04-deployment/env-vars.md", text="../04-deployment/env-vars.md") }}.
