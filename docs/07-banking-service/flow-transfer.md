# Flow: POST /transfers

Move minor-unit funds from a source account (owned by the caller, or any account if admin) to a destination account identified by its human-shareable account number. Every accepted transfer is signed with banking's Ed25519 key and hash-chained in the audit log.

## Request

```
POST /banking/transfers
Authorization: Bearer <access_jwt>
Content-Type: application/json

{
  "from_account_id":    "b3d9142c-...-0b6534e793a8",
  "to_account_number":  "915203847106",
  "amount_minor":       2500
}
```

Field rules ({{ src("banking_service/src/banking_service/infrastructure/schemas.py") }}):

- `from_account_id` — 1–64 chars. Validated as opaque string at the edge; treated as a UUID by the repo.
- `to_account_number` — regex `^\d{8,32}$`. The 12-digit account numbers this service generates match; the wider band tolerates future format changes.
- `amount_minor` — positive integer, `<= 10_000_000_00` (\$10 million). Upper bound guards against ints so large they'd overflow display or delay Postgres inserts.
- `extra="forbid"` — unknown fields → 422. See [input-validation.md](input-validation.md).

## Response — success

```
201 Created
Content-Type: application/json

{
  "id":              "94f0-...-5a83",
  "from_account_id": "b3d9-...-53a8",
  "to_account_id":   "0e51-...-b1e4",
  "amount_minor":    2500,
  "at":              1783072999,
  "signature_hex":   "b9c7…128 hex chars…",
  "signature_valid": true
}
```

- `signature_hex` — 64-byte Ed25519 signature as 128 hex chars.
- `signature_valid` — always `true` on the create response (freshly signed). The interesting `signature_valid` is the one returned from `GET /transactions/{account_id}`, which re-verifies at read time and can flip to `false` if the row was tampered.
- `to_account_id` — the resolved UUID of the destination account. This is what gets stored and signed; the customer's input was the account number.

## Sequence — success

```
Client              FastAPI          transfer               PostgresAccountRepository       transactions_repo      PostgresAuditLog
   │                  │                 │                          │                              │                     │
   │──POST /banking/transfers (body)──▶│                          │                              │                     │
   │                  │──validate TransferRequest──▶ ok                                                                 │
   │                  │──bearer_caller ─▶ Caller(user_id, role)                                                          │
   │                  │                                                                                                  │
   │            [open main + audit conns, begin main txn]                                                                │
   │                  │──transfer(from_id, to_number, amount, caller, deps)──▶│                                          │
   │                  │                                            │──accounts.get(from_id) ─▶ source (owner=caller)     │
   │                  │                                            │──accounts.get_by_account_number(to_number)          │
   │                  │                                            │   [scan+decrypt+match]                              │
   │                  │                                            │   ─▶ destination                                    │
   │                  │                                            │                                                     │
   │                  │                                            │──require caller.role=='admin' OR source.owner_id==sub│
   │                  │                                            │──assert source.status=='active' AND destination.status=='active'
   │                  │                                            │──assert source.balance_minor >= amount              │
   │                  │                                            │                                                     │
   │                  │                                            │──build Transaction(id, from, to, amount, at=now, signature=b'')│
   │                  │                                            │──sign_transaction(payload(tx), tx_signing_private_key) ─▶ sig │
   │                  │                                            │──accounts.update(source, balance -= amount) ─▶│                │
   │                  │                                            │──accounts.update(destination, balance += amount) ─▶│           │
   │                  │                                            │──transactions.add(signed_tx) ────────────────────────────▶│    │
   │                  │                                            │──emit "transfer"                                             │
   │                  │                                            │       ──record────────────────────────────────────────────▶ │
   │                  │                                            │       [own txn on audit_conn: LOCK + chain + INSERT + COMMIT]│
   │                  │◀───signed Transaction──────────────────────│                                                              │
   │            [commit main txn — accounts + transactions land]                                                                  │
   │◀──201 TransactionResponse(signature_valid=true)                                                                              │
```

## Sequence — insufficient funds

The interesting failure. The main transaction rolls back, but the audit event lands.

```
Client            transfer               PostgresAccountRepository        PostgresAuditLog (autocommit)
   │                 │                          │                                     │
   │──transfer(…)───▶│                          │                                     │
   │                 │──accounts.get(from_id)  ─▶ source (balance=100)                │
   │                 │──accounts.get_by_account_number(...)  ─▶ destination           │
   │                 │──amount=500  >  100                                            │
   │                 │──emit "transfer_rejected" reason=insufficient_funds            │
   │                 │       ──record────────────────────────────────────────────▶   │
   │                 │       [own txn on audit_conn: LOCK + chain + INSERT + COMMIT]  │
   │                 │◀────────────────ok─────────────────────────────────────────    │
   │                 │──raise InsufficientFunds                                        │
   │◀──409                                                                            │
   │
   │  Main txn rolls back on exception exit — but audit event
   │  is already committed on the audit connection.
```

Same design as auth's failed-login audit path. See {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }} for the full rationale.

## Signature payload — what actually gets signed

From {{ src("banking_service/src/banking_service/domain/transactions.py", text="transaction_payload") }}:

