# Flow: POST /accounts

Open a new account for the caller. Any authenticated caller (customer or admin) can call this — the resulting account is owned by whoever the token identifies.

## Request

```
POST /banking/accounts
Authorization: Bearer <access_jwt>
```

No body. The caller identity is the only input, taken from the token.

## Response — success

```
201 Created
Content-Type: application/json

{
  "id":             "b3d9142c-...-0b6534e793a8",
  "owner_id":       "0e51a7f0-...-31d1a2c0b1e4",
  "account_number": "418739255012",
  "balance_minor":  10000,
  "card_number":    "3927451068220453",
  "status":         "active"
}
```

- `id` — UUID, banking's internal PK. Used by URL-scoped routes (`GET /accounts/{id}`, `POST /accounts/{id}/freeze`).
- `owner_id` — the `sub` claim from the caller's access token.
- `account_number` — 12 random digits. What customers share with each other for transfers.
- `balance_minor` — starting balance in cents. Seeded to `100_00` = $100.00 so a fresh customer can immediately test a transfer end-to-end. Constant `NEW_ACCOUNT_STARTING_BALANCE_MINOR` in {{ src("banking_service/src/banking_service/application/open_account.py") }}.
- `card_number` — 16 random digits.
- `status` — always `"active"` for a new account.

## Sequence — success

```
Client               FastAPI       token_verifier              open_account            PostgresAccountRepository    PostgresAuditLog
   │                   │                │                          │                             │                        │
   │──POST /banking/accounts (Bearer …)─▶                          │                             │                        │
   │                   │                │                          │                             │                        │
   │             [strip /banking/, forward to https://banking:8000/accounts]                                               │
   │                   │                │                          │                             │                        │
   │                   │──bearer_caller(auth_public_key)──▶│                                                              │
   │                   │                │  verify_token → claims  │                                                       │
   │                   │                │  Caller(user_id=sub, role=role)                                                 │
   │                   │◀───────────────│                          │                                                       │
   │                                                                                                                       │
   │             [open main_conn + audit_conn, begin main txn]                                                             │
   │                   │──open_account(caller=..., deps=...)──────▶│                                                       │
   │                   │                                            │──uuid4() → account.id                                │
   │                   │                                            │──generate_account_number() → 12 digits                │
   │                   │                                            │──generate_card_number()    → 16 digits                │
   │                   │                                            │──build Account(status="active", balance=100_00)       │
   │                   │                                            │──accounts.add(account) ─────▶│                       │
   │                   │                                            │                              │──encrypt_field(3 cols)│
   │                   │                                            │                              │──INSERT INTO accounts │
   │                   │                                            │◀──────────────────────────────                        │
   │                   │                                            │──emit "account_opened"                                │
   │                   │                                            │       ──record─────────────────────────────────────▶ │
   │                   │                                            │       [own txn: LOCK + chain + INSERT + COMMIT]       │
   │                   │                                            │       ◀───────────ok───────────────────────────────  │
   │                   │◀───Account─────────────────────────────────│                                                       │
   │             [commit main txn]                                                                                          │
   │◀──201 AccountResponse                                                                                                  │
```

## Code path

Route: {{ src("banking_service/src/banking_service/infrastructure/app.py", text="open_route in app.py") }}:

```python
@app.post("/accounts", response_model=AccountResponse, status_code=201)
def open_route(request, caller: Caller = Depends(caller_dep), deps: BankingDeps = Depends(deps_factory)):
    account = open_account(caller=caller, deps=deps)
    logger.info("ACCOUNT_OPENED ip=%s user_id=%s account_id=%s", ...)
    return _account_response(account)
```

Use case: {{ src("banking_service/src/banking_service/application/open_account.py", text="open_account in application/open_account.py") }}. Zero role check — every authenticated caller can open an account for their own user id.

## What ends up on disk

Row layout in `accounts` (see also [../04-deployment/database-schema.md](../04-deployment/database-schema.md)):

| Column | Type | Content |
|--------|------|---------|
| `id` | UUID | plaintext |
| `owner_id` | UUID | plaintext (indexed for `get_by_owner`) |
| `account_number` | BYTEA | AES-256-GCM ciphertext of `"418739255012".encode()` |
| `balance_minor` | BYTEA | AES-256-GCM ciphertext of `"10000".encode()` — string form, not integer |
| `card_number` | BYTEA | AES-256-GCM ciphertext of `"3927451068220453".encode()` |
| `status` | TEXT | `"active"` |
| `created_at` | TIMESTAMPTZ | `NOW()` at insert |

The balance is stringified before encryption because AEAD works on byte strings and integer→bytes conversion has no canonical form we want to pin. Arithmetic happens on the plaintext side after decryption. Details: {{ src("07-banking-service/infrastructure-layer.md", text="infrastructure-layer.md") }}.

Verify from the DB:

```
$ psql -c 'SELECT id, owner_id, encode(balance_minor, \x27hex\x27) FROM accounts LIMIT 1'
 id  | owner_id | encode
-----+----------+--------
 ... | ...      | 6f2d4a…  ← 12-byte nonce + ciphertext + 16-byte GCM tag
```

Not a number, not a string. Ciphertext.

## Audit event

```json
{"event":"account_opened","at":1783072578,"account_id":"...","owner_id":"..."}
```

Hash-chained in the `banking.audit_log` table. Verifiable end-to-end via `shared_security.audit_chain.verify_chain` — locked by {{ src("banking_service/tests/test_integration_postgres.py", text="test_audit_chain_valid_end_to_end") }}.

## Failure modes

| Status | Cause | Body |
|--------|-------|------|
| `201` | Success | `AccountResponse` |
| `401` | Missing / malformed / expired / tampered bearer token | `{"detail":"missing bearer token"}` / `{"detail":"invalid token"}` / `{"detail":"malformed token claims"}` |
| `500` | Postgres unavailable, field key invalid | Generic |

No 4xx for missing body — there is no body to validate.

## Tests that pin this flow

- {{ src("banking_service/tests/test_open_account.py") }}:
    - `test_open_account_assigns_owner_and_starting_balance` — id, owner, status, and $100 starting balance all set.
    - `test_open_account_audited` — one `account_opened` event, correct account_id, correct owner.
    - `test_two_customers_get_distinct_account_numbers` — the RNG isn't collision-prone at demo scale (statistical, not proof — the number is 12 random digits from `secrets`).
- {{ src("banking_service/tests/test_integration.py", text="test_open_and_read_own_account_over_http") }} — HTTP round-trip through FastAPI.
- {{ src("banking_service/tests/test_integration_postgres.py", text="test_sensitive_fields_are_ciphertext_on_disk") }} — proves the three columns are non-plaintext against a real Postgres.
