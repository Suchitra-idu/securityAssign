# Security controls map

The assignment lists security points that count toward the grade (see {{ src("CLAUDE.md", text="../../CLAUDE.md") }} and {{ src("DEV_GUIDE.md", text="../../DEV_GUIDE.md") }}). This page maps each point to the code that implements it, with an honest "done / partial / not built" status.

## Legend
- ✅ **Done** — implemented and tested.
- 🟡 **Partial** — implemented but with a gap noted in {{ src("flags.md", text="../../flags.md") }}.
- ❌ **Not built** — planned, not implemented yet.

## Points

### 1. TLS 1.3, client → proxy ✅
Caddy 2.11 terminates TLS on `:443` (published as host `:8443`) with a cert issued by its built-in local CA (`tls internal`). Confirmed with `openssl s_client`: `Protocol: TLSv1.3`, cipher `TLS_AES_128_GCM_SHA256`, issuer `Caddy Local Authority - ECC Intermediate`. HTTP on `:80` returns a 301 to HTTPS. See {{ src("proxy/caddy/Caddyfile") }} and {{ src("docs/06-proxy/overview.md", text="proxy overview") }}.

Production upgrade: swap the `localhost` site block for a real hostname and Caddy auto-obtains from Let's Encrypt (`tls internal` becomes `tls admin@example.com`).

### 2. Firewall, network isolation, no published database port ✅
Compose has two networks: `edge` (bridge, Caddy only, publishes 8080/8443) and `internal` (`internal: true`, auth + banking + postgres). Neither auth, banking, nor postgres has a `ports:` block. Confirmed with `docker ps`: postgres shows `5432/tcp`, auth and banking show `8000/tcp` — container ports only, no host bindings. A raw TCP connect from the host to `127.0.0.1:5432` refuses. See {{ src("deploy/compose/docker-compose.yml") }}.

### 3. WAF, Coraza on the OWASP core rule set 🟡
Coraza WAF is deployed as a Caddy plugin via `xcaddy` build, loaded with OWASP Core Rule Set v4.16.0. Confirmed matching SQL injection (`rule_id: 942100`) and other CRS categories during smoke testing.

Gap: runs in `SecRuleEngine DetectionOnly` mode — the WAF logs rule hits but does not block, to avoid locking out legitimate traffic before rules are tuned against our JSON API. Switch to `On` once tuning is done ({{ src("flags.md", text="flag 10") }}). See {{ src("proxy/coraza/coraza.conf") }} and {{ src("docs/06-proxy/overview.md", text="proxy overview") }}.

### 4. HTTPS, proxy → services ✅
Caddy reverse-proxies to `https://auth:8000` and `https://banking:8000` inside the `internal` Docker network. Both service images bake a self-signed RSA cert at build time and run uvicorn with `--ssl-keyfile` / `--ssl-certfile`; Caddy trusts them via `tls_insecure_skip_verify` in {{ src("proxy/caddy/Caddyfile") }}. Verified end-to-end in the smoke test. mTLS remains production future work per DEV_GUIDE ({{ src("flags.md", text="flag 12") }}).

### 5. Password hashing + token signing (auth service) ✅
- **Password hashing** — bcrypt. Implementation: {{ src("shared_security/src/shared_security/passwords.py") }}. Tests: {{ src("shared_security/tests/test_passwords.py") }}. See {{ src("02-shared-security/passwords.md", text="../02-shared-security/passwords.md") }}.
- **Token signing** — Ed25519 (EdDSA) JWT via PyJWT. Algorithm is pinned by name; `alg` header is never trusted. Implementation: {{ src("shared_security/src/shared_security/tokens.py") }}. The classic algorithm-confusion attack is explicitly covered by {{ src("shared_security/tests/test_tokens.py", text="test_algorithm_confusion_hs256_rejected") }}. See {{ src("02-shared-security/tokens.md", text="../02-shared-security/tokens.md") }}.
- **Timing-safe unknown-user login** — dummy bcrypt hash consulted when the username is unknown so response time matches wrong-password. Locked by {{ src("auth_service/tests/test_login.py", text="test_login_unknown_user_still_calls_bcrypt") }}.