```python
{
    "id": tx.id,
    "from": tx.from_account_id,
    "to": tx.to_account_id,
    "amount_minor": tx.amount_minor,
    "at": tx.at,
}
```

Canonicalised via {{ src("shared_security/src/shared_security/canonical.py", text="canonical_json_bytes") }} before signing (`sort_keys=True`, `separators=(",",":")`) so the bytes are identical on the verifying side. Ed25519 signature via `shared_security.transaction_signatures.sign_transaction`.

**What the signature covers:** id, both endpoints, amount, timestamp.
**What it does not cover:** the owner_id of either account. If the DB is tampered to re-parent an account after the transfer landed, the transaction signature stays valid — but the audit chain would have to be broken to hide the re-parenting from an auditor.

Detailed threat model: {{ src("02-shared-security/transaction-signatures.md", text="../02-shared-security/transaction-signatures.md") }}.

## Detecting tampering at read time

`GET /transactions/{account_id}` recomputes the signature for every row via {{ src("banking_service/src/banking_service/application/list_transactions.py", text="list_transactions") }}:

```python
verify_transaction(transaction_payload(tx), tx.signature, deps.settings.tx_signing_public_key)
```

If someone edited `transactions.amount_minor` directly in Postgres, the recomputed payload no longer matches the stored signature and `signature_valid` flips to `false` on the response — without touching the signature bytes. Locked by:

- {{ src("banking_service/tests/test_list_transactions.py", text="test_tampered_stored_amount_reports_signature_invalid") }} — application-layer.
- Live smoke recorded in {{ src("docs/07-banking-service/overview.md", text="overview") }} — real Postgres UPDATE flipped the flag.

## Audit events

```json
{"event":"transfer","at":…,"actor_user_id":"…","tx_id":"…","from_account":"…","to_account":"…","amount_minor":2500}
{"event":"transfer_rejected","at":…,"actor_user_id":"…","from_account":"…","reason":"insufficient_funds"}
```

Both hash-chained. `transfer_rejected` deliberately does not include the destination — the caller supplied an account number, and the point of the event is "this actor tried to move money they didn't have".

Also emitted to stdout for grep:

```
TRANSFER ip=X user_id=Y tx_id=Z
TRANSFER_REJECTED ip=X user_id=Y from=Z reason=insufficient_funds
```

## Failure modes

| Status | Cause | Body |
|--------|-------|------|
| `201` | Success | `TransactionResponse` |
| `400` | `amount_minor <= 0` (post-Pydantic — negative not literally possible after schema, but `InvalidTransfer` covers self-transfer here too) | `{"detail":"amount must be positive"}` or `{"detail":"cannot transfer to the same account"}` |
| `401` | Missing / bad token | as [flow-open-account.md](flow-open-account.md) |
| `403` | Caller is a customer and does not own the source account | `{"detail":"not the source account owner"}` |
| `404` | Source id doesn't exist or destination number doesn't match any account | `{"detail":"account not found"}` |
| `409` | Either side frozen or source underfunded | `{"detail":"account frozen"}` / `{"detail":"insufficient funds"}` |
| `422` | Schema validation failure (missing field, non-digit account number, negative amount, extra keys) | Pydantic error detail |

Two 404 shapes, one status, because both "unknown source id" and "unknown destination number" collapse into `AccountNotFound`. The client cannot use the status to enumerate which side was wrong.

## Rules the use case enforces (in order)

Straight read of {{ src("banking_service/src/banking_service/application/transfer.py") }}:

1. `amount_minor > 0` — else `InvalidTransfer` → 400.
2. Source exists — else `AccountNotFound` → 404.
3. Destination exists — else `AccountNotFound` → 404.
4. Source id ≠ destination id — else `InvalidTransfer` → 400.
5. Caller is admin OR owns the source — else `NotAccountOwner` → 403.
6. Neither source nor destination frozen — else `AccountFrozen` → 409.
7. Source balance ≥ amount — else emit audit + `InsufficientFunds` → 409.
8. Sign, apply, persist, audit.

The order matters. Auth failures (5) run *after* the id lookups so that a customer probing "does account X exist?" cannot use response timing to distinguish "not found" from "found but not yours" — both hit the DB before the check.

## Tests that pin this flow

{{ src("banking_service/tests/test_transfer.py") }} — 9 tests, one per rule and one for the happy path:

- `test_transfer_moves_balance` — debit + credit.
- `test_transfer_produces_verifiable_signature` — signature verifies with the paired public key.
- `test_tampered_transaction_signature_fails_verification` — verify rejects a signature+payload mismatch.
- `test_customer_cannot_transfer_from_someone_elses_account` — rule 5.
- `test_insufficient_funds_rejected_and_audited` — rule 7 including the audit event.
- `test_zero_or_negative_amount_rejected` — rule 1.
- `test_self_transfer_rejected` — rule 4.
- `test_admin_can_transfer_from_any_account` — rule 5 admin bypass.
- `test_transfer_audited` — happy-path audit event shape.

Plus the frozen-side tests in {{ src("banking_service/tests/test_freeze_account.py") }} (rule 6) and integration coverage in {{ src("banking_service/tests/test_integration.py", text="test_transfer_flow") }} and {{ src("banking_service/tests/test_integration_postgres.py", text="test_transfer_persists_signature_and_updates_balances") }}.
