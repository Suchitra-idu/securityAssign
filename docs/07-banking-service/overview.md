# Banking service

The banking service owns accounts, transactions, and the freeze / unfreeze workflow. It holds **only the auth service's public key**, so it can verify tokens but never mint them. Every route requires a valid bearer token; every use case runs a role check before touching data; every sensitive column on disk is AES-256-GCM ciphertext; every transfer produces an Ed25519 signature over a canonical payload.

Same three-layer shape as auth: domain / application / infrastructure. Same "crypto through a boundary, keys in config" pattern.

Deep dives:
- [Domain layer](domain-layer.md)
- [Application layer](application-layer.md)
- [Infrastructure layer](infrastructure-layer.md)
- [Input validation](input-validation.md)
- [Flow: open account](flow-open-account.md)
- [Flow: transfer](flow-transfer.md)
- [Flow: freeze / unfreeze](flow-freeze-unfreeze.md)

## What it delivers

Cross-reference with the {{ src("docs/01-architecture/security-controls.md", text="security controls map") }}:

- **Point 6 — RBAC customer vs admin** ✅ Enforced in {{ src("banking_service/src/banking_service/application/authz.py") }} via `require_owner_or_admin` / `require_admin`. Called by every use case that touches account state.
- **Point 7 — Token verification, field encryption, transaction signing** ✅ All three inside this service.
- **Point 9 — Encryption at rest** ✅ Three account columns encrypted at the storage boundary in {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository") }}.
- **Point 10 — Hash-chained audit log** ✅ Same design as auth ({{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}) in its own `banking.audit_log` table.

## Routes

Behind Caddy at `/banking/*`. Prefix is stripped upstream, so the service internally sees the paths below.

| Method | Path | Role required | Purpose |
|--------|------|---------------|---------|
| POST | `/accounts` | customer | Open an account owned by the caller (12-digit account number, 16-digit card, balance 0). |
| GET | `/accounts/me` | customer | List accounts owned by the caller. |
| GET | `/accounts/{id}` | owner or admin | Read a single account. |
| GET | `/accounts` | admin | List all accounts. |
| POST | `/accounts/{id}/freeze` | admin | Freeze an account (idempotent). Frozen accounts reject transfers on both sides. |
| POST | `/accounts/{id}/unfreeze` | admin | Unfreeze an account (idempotent). Restores transfer eligibility. |
| POST | `/transfers` | source owner or admin | Debit source, credit destination, sign the transaction, audit. Destination is identified by `account_number`, not id. |
| GET | `/transactions/{account_id}` | owner or admin | List transactions for an account with `signature_valid` per row. |
| GET | `/health` | none | Liveness. |

All non-`/health` routes require `Authorization: Bearer <jwt>`. Missing / malformed / expired / tampered → 401. Wrong role → 403. Account not found → 404.

## The three layers

### Domain — {{ src("banking_service/src/banking_service/domain/") }}
Pure dataclasses and errors. Zero web / DB / crypto imports.

- {{ src("banking_service/src/banking_service/domain/accounts.py") }} — `Account(id, owner_id, account_number, balance_minor, card_number, status)`. `status: "active" | "frozen"`. Balance is minor units (integer). Plaintext at this layer — encryption happens at the storage boundary.
- {{ src("banking_service/src/banking_service/domain/transactions.py") }} — `Transaction(id, from_account_id, to_account_id, amount_minor, at, signature)`. `transaction_payload(tx) -> dict` is the canonical dict that gets signed; keeping it in the domain guarantees signing and verifying use the same payload shape.
- {{ src("banking_service/src/banking_service/domain/errors.py") }} — `AccountNotFound`, `NotAccountOwner`, `Forbidden`, `InsufficientFunds`, `AccountFrozen`, `InvalidTransfer`, `TamperedRecord`. Routes translate these into HTTP status codes.

### Application — {{ src("banking_service/src/banking_service/application/") }}
Use cases and role checks. Depends on domain + ports (`AccountRepository`, `TransactionRepository`, `AuditLog`, `Clock` in {{ src("banking_service/src/banking_service/application/ports.py") }}). Never imports FastAPI or psycopg.

The role check helper is the single place where "customer vs admin" is enforced:

```python
def require_owner_or_admin(caller: Caller, account: Account) -> None:
    if caller.role == "admin":
        return
    if account.owner_id != caller.user_id:
        raise NotAccountOwner

def require_admin(caller: Caller) -> None:
    if caller.role != "admin":
        raise Forbidden
```

Every use case that reads or mutates account state calls one of these before doing anything else. Tests pin the behaviour end-to-end:

- {{ src("banking_service/tests/test_read_account.py", text="test_customer_cannot_read_other_customer_account") }}
- {{ src("banking_service/tests/test_list_accounts.py", text="test_customer_cannot_list_all_accounts") }}
- {{ src("banking_service/tests/test_freeze_account.py", text="test_customer_cannot_freeze_account") }}
- {{ src("banking_service/tests/test_transfer.py", text="test_customer_cannot_transfer_from_someone_elses_account") }}

### Infrastructure — {{ src("banking_service/src/banking_service/infrastructure/") }}
Everything that touches the outside world. FastAPI routes, Postgres repos, config, wiring.

- {{ src("banking_service/src/banking_service/infrastructure/token_verifier.py", text="bearer_caller") }} — FastAPI dep. Extracts the bearer, calls `verify_token(auth_public_key)`, checks `role in {"customer", "admin"}` and `sub` is a string, returns a `Caller`.
- {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository") }} — encrypts three columns on write with `shared_security.field_crypto.encrypt_field`, decrypts on read. Balance stored as `str(int).encode()` inside AEAD so the domain never sees ciphertext.
- {{ src("banking_service/src/banking_service/infrastructure/repositories/transactions_repo.py") }} — plain persistence for `Transaction`. Signature is a `BYTEA` column.
- {{ src("banking_service/src/banking_service/infrastructure/audit_log.py") }} — copy of the same hash-chained audit log pattern as auth. See {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }} for why LOCK TABLE and autocommit.
- {{ src("banking_service/src/banking_service/infrastructure/config.py") }} — `BANKING_*` env vars. Auth public key and TX signing keys accept inline PEM or a mounted file path (Docker secret). Field key accepts hex string or a hex-in-a-file path. Validates on startup.

## Where the crypto lives

Three distinct crypto responsibilities, three distinct keys:

| What | Key | Where it lives |
|------|-----|----------------|
| Verify auth-issued JWTs | Auth's Ed25519 public key | `BANKING_AUTH_PUBLIC_KEY_PEM` — same PEM auth's `/public-key` serves |
| Sign each transfer | Banking's Ed25519 private key | `BANKING_TX_SIGNING_PRIVATE_KEY_PEM` — banking-only |
| Encrypt account_number / balance / card_number | AES-256-GCM 32-byte key | `BANKING_FIELD_KEY_HEX` — banking-only |

The auth public key is what makes token verification trustworthy — banking cannot forge tokens because it has no signing key. The transaction key is banking's own — a customer / admin / DB tamperer cannot forge a signed transfer without extracting it from banking's config. The field key is what makes the balance stored on disk unreadable by anyone with raw DB access.

## Two connections per request

Same idea as auth. Each request opens a main transactional connection and a second autocommit connection for the audit log. Audit events survive request-level rollbacks — so a `transfer_rejected` event for insufficient funds still lands even though the main transaction rolled back.

Rationale in full: {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}.

## Field encryption trade-offs

- **Owner ID is plaintext.** It's the FK we filter and index on. Encrypting it would require deterministic encryption or a search index — significant scope creep for a demo. The `owner_id` is a UUID, not a name; leaking it doesn't leak identity.
- **Balance is stored as a UTF-8 string inside the ciphertext.** `encrypt_field(str(100000).encode(), key)`. Arithmetic happens on the plaintext side after decryption. Homomorphic operations on the ciphertext are out of scope.
- **Ciphertext is unindexed.** Range queries or aggregate reports on `balance_minor` would need a plaintext shadow column or a KMS-mediated decryption service. Not built.

## Transaction signing trade-offs

- **Signature covers `id, from, to, amount_minor, at`.** Not the `owner_id` of either account — those are inferred from the account ids at verification time. If the DB is tampered to re-parent an account, that's out of the signature's scope (but breaks the audit chain).
- **Signature is Ed25519, not a chain.** Each transaction stands alone; the ordering evidence is the audit log. Re-ordering the `transactions` table rows without breaking the audit chain requires tampering both tables.
- **Verification is offline.** The `signature_valid` boolean on every list response is a re-check at read time. If the signing key rotates, historical signatures become unverifiable unless the old public key is retained.

## Verified end-to-end

- **49 tests** in the banking suite, including 5 real-Postgres integration tests via `testcontainers-python` in {{ src("banking_service/tests/test_integration_postgres.py") }}.
- **Live smoke test** through Caddy on `https://localhost:8443`:
    - Cross-customer read → 403.
    - Customer listing all accounts → 403.
    - Newly opened account carries a seeded balance of 10 000 minor units ($100); `psql SELECT balance_minor` returned ciphertext bytes.
    - Transfer 2500 minor units, response body includes `signature_valid: true`, source went 10 000 → 7 500, destination 10 000 → 12 500.
    - `UPDATE transactions SET amount_minor = 999999` directly in Postgres → next list response flipped `signature_valid` to `false` without touching the signature bytes.
    - Admin freeze then unfreeze; `account_frozen` and `account_unfrozen` events appear in the audit log; a transfer that was blocked with `AccountFrozen` succeeded after unfreeze.
    - Malformed `account_id` (non-UUID) returned a clean 404 instead of a 500 (see {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository.get") }}).
    - `verify_chain` over the `banking.audit_log` table returned `True` at end of run.

## What this service does *not* do

- **No login.** Auth owns identity. Banking receives whichever token auth minted.
- **No key rotation.** Auth pubkey, TX signing key, and field key are all static across restarts. Rotation is a separate work item.
- **No admin credit / debit endpoint.** Balance seed in the demo is the fixed `NEW_ACCOUNT_STARTING_BALANCE_MINOR = 100_00` applied at account open. A production system would have a deposit path with its own signed audit event.
- **No transaction search or reporting.** Field encryption of the balance column blocks aggregate SQL; adding that is a design decision, not just code.
- **No mTLS to Postgres.** Assessment point 8 is a follow-up ({{ src("flags.md", text="../../flags.md") }} flag 16).