### 6. Access control (customer vs admin RBAC) ✅
- **Roles in tokens** — the `role` claim is set from the stored user role at login and preserved through refresh. Implementation: {{ src("auth_service/src/auth_service/application/tokens.py", text="mint_token_pair") }}. Locked by {{ src("auth_service/tests/test_login.py", text="test_login_success_returns_verifiable_access_token_with_role") }} and {{ src("auth_service/tests/test_refresh.py", text="test_refresh_preserves_subject_and_role") }}.
- **Public `/register` cannot create admins** — Pydantic `extra="forbid"` on `RegisterRequest` rejects any `role` field with 422, and the route hardcodes `role="customer"`. Locked by {{ src("auth_service/tests/test_integration.py", text="test_register_forbids_role_field_from_request") }}.
- **Admin bootstrap** — env-driven, idempotent, seeds one admin on service start when `AUTH_INITIAL_ADMIN_USERNAME` and `AUTH_INITIAL_ADMIN_PASSWORD` are set. {{ src("auth_service/src/auth_service/application/bootstrap.py") }} + {{ src("auth_service/tests/test_bootstrap.py") }}.
- **Enforcement in banking** — every banking route depends on `bearer_caller` ({{ src("banking_service/src/banking_service/infrastructure/token_verifier.py") }}) which calls `verify_token(auth_public_key)` and extracts `(sub, role)` before the route runs. Use cases call `require_owner_or_admin` / `require_admin` in {{ src("banking_service/src/banking_service/application/authz.py") }} before touching data. Locked by {{ src("banking_service/tests/test_read_account.py", text="test_customer_cannot_read_other_customer_account") }}, {{ src("banking_service/tests/test_list_accounts.py", text="test_customer_cannot_list_all_accounts") }}, {{ src("banking_service/tests/test_freeze_account.py", text="test_customer_cannot_freeze_account") }}, {{ src("banking_service/tests/test_transfer.py", text="test_customer_cannot_transfer_from_someone_elses_account") }}, and end-to-end at HTTP level in {{ src("banking_service/tests/test_integration.py", text="test_customer_cannot_read_other_account") }}, {{ src("banking_service/tests/test_integration.py", text="test_customer_forbidden_from_admin_list") }}.

