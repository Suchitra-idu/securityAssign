# Flags

Follow-up items surfaced during build. Not blockers for what's landed, but worth doing before the next milestone or the report.

## Security

### 1. Timing-safe unknown-user login
`login()` returns early when the username doesn't exist, skipping bcrypt. An attacker can distinguish "user exists / wrong password" from "user doesn't exist" by response time (~100ms bcrypt vs. ~0ms early return) — a real user-enumeration side channel. Fix: verify the submitted password against a precomputed dummy hash constant in the unknown-user branch.
- File: [auth_service/src/auth_service/application/login.py](auth_service/src/auth_service/application/login.py)
- Effort: ~3 lines + one module-level constant.

### 2. Admin bootstrap mechanism
`POST /register` locks `role="customer"` and rejects any `role` field in the request body (via Pydantic `extra="forbid"`). There is currently no path to create the first admin. Options: (a) one-time seed SQL executed at compose bring-up, (b) an env-driven bootstrap that inserts an admin on first boot if none exists, (c) a CLI subcommand. Pick before demoing admin-only RBAC on banking.
- Files: [auth_service/src/auth_service/infrastructure/schema.sql](auth_service/src/auth_service/infrastructure/schema.sql), [auth_service/src/auth_service/infrastructure/main.py](auth_service/src/auth_service/infrastructure/main.py)

### 3. fail2ban filter not shipped
The auth service already emits stable-prefix log lines (`LOGIN_FAILED username=...`) intended for fail2ban to grep, but no filter/jail config exists yet.
- Files to add: `deploy/fail2ban/filter.d/auth-login.conf`, `deploy/fail2ban/jail.d/auth.conf`
- Depends on: log shipping shape once Docker Compose logging driver is decided.

## Contracts (per CLAUDE.md "must be agreed up front and never changed silently")

### 4. Token payload contract doc
The banking service will verify tokens against a payload shape currently pinned only by [auth_service/src/auth_service/application/tokens.py:23-30](auth_service/src/auth_service/application/tokens.py#L23-L30) and the auth tests. CLAUDE.md says this must live somewhere both people see. [contracts/](contracts/) is still empty.
- File to add: `contracts/token_payload.md` — algorithm (`EdDSA`), claims (`sub`, `role`, `iat`, `exp`), TTL bounds, public-key retrieval endpoint.

### 5. Crypto function boundary doc
Same rationale as (4), for the shared_security public API (`sign_token`, `verify_token`, `sign_transaction`, `verify_transaction`, `encrypt_field`, `decrypt_field`, `hash_password`, `verify_password`, `compute_chain_hash`, `verify_chain`, `canonical_json_bytes`).
- File to add: `contracts/crypto_boundary.md`

## Testing

### 6. Real-Postgres integration test
Route + Pydantic + application-layer integration is covered via `TestClient` with fake ports. The Postgres impls (repos, hash-chained audit sink, `LOCK TABLE` behaviour) are only smoke-testable via `docker compose up`. Add a test that stands up Postgres (testcontainers-python or a compose profile) and runs the same TestClient flow against real repos, then verifies the audit chain with `shared_security.audit_chain.verify_chain`.
- File to add: `auth_service/tests/test_integration_postgres.py`

## Deployment

### 7. Flip compose network to `internal: true` when Caddy lands
Compose network is currently `internal: false` because auth is the only externally-reachable service. Once Caddy fronts everything, only Caddy should be published — flip to `internal: true` so the auth service and Postgres cannot reach the internet either.
- File: [deploy/compose/docker-compose.yml](deploy/compose/docker-compose.yml)

### 8. Private key handling in production
The Ed25519 private key is currently passed as an env var (`AUTH_SIGNING_PRIVATE_KEY_PEM`). Fine for local/demo. For anything realer, mount it as a Docker secret or a read-only file and load via `Config` file-path field. Note in the report if we don't actually change this.
- File: [auth_service/src/auth_service/infrastructure/config.py](auth_service/src/auth_service/infrastructure/config.py)

## Housekeeping

### 9. Vestigial empty directories under `src/shared_security/`
`application/`, `domain/`, `infrastructure/` directories exist under [shared_security/src/shared_security/](shared_security/src/shared_security/) but the shared module is intentionally flat per CLAUDE.md. Safe to delete once confirmed.
