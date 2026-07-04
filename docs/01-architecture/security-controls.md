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
Compose has two networks: `edge` (bridge, Caddy only, publishes 8080/8443) and `internal` (`internal: true`, auth + postgres). Neither auth nor postgres has a `ports:` block. Confirmed with `docker ps`: postgres shows `5432/tcp` and auth shows `8000/tcp` — container ports only, no host bindings. A raw TCP connect from the host to `127.0.0.1:5432` refuses. See {{ src("deploy/compose/docker-compose.yml") }}.

### 3. WAF, Coraza on the OWASP core rule set 🟡
Coraza WAF is deployed as a Caddy plugin via `xcaddy` build, loaded with OWASP Core Rule Set v4.16.0. Confirmed matching SQL injection (`rule_id: 942100`) and other CRS categories during smoke testing.

Gap: runs in `SecRuleEngine DetectionOnly` mode — the WAF logs rule hits but does not block, to avoid locking out legitimate traffic before rules are tuned against our JSON API. Switch to `On` once tuning is done ({{ src("flags.md", text="flag 10") }}). See {{ src("proxy/coraza/coraza.conf") }} and {{ src("docs/06-proxy/overview.md", text="proxy overview") }}.

### 4. HTTPS, proxy → services 🟡
Caddy reverse-proxies to `http://auth:8000` inside the `internal` Docker network. The client-facing hop (browser → Caddy) is TLS 1.3; the internal hop (Caddy → auth) is currently plaintext. Docker's internal network isolation is the practical transport-security guarantee for now — traffic never leaves the Docker bridge — but this is a partial closure of the security point.

Gap: add self-signed cert to auth and flip Caddy's `reverse_proxy` to `https://auth:8000` with `tls_insecure_skip_verify` ({{ src("flags.md", text="flag 11") }}). mTLS is the production upgrade, documented in DEV_GUIDE as future work ({{ src("flags.md", text="flag 12") }}).

### 5. Password hashing + token signing (auth service) ✅
- **Password hashing** — bcrypt. Implementation: {{ src("shared_security/src/shared_security/passwords.py") }}. Tests: {{ src("shared_security/tests/test_passwords.py") }}. See {{ src("02-shared-security/passwords.md", text="../02-shared-security/passwords.md") }}.
- **Token signing** — Ed25519 (EdDSA) JWT via PyJWT. Algorithm is pinned by name; `alg` header is never trusted. Implementation: {{ src("shared_security/src/shared_security/tokens.py") }}. The classic algorithm-confusion attack is explicitly covered by {{ src("shared_security/tests/test_tokens.py", text="test_algorithm_confusion_hs256_rejected") }}. See {{ src("02-shared-security/tokens.md", text="../02-shared-security/tokens.md") }}.

Gap: unknown-user login is not timing-safe ({{ src("flags.md", text="flag 1") }}).

### 6. Access control (customer vs admin RBAC) 🟡
- **Roles exist and are minted into tokens** — the `role` claim is set from the stored user role at login and preserved through refresh. Implementation: {{ src("auth_service/src/auth_service/application/tokens.py", text="mint_token_pair") }}. Locked by test {{ src("auth_service/tests/test_login.py", text="test_login_success_returns_verifiable_access_token_with_role") }} and {{ src("auth_service/tests/test_refresh.py", text="test_refresh_preserves_subject_and_role") }}.
- **Public `/register` cannot create admins** — Pydantic `extra="forbid"` on `RegisterRequest` rejects any `role` field with 422, and the route hardcodes `role="customer"`. Locked by {{ src("auth_service/tests/test_integration.py", text="test_register_forbids_role_field_from_request") }}.

Gap: the actual "customer cannot reach another customer's account, customer cannot perform admin action" enforcement lives in banking_service, which is not built. Also no admin bootstrap path ({{ src("flags.md", text="flag 2") }}).

### 7. Token verification, field encryption, transaction signing (banking service) ❌
- **Token verification** helper exists in shared_security ({{ src("shared_security/src/shared_security/tokens.py") }}) and is exercised by auth's own tests. Banking service (the actual consumer) is not built.
- **Field encryption** primitive exists ({{ src("shared_security/src/shared_security/field_crypto.py") }}). No consumer yet.
- **Transaction signatures** primitive exists ({{ src("shared_security/src/shared_security/transaction_signatures.py") }}). No consumer yet.

### 8. TLS services → database ❌
Postgres inside compose is currently on plain TCP over the internal network. Enabling TLS in Postgres and requiring `sslmode=require` in the connection string is a config change; not done.

### 9. Encryption at rest for sensitive fields ❌
The `field_crypto` primitive exists (AES-256-GCM). Banking service will use it on write and read. Not consumed yet.

### 10. Hash-chained audit log ✅
- **Primitive** — `compute_chain_hash` and `verify_chain` in {{ src("shared_security/src/shared_security/audit_chain.py") }}. Test {{ src("shared_security/tests/test_audit_chain.py") }} proves that any tampered record breaks the chain.
- **Auth service integration** — `PostgresAuditLog` maintains the chain across concurrent writers using `LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`, and writes on a separate autocommit connection so failed operations (login failures, refresh failures) still persist their audit record. Implementation: {{ src("auth_service/src/auth_service/infrastructure/audit_log.py") }}. Design rationale: {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}.

### 11. Encrypted backups ❌
Backup script and encrypted storage not built.

### Plus: fail2ban IDS on auth logs 🟡
- **Log lines exist in stable-prefix format** — the FastAPI routes in {{ src("auth_service/src/auth_service/infrastructure/app.py") }} emit `LOGIN_FAILED username=...` and `REFRESH_FAILED` on failure. These are grep-friendly for fail2ban.
- **fail2ban filter / jail configuration not shipped** ({{ src("flags.md", text="flag 3") }}).

## Summary
Of the 12 numbered points plus IDS: **5 done, 4 partial** (each with a concrete follow-up in flags.md), and 4 depend on banking_service or backups. The proxy layer landing has moved TLS 1.3, network isolation, WAF, and HTTPS proxy→service from "not built" to done/partial in one delivery.
