# Documentation

Reference documentation for the secure banking application. Covers **only what is currently implemented**. Items not yet built (mTLS between Caddy and services, Coraza in `SecRuleEngine On` after tuning) are called out inline and tracked in {{ src("flags.md", text="../flags.md") }}. See {{ src("DEV_GUIDE.md", text="../DEV_GUIDE.md") }} for the original design intent.

## What is currently implemented

- **shared_security** — cryptographic and integrity primitives shared by all services: bcrypt password hashing, Ed25519 JWT sign/verify, AES-256-GCM field encryption, canonical-JSON transaction signatures, SHA-256 hash-chained audit log.
- **auth_service** — FastAPI service that owns identity and tokens. Register, login (timing-safe on unknown user), refresh (with rotation), public-key endpoint, admin bootstrap, audit-logged auth events. Three-layer clean architecture (domain / application / infrastructure).
- **banking_service** — FastAPI service that owns accounts, transactions, and only the auth *public* key. Verifies tokens on every request, enforces customer-vs-admin RBAC, encrypts sensitive fields at rest with AES-256-GCM, signs every transfer with its own Ed25519 keypair, audit-logs every data change. Same three-layer architecture.
- **Proxy + WAF + TLS** — Caddy 2.11 with Coraza (OWASP CRS v4.16.0, DetectionOnly) and per-IP rate limiting. TLS 1.3 client → Caddy; HTTPS Caddy → auth and Caddy → banking (self-signed on the inside). Auth on the root, banking on `/banking/*`.
- **fail2ban IDS** — filter, jail, and README under {{ src("deploy/fail2ban/") }}. Watches the auth log for `LOGIN_FAILED ip=<host>` / `REFRESH_FAILED ip=<host>` lines.
- **Docker packaging** — `Dockerfile` per service, a Docker Compose file that runs Caddy on the `edge` network and Postgres + auth + banking + backup on `internal: true` (no route to host, no outbound internet). Postgres init script creates a separate `banking` database on first boot.
- **TLS to Postgres** — custom Postgres image bakes a dev CA + server cert. `hostssl`-only `pg_hba.conf` rejects any plain-text connection. Services connect with `sslmode=verify-ca`. `pg_stat_ssl` confirms every pool connection is TLS 1.3.

## Reading order

If you have never seen this repo before, read in this order:

1. [01-architecture/overview.md](01-architecture/overview.md) — one-page picture of what runs where and why.
2. [01-architecture/clean-architecture.md](01-architecture/clean-architecture.md) — the three-layer rule and how it's applied.
3. [01-architecture/security-controls.md](01-architecture/security-controls.md) — mapping between the assignment's security points and the code.
4. [01-architecture/contracts.md](01-architecture/contracts.md) — the two contracts CLAUDE.md says must be locked: token payload and crypto boundary.
5. Then dive into a module: [02-shared-security/overview.md](02-shared-security/overview.md), [03-auth-service/overview.md](03-auth-service/overview.md), [06-proxy/overview.md](06-proxy/overview.md), or [07-banking-service/overview.md](07-banking-service/overview.md).

## Index

### Architecture
- [Overview](01-architecture/overview.md)
- [Clean architecture applied](01-architecture/clean-architecture.md)
- [Security controls map](01-architecture/security-controls.md)
- [Locked contracts](01-architecture/contracts.md)

### Shared security module
- [Overview](02-shared-security/overview.md)
- [Password hashing](02-shared-security/passwords.md)
- [Tokens (Ed25519 JWT)](02-shared-security/tokens.md)
- [Field encryption (AES-256-GCM)](02-shared-security/field-crypto.md)
- [Transaction signatures](02-shared-security/transaction-signatures.md)
- [Audit hash chain](02-shared-security/audit-chain.md)
- [Canonical JSON](02-shared-security/canonical-json.md)

### Auth service
- [Overview](03-auth-service/overview.md)
- [Domain layer](03-auth-service/domain-layer.md)
- [Application layer](03-auth-service/application-layer.md)
- [Infrastructure layer](03-auth-service/infrastructure-layer.md)
- [Flow: register](03-auth-service/flow-register.md)
- [Flow: login](03-auth-service/flow-login.md)
- [Flow: refresh](03-auth-service/flow-refresh.md)
- [Flow: public-key](03-auth-service/flow-public-key.md)
- [Audit-log durability model](03-auth-service/audit-log-durability.md)
- [Input validation rules](03-auth-service/input-validation.md)

### Banking service
- [Overview](07-banking-service/overview.md)

### Proxy / WAF / TLS
- [Overview](06-proxy/overview.md)

### Deployment
- [Running locally](04-deployment/running-locally.md)
- [Docker image](04-deployment/docker-image.md)
- [Environment variables](04-deployment/env-vars.md)
- [Database schema](04-deployment/database-schema.md)

### Testing
- [Strategy: TDD on the security-critical core](05-testing/strategy.md)
- [Running tests](05-testing/running-tests.md)
- [What each test proves](05-testing/what-tests-prove.md)

## Conventions used in these docs

- **Clickable code pointers.** Every claim about behaviour links to the file that implements it, often at a line range: `{{ src("shared_security/src/shared_security/tokens.py", lines="23-30") }}`. If a doc says something the code no longer does, believe the code and file a fix in {{ src("flags.md") }}.
- **Threat model per primitive.** Each primitive doc has a "What this defends against" and a "What this does not defend against" section. Both matter — the omissions are as informative as the coverage.
- **Rationale over description.** Design choices (bcrypt vs Argon2id, opaque vs JWT refresh tokens, two DB connections per request) come with the *why*, because someone reading this in six months will need to know whether to preserve the choice or change it.
