# Application layer

Use cases + ports + role checks. Every business rule lives here. No FastAPI, no psycopg — the use cases can run in a test without any of that.

Location: {{ src("banking_service/src/banking_service/application/", text="banking_service/src/banking_service/application/") }}.

## Ports — the swappable seams

{{ src("banking_service/src/banking_service/application/ports.py") }} declares four `typing.Protocol` interfaces:

```python
class AccountRepository(Protocol):
    def get(self, account_id: str) -> Account | None: ...
    def get_by_account_number(self, account_number: str) -> Account | None: ...
    def get_by_owner(self, owner_id: str) -> list[Account]: ...
    def list_all(self) -> list[Account]: ...
    def add(self, account: Account) -> None: ...
    def update(self, account: Account) -> None: ...

class TransactionRepository(Protocol):
    def add(self, tx: Transaction) -> None: ...
    def list_for_account(self, account_id: str) -> list[Transaction]: ...
    def list_all(self) -> list[Transaction]: ...

class AuditLog(Protocol):
    def record(self, event: dict) -> None: ...

class Clock(Protocol):
    def now(self) -> int: ...
```

Two implementations of each:

| Port | Test impl | Production impl |
|------|-----------|-----------------|
| `AccountRepository` | `FakeAccountRepo` in {{ src("banking_service/tests/conftest.py") }} | {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository") }} |
| `TransactionRepository` | `FakeTxRepo` in conftest.py | {{ src("banking_service/src/banking_service/infrastructure/repositories/transactions_repo.py", text="PostgresTransactionRepository") }} |
| `AuditLog` | `FakeAudit` in conftest.py | {{ src("banking_service/src/banking_service/infrastructure/audit_log.py", text="PostgresAuditLog") }} |
| `Clock` | `FakeClock` in conftest.py | {{ src("banking_service/src/banking_service/infrastructure/clock.py", text="SystemClock") }} |

`AccountRepository.get_by_account_number` is a scan-and-decrypt at the Postgres implementation because `account_number` is AES-256-GCM encrypted with a random per-row nonce — see the {{ src("07-banking-service/infrastructure-layer.md", text="infrastructure layer") }} for the trade-off.

## Deps container

{{ src("banking_service/src/banking_service/application/deps.py") }}:

```python
@dataclass(frozen=True)
class BankingDeps:
    accounts: AccountRepository
    transactions: TransactionRepository
    audit: AuditLog
    clock: Clock
    settings: BankingSettings
```

Every use case takes `deps: BankingDeps`. Same shape as `AuthDeps` (see {{ src("03-auth-service/application-layer.md", text="../03-auth-service/application-layer.md") }}). Slight downside — a use case that only needs `accounts` still receives everything else — but the ergonomic win at every call site outweighs it.

## Caller — who is asking

{{ src("banking_service/src/banking_service/application/caller.py") }}:

```python
CallerRole = Literal["customer", "admin"]

@dataclass(frozen=True)
class Caller:
    user_id: str
    role: CallerRole
```

Built by the token verifier from the `sub` + `role` claims. This is the *only* input a use case receives that describes "who". It never receives the raw token, and it never receives the auth service's username — banking has no concept of usernames, only user ids from auth.

## Banking settings

{{ src("banking_service/src/banking_service/application/settings.py") }}:

```python
@dataclass(frozen=True)
class BankingSettings:
    auth_public_key: str          # PEM — for token verification
    tx_signing_private_key: str   # PEM — for signing transfers
    tx_signing_public_key: str    # PEM — for verifying transfers at read time
```

Application-layer type. The infrastructure `Config` in {{ src("banking_service/src/banking_service/infrastructure/config.py") }} builds this from env vars.

## Role-check helpers — the single RBAC choke point

{{ src("banking_service/src/banking_service/application/authz.py") }}:

```python
def require_admin(caller: Caller) -> None:
    if caller.role != "admin":
        raise Forbidden

def require_owner_or_admin(caller: Caller, account: Account) -> None:
    if caller.role == "admin":
        return
    if account.owner_id != caller.user_id:
        raise NotAccountOwner
```

Every use case that reads or mutates account state calls one of these before doing anything else. This is the whole enforcement of assessment point 6 (RBAC customer vs admin). The tests that pin it:

- {{ src("banking_service/tests/test_read_account.py", text="test_customer_cannot_read_other_customer_account") }}
- {{ src("banking_service/tests/test_list_accounts.py", text="test_customer_cannot_list_all_accounts") }}
- {{ src("banking_service/tests/test_freeze_account.py", text="test_customer_cannot_freeze_account") }}
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_customer_cannot_unfreeze_account") }}
- {{ src("banking_service/tests/test_transfer.py", text="test_customer_cannot_transfer_from_someone_elses_account") }}

Route-level checks alone would not be enough: an admin operation that forgets to call `require_admin` would compile and pass every non-RBAC test. The rule is "if a use case touches account state, it opens with a role check" — every module in this layer follows it.

## Audit emit helper

{{ src("banking_service/src/banking_service/application/audit.py") }}:

```python
def emit(deps: BankingDeps, event: str, **fields) -> None:
    deps.audit.record({"event": event, "at": deps.clock.now(), **fields})
```

Same pattern as auth. Every event carries `event` and `at`; extra fields go through kwargs. Six call sites in this layer, one source of truth for the event shape.

## Number generators

{{ src("banking_service/src/banking_service/application/numbers.py") }}:

```python
def generate_account_number() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(12))

def generate_card_number() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(16))
```

Random digits from `secrets`, not `random`. The output is displayed to the user and stored ciphertext. No Luhn check-digit — the card number is for demo display only, no real card scheme has to validate it.

## Use cases

### `open_account`

{{ src("banking_service/src/banking_service/application/open_account.py") }}:

```python
NEW_ACCOUNT_STARTING_BALANCE_MINOR = 100_00

def open_account(*, caller: Caller, deps: BankingDeps) -> Account:
    account = Account(
        id=str(uuid4()),
        owner_id=caller.user_id,
        account_number=generate_account_number(),
        balance_minor=NEW_ACCOUNT_STARTING_BALANCE_MINOR,
        card_number=generate_card_number(),
        status="active",
    )
    deps.accounts.add(account)
    emit(deps, "account_opened", account_id=account.id, owner_id=account.owner_id)
    return account
```

- No role check — any authenticated caller can open an account for themselves. Admin opens one for the admin user_id, same as any customer.
- Balance seeded with $100.00 so the demo transfer flow works end-to-end without a separate credit endpoint. Documented in the constant's comment.

Full flow: [flow-open-account.md](flow-open-account.md).

### `transfer`

{{ src("banking_service/src/banking_service/application/transfer.py") }}. The most rule-dense use case in the service.

Rules, in order:

1. **Amount positive** (`InvalidTransfer` → 400).
2. **Source loads by id.** `AccountNotFound` if the caller supplies a bad UUID → 404.
3. **Destination loads by account number.** Scan-and-decrypt through `get_by_account_number`. `AccountNotFound` if unknown → 404.
4. **Not a self-transfer** (`InvalidTransfer` → 400).
5. **Caller owns the source, unless admin** (`NotAccountOwner` → 403).
6. **Neither side frozen** (`AccountFrozen` → 409).
7. **Source has funds.** On failure, emit `transfer_rejected` audit event *before* raising, so the audit chain records refused attempts (`InsufficientFunds` → 409).
8. Build unsigned `Transaction`, sign with `sign_transaction(transaction_payload(...), settings.tx_signing_private_key)`.
9. Debit source, credit destination, persist the signed transaction, emit `transfer` audit event.

Two things are worth understanding:

- **Destination is looked up by account number, not id.** Customers see and share account numbers; UUIDs never leave the server for customer flows. See the {{ src("07-banking-service/overview.md", text="overview") }} for the "why".
- **Rejected transfers get an audit event.** Same reason auth audits failed logins on a separate connection — the whole request rolls back on `InsufficientFunds`, but the audit event persists via the autocommit audit connection. See {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}.

Full flow: [flow-transfer.md](flow-transfer.md).

### `read_account` / `list_own_accounts` / `list_all_accounts`

Three read paths, three role rules:

```python
def read_account(*, account_id, caller, deps) -> Account:
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    require_owner_or_admin(caller, account)
    emit(deps, "account_read", account_id=..., actor_user_id=..., actor_role=...)
    return account

def list_own_accounts(*, caller, deps) -> list[Account]:
    return deps.accounts.get_by_owner(caller.user_id)

def list_all_accounts(*, caller, deps) -> list[Account]:
    require_admin(caller)
    return deps.accounts.list_all()
```

- Single-account read is owner-or-admin, and audited (so admin snooping into a customer account leaves a trace).
- Own-account list is unconditional — the query is bounded to `caller.user_id`, there's nothing for a customer to overreach at.
- All-accounts list is admin-only, hard-gated.

### `freeze_account` / `unfreeze_account`

Symmetrical mirror. Both admin-only, both idempotent.

```python
def freeze_account(*, account_id, caller, deps) -> Account:
    require_admin(caller)
    account = deps.accounts.get(account_id)
    if account is None:
        raise AccountNotFound
    if account.status == "frozen":
        return account                 # idempotent no-op
    frozen = replace(account, status="frozen")
    deps.accounts.update(frozen)
    emit(deps, "account_frozen", account_id=..., actor_user_id=...)
    return frozen
```

`unfreeze_account` in {{ src("banking_service/src/banking_service/application/unfreeze_account.py") }} is the exact mirror with `"active"` swapped in. Idempotency short-circuits *before* emitting the audit event — repeated calls do not spam the audit log. Locked by:

- {{ src("banking_service/tests/test_freeze_account.py", text="test_freeze_is_idempotent") }}
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_unfreeze_is_idempotent_on_active_account") }}
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_unfreeze_emits_single_audit_event") }}

Full flow: [flow-freeze-unfreeze.md](flow-freeze-unfreeze.md).

### `list_transactions`

{{ src("banking_service/src/banking_service/application/list_transactions.py") }}. Returns a list of `(Transaction, signature_valid: bool)` tuples. The boolean is computed at read time:

```python
verify_transaction(transaction_payload(tx), tx.signature, deps.settings.tx_signing_public_key)
```

If the row's `amount_minor` was tampered directly in the DB (bypassing the application), `signature_valid` flips to `False` on the very next read. Locked by {{ src("banking_service/tests/test_list_transactions.py", text="test_tampered_stored_amount_reports_signature_invalid") }}.

Owner-or-admin role check, same as `read_account`. Not audited on each read of a transaction list (would be noisy and low-signal — a customer scrolling their own history isn't audit-worthy).

## What is not in the application layer

- **No transactions.** Use cases do not know they run inside a psycopg transaction. That is an infrastructure concern — the FastAPI dependency generator wraps each request in one. Same pattern as auth. See {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}.
- **No HTTP status codes.** Domain errors propagate up; the route translates them.
- **No key material generation.** All three keys arrive already-materialised in `BankingSettings`.
- **No token verification.** Handled at the FastAPI-dependency layer by {{ src("banking_service/src/banking_service/infrastructure/token_verifier.py", text="bearer_caller") }} — the application layer receives a valid `Caller` or the request has already 401'd.

## Tests over the application layer

- {{ src("banking_service/tests/test_open_account.py") }} — 3 tests.
- {{ src("banking_service/tests/test_read_account.py") }} — 6 tests.
- {{ src("banking_service/tests/test_list_accounts.py") }} — 2 tests.
- {{ src("banking_service/tests/test_transfer.py") }} — 9 tests.
- {{ src("banking_service/tests/test_freeze_account.py") }} — 6 tests.
- {{ src("banking_service/tests/test_unfreeze_account.py") }} — 6 tests.
- {{ src("banking_service/tests/test_list_transactions.py") }} — 3 tests.

All use the fake ports in {{ src("banking_service/tests/conftest.py") }}. No FastAPI, no Postgres, sub-second.
