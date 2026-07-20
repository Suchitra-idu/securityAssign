# Domain layer

Pure data + errors. If you deleted every non-stdlib import tomorrow, this layer would not change.

Location: {{ src("banking_service/src/banking_service/domain/", text="banking_service/src/banking_service/domain/") }}.

## Files

### `accounts.py`

```python
AccountStatus = Literal["active", "frozen"]

@dataclass(frozen=True)
class Account:
    id: str
    owner_id: str
    account_number: str
    balance_minor: int
    card_number: str
    status: AccountStatus
```

- **`id`** — UUIDv4 assigned by {{ src("banking_service/src/banking_service/application/open_account.py", text="open_account()") }}. The internal primary key. Never leaves the banking service in a form that a customer types in — customer-visible flows use `account_number` instead.
- **`owner_id`** — the `sub` claim from the caller's access token, resolved by {{ src("banking_service/src/banking_service/infrastructure/token_verifier.py", text="bearer_caller") }}. Stored plaintext (see the trade-off note in {{ src("07-banking-service/overview.md", text="overview") }}).
- **`account_number`** — 12 random digits ({{ src("banking_service/src/banking_service/application/numbers.py", text="generate_account_number") }}). The customer-visible identifier. Encrypted at rest.
- **`balance_minor`** — integer in minor units (cents). Domain code never sees the ciphertext form — encryption is a storage-layer concern.
- **`card_number`** — 16 random digits. Encrypted at rest.
- **`status`** — the literal `"active"` or `"frozen"`. Constrained by the DB `CHECK (status IN ('active', 'frozen'))`.

`frozen=True` means every state change (freeze, unfreeze, debit, credit) produces a **new** `Account` via `dataclasses.replace(...)`. No mutation, no partial-update bugs.

### `transactions.py`

```python
@dataclass(frozen=True)
class Transaction:
    id: str
    from_account_id: str
    to_account_id: str
    amount_minor: int
    at: int
    signature: bytes

def transaction_payload(tx: Transaction) -> dict:
    return {
        "id": tx.id,
        "from": tx.from_account_id,
        "to": tx.to_account_id,
        "amount_minor": tx.amount_minor,
        "at": tx.at,
    }
```

Two things live here together for a reason:

1. **`Transaction`** — the immutable record of a transfer. `signature` is Ed25519 raw bytes.
2. **`transaction_payload`** — the single function that decides *what gets signed*. Called by {{ src("banking_service/src/banking_service/application/transfer.py", text="transfer") }} to build the signing input, and again by {{ src("banking_service/src/banking_service/application/list_transactions.py", text="list_transactions") }} to reconstruct the verification input. Because both sides call the same function, the two representations cannot drift.

Note the payload uses `"from"` / `"to"` as JSON keys but `from_account_id` / `to_account_id` on the dataclass — the payload is deliberately shorter because it's what gets canonicalised and signed, and shorter keys make the signature over slightly less bytes. The dataclass keeps the more readable Python name.

### `errors.py`

```python
class AccountNotFound(Exception): pass
class NotAccountOwner(Exception): pass
class Forbidden(Exception): pass
class InsufficientFunds(Exception): pass
class AccountFrozen(Exception): pass
class InvalidTransfer(Exception): pass
class TamperedRecord(Exception): pass
```

Seven failure modes, mapped to HTTP by {{ src("banking_service/src/banking_service/infrastructure/app.py") }}:

| Exception | HTTP status | Raised from |
|-----------|-------------|-------------|
| `AccountNotFound` | 404 | any use case that dereferences an id |
| `NotAccountOwner` | 403 | `require_owner_or_admin` when the caller is a customer but not the owner |
| `Forbidden` | 403 | `require_admin` when the caller is a customer |
| `InsufficientFunds` | 409 | `transfer` when source balance is short |
| `AccountFrozen` | 409 | `transfer` when either side is frozen |
| `InvalidTransfer` | 400 | `transfer` for non-positive amount or self-transfer |
| `TamperedRecord` | (unused at HTTP) | reserved for audit-chain verification callers |

Two things worth spelling out:

- **`NotAccountOwner` vs `Forbidden`** — both become 403 but distinguishing them at the domain level lets the message be honest. `NotAccountOwner` means "you asked about a resource that isn't yours"; `Forbidden` means "your role can't do this operation at all". The distinction shows up in the response body strings.
- **No `SelfTransfer` type.** Self-transfer is folded into `InvalidTransfer("cannot transfer to the same account")` because it shares the failure mode: the amount fails to move any money that matters. One error type, one HTTP status, no branch in the route.

## What the domain layer does not have

- No `Money` type — integer minor units is the whole abstraction. Arithmetic is plain Python.
- No `AccountNumber` / `CardNumber` types — validated at the HTTP edge, otherwise just `str`.
- No `Signature` type — `bytes` is enough; validity is a separate boolean computed at read time.
- No `AccountService` / `TransferService` classes — the use cases in the application layer *are* the operations, functions not methods.

Keeping the domain deliberately thin matches auth's shape (see {{ src("03-auth-service/domain-layer.md", text="../03-auth-service/domain-layer.md") }}).

## Import discipline

Verify with:

```
$ grep -R "^import\|^from" banking_service/src/banking_service/domain/
```

You should see only `dataclasses` and `typing`. Any other import here is a layering violation.

## Tests that pin behaviour of the domain layer

There are no dedicated domain tests. Every application-layer test constructs `Account` and `Transaction` values directly and asserts against them ({{ src("banking_service/tests/test_open_account.py") }}, {{ src("banking_service/tests/test_transfer.py") }}, etc.), which is enough for a layer this thin.