### 7. Token verification, field encryption, transaction signing (banking service) ✅
- **Token verification** — {{ src("banking_service/src/banking_service/infrastructure/token_verifier.py", text="bearer_caller") }} calls `shared_security.tokens.verify_token(auth_public_key)` on every request. Malformed / expired / tampered / missing tokens all return 401. Locked by {{ src("banking_service/tests/test_integration.py") }} (`test_missing_bearer_returns_401`, `test_tampered_token_returns_401`, `test_expired_token_returns_401`).
- **Field encryption** — the Postgres repository ({{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py") }}) encrypts `account_number`, `balance_minor`, and `card_number` on write with AES-256-GCM (`encrypt_field`) and decrypts on read. Domain and application layers never see ciphertext. Locked by {{ src("banking_service/tests/test_integration_postgres.py", text="test_sensitive_fields_are_ciphertext_on_disk") }} and `test_tampered_ciphertext_fails_to_decrypt`.
- **Transaction signing** — `transfer` builds a canonical payload of `(id, from, to, amount, at)` and calls `shared_security.transaction_signatures.sign_transaction(banking_private_key)`. Signature bytes are persisted on the row and re-verified on read; the API returns a `signature_valid` boolean per transaction. Live smoke test confirmed that mutating `amount_minor` in Postgres flips the flag to false without touching the signature bytes. Locked by {{ src("banking_service/tests/test_transfer.py", text="test_transfer_produces_verifiable_signature") }} and `test_tampered_transaction_signature_fails_verification`.

### 8. TLS services → database ✅
Postgres runs from a custom image ({{ src("deploy/compose/postgres/Dockerfile") }}) that bakes a dev CA + server cert. The mounted {{ src("deploy/compose/postgres/pg_hba.conf") }} declares `hostssl`-only rules and deliberately omits any plain-text `host` line, so a `psql "postgresql://...?sslmode=disable"` connection is rejected by Postgres before authentication:

```
FATAL: no pg_hba.conf entry for host "172.18.0.2", user "auth", database "auth", no encryption
```

Both `AUTH_DATABASE_URL` and `BANKING_DATABASE_URL` in {{ src("deploy/compose/docker-compose.yml") }} include `?sslmode=verify-ca&sslrootcert=/app/tls/pg-ca.crt`, so psycopg verifies the server cert against the CA that was baked into each service image. Verified in-container against `pg_stat_ssl`:

```
 pid | ssl | version |         cipher         | client_addr
-----+-----+---------+------------------------+-------------
  77 | t   | TLSv1.3 | TLS_AES_256_GCM_SHA384 | 172.18.0.4  ← banking pool
  78 | t   | TLSv1.3 | TLS_AES_256_GCM_SHA384 | 172.18.0.4
  79 | t   | TLSv1.3 | TLS_AES_256_GCM_SHA384 | 172.18.0.3  ← auth pool
  80 | t   | TLSv1.3 | TLS_AES_256_GCM_SHA384 | 172.18.0.3
```

Cert lifecycle: {{ src("deploy/compose/tls/generate.sh") }} produces the CA and server cert on the host; the outputs are gitignored. Rotation is a re-run of the script followed by `docker compose build`. Client-side mTLS (Postgres verifying the *client's* cert) is a straightforward next step; not built here.

### 9. Encryption at rest for sensitive fields ✅
`shared_security.field_crypto` (AES-256-GCM, 12-byte random nonce, no additional data) is used inside {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository") }} as the write and read path for `account_number`, `balance_minor`, and `card_number`. `SELECT balance_minor` in Postgres returns ciphertext bytes; the plaintext value never touches the database row. Verified live end-to-end: seeded a balance of `100000`, `psql` showed 60-ish bytes of ciphertext, the API returned `100000`. Locked by {{ src("banking_service/tests/test_integration_postgres.py", text="test_field_encryption_round_trip_across_transactions") }} and `test_sensitive_fields_are_ciphertext_on_disk`.

### 10. Hash-chained audit log ✅
- **Primitive** — `compute_chain_hash` and `verify_chain` in {{ src("shared_security/src/shared_security/audit_chain.py") }}. Test {{ src("shared_security/tests/test_audit_chain.py") }} proves that any tampered record breaks the chain.
- **Auth service integration** — `PostgresAuditLog` maintains the chain across concurrent writers using `LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`, and writes on a separate autocommit connection so failed operations (login failures, refresh failures) still persist their audit record. Implementation: {{ src("auth_service/src/auth_service/infrastructure/audit_log.py") }}. Design rationale: {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}.
- **Banking service integration** — same design, own `audit_log` table in the `banking` database. {{ src("banking_service/src/banking_service/infrastructure/audit_log.py") }}. Events include `account_opened`, `account_read`, `account_frozen`, `transfer`, and `transfer_rejected`. End-to-end chain verification landed by {{ src("banking_service/tests/test_integration_postgres.py", text="test_audit_chain_valid_end_to_end") }}.

### 11. Encrypted backups ✅
A `backup` sidecar ({{ src("deploy/backup/Dockerfile") }}) runs a `pg_dump | age` loop against both databases. The plaintext SQL is never persisted — `pg_dump` streams over TLS 1.3 into `age`, and only the ciphertext (`.sql.age`) hits the mounted `backup_data` volume. Schedule is `BACKUP_INTERVAL_SECONDS` (hourly by default) with retention `BACKUP_RETENTION` (7 by default).

**Public/private split** — the `age` recipient (public) is passed to the container via `BACKUP_AGE_RECIPIENT`. The identity (private) is deliberately absent from the container image; restore requires supplying it at exec time:

```
docker compose exec -e BACKUP_AGE_IDENTITY=$KEY backup \
    restore /backups/auth-20260704T121605Z.sql.age auth_restored
```

**Ciphertext-at-rest verified** — the first 100 bytes of every `.sql.age` file start with `age-encryption.org/v1` followed by an X25519 recipient stanza, not SQL. Attempting `age -d` inside the container without the identity: `no identity matched any of the recipients`.

**Restore drill verified** — took a backup after seeding a `users` row and audit-log events; ran `restore` into a fresh `auth_restored` database; queried `SELECT username, role FROM users` and got the expected row back with the audit log intact.

Trade-off: the backup container has network access to Postgres. A stronger model runs backups from an off-host worker whose only reach into the cluster is a read-only DB user; retained here for demo simplicity.

### Plus: fail2ban IDS on auth logs 🟡
- **Log lines exist in stable-prefix format** — the FastAPI routes in {{ src("auth_service/src/auth_service/infrastructure/app.py") }} emit `LOGIN_FAILED ip=<host> username=...` and `REFRESH_FAILED ip=<host>` on failure. These are grep-friendly for fail2ban.
- **fail2ban filter, jail, and README** shipped under {{ src("deploy/fail2ban/") }}. Filter matches `LOGIN_FAILED|REFRESH_FAILED ip=<HOST>`; jail bans for 1 hour after 5 hits in 5 minutes via `iptables-multiport`.
- **Gap** — Docker bridge NAT means Caddy sees the Docker gateway IP for host-originated traffic, not the real client. Fine for a demo; production would run Caddy with `network_mode: host` or sit behind a real load balancer with a trusted X-Forwarded-For chain ({{ src("flags.md", text="flag 13") }}).

## Summary
Of the 11 numbered points plus IDS: **10 done** and **2 partial** (WAF DetectionOnly, fail2ban client-IP NAT — each with a concrete follow-up in {{ src("flags.md", text="../../flags.md") }}). Every numbered point is at least partially implemented. The banking service landing moved points 6, 7, and 9 from "not built" to done in one delivery; the postgres-TLS work closed point 8; the encrypted-backup sidecar closed point 11.
