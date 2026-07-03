# Security controls map

The assignment lists security points that count toward the grade (see [../../CLAUDE.md](../../CLAUDE.md) and [../../DEV_GUIDE.md](../../DEV_GUIDE.md)). This page maps each point to the code that implements it, with an honest "done / partial / not built" status.

## Legend
- ✅ **Done** — implemented and tested.
- 🟡 **Partial** — implemented but with a gap noted in [../../flags.md](../../flags.md).
- ❌ **Not built** — planned, not implemented yet.

## Points

### 1. TLS 1.3, client → proxy ❌
Requires Caddy + certificate setup. Not started.

### 2. Firewall, network isolation, no published database port 🟡
Compose file leaves Postgres without a `ports:` block, so it is only reachable inside the internal Docker network. See [../../deploy/compose/docker-compose.yml](../../deploy/compose/docker-compose.yml).

Gap: the network is currently `internal: false` because auth_service must be reachable externally until Caddy fronts it. Flip to `internal: true` once Caddy lands ([flag 7](../../flags.md)).

### 3. WAF, Coraza on the OWASP core rule set ❌
Not built. Fallback path per DEV_GUIDE if time runs short: Caddy rate-limiting only.

### 4. HTTPS, proxy → services ❌
Depends on Caddy. Not built.

### 5. Password hashing + token signing (auth service) ✅
- **Password hashing** — bcrypt. Implementation: [passwords.py](../../shared_security/src/shared_security/passwords.py). Tests: [test_passwords.py](../../shared_security/tests/test_passwords.py). See [../02-shared-security/passwords.md](../02-shared-security/passwords.md).
- **Token signing** — Ed25519 (EdDSA) JWT via PyJWT. Algorithm is pinned by name; `alg` header is never trusted. Implementation: [tokens.py](../../shared_security/src/shared_security/tokens.py). The classic algorithm-confusion attack is explicitly covered by [test_algorithm_confusion_hs256_rejected](../../shared_security/tests/test_tokens.py). See [../02-shared-security/tokens.md](../02-shared-security/tokens.md).

Gap: unknown-user login is not timing-safe ([flag 1](../../flags.md)).

### 6. Access control (customer vs admin RBAC) 🟡
- **Roles exist and are minted into tokens** — the `role` claim is set from the stored user role at login and preserved through refresh. Implementation: [mint_token_pair](../../auth_service/src/auth_service/application/tokens.py). Locked by test [test_login_success_returns_verifiable_access_token_with_role](../../auth_service/tests/test_login.py) and [test_refresh_preserves_subject_and_role](../../auth_service/tests/test_refresh.py).
- **Public `/register` cannot create admins** — Pydantic `extra="forbid"` on `RegisterRequest` rejects any `role` field with 422, and the route hardcodes `role="customer"`. Locked by [test_register_forbids_role_field_from_request](../../auth_service/tests/test_integration.py).

Gap: the actual "customer cannot reach another customer's account, customer cannot perform admin action" enforcement lives in banking_service, which is not built. Also no admin bootstrap path ([flag 2](../../flags.md)).

### 7. Token verification, field encryption, transaction signing (banking service) ❌
- **Token verification** helper exists in shared_security ([tokens.py](../../shared_security/src/shared_security/tokens.py)) and is exercised by auth's own tests. Banking service (the actual consumer) is not built.
- **Field encryption** primitive exists ([field_crypto.py](../../shared_security/src/shared_security/field_crypto.py)). No consumer yet.
- **Transaction signatures** primitive exists ([transaction_signatures.py](../../shared_security/src/shared_security/transaction_signatures.py)). No consumer yet.

### 8. TLS services → database ❌
Postgres inside compose is currently on plain TCP over the internal network. Enabling TLS in Postgres and requiring `sslmode=require` in the connection string is a config change; not done.

### 9. Encryption at rest for sensitive fields ❌
The `field_crypto` primitive exists (AES-256-GCM). Banking service will use it on write and read. Not consumed yet.

### 10. Hash-chained audit log ✅
- **Primitive** — `compute_chain_hash` and `verify_chain` in [audit_chain.py](../../shared_security/src/shared_security/audit_chain.py). Test [test_audit_chain.py](../../shared_security/tests/test_audit_chain.py) proves that any tampered record breaks the chain.
- **Auth service integration** — `PostgresAuditLog` maintains the chain across concurrent writers using `LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`, and writes on a separate autocommit connection so failed operations (login failures, refresh failures) still persist their audit record. Implementation: [audit_log.py](../../auth_service/src/auth_service/infrastructure/audit_log.py). Design rationale: [../03-auth-service/audit-log-durability.md](../03-auth-service/audit-log-durability.md).

### 11. Encrypted backups ❌
Backup script and encrypted storage not built.

### Plus: fail2ban IDS on auth logs 🟡
- **Log lines exist in stable-prefix format** — the FastAPI routes in [app.py](../../auth_service/src/auth_service/infrastructure/app.py) emit `LOGIN_FAILED username=...` and `REFRESH_FAILED` on failure. These are grep-friendly for fail2ban.
- **fail2ban filter / jail configuration not shipped** ([flag 3](../../flags.md)).

## Summary
Of the 12 numbered points plus IDS: 3 are done, 3 are partial (with concrete follow-ups in flags.md), and 7 depend on components not built yet (WAF, TLS, banking_service, backup). The done and partial points are the ones the auth-side owner (Person A) has committed to and tested; the others are on the schedule but were out of scope for this doc.
