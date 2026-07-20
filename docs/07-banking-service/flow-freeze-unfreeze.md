# Flow: POST /accounts/{id}/freeze and /unfreeze

Symmetrical admin-only status flip. Freezing an account blocks it from being either side of a transfer; unfreezing restores it.

Two routes, one design pattern. The docs are combined because everything meaningful is shared.

## Requests

```
POST /banking/accounts/{account_id}/freeze
Authorization: Bearer <admin_access_jwt>
```

```
POST /banking/accounts/{account_id}/unfreeze
Authorization: Bearer <admin_access_jwt>
```

No body. `{account_id}` is the UUID `Account.id` — the same value returned from `POST /accounts`.

## Response — success

Both return `200 AccountResponse`:

```
200 OK
Content-Type: application/json

{
  "id":             "b3d9142c-...-0b6534e793a8",
  "owner_id":       "0e51a7f0-...-31d1a2c0b1e4",
  "account_number": "418739255012",
  "balance_minor":  10000,
  "card_number":    "3927451068220453",
  "status":         "frozen"    // or "active" for unfreeze
}
```

The rest of the account is unchanged — only `status` flips.

## Sequence — freeze happy path

```
Client              FastAPI      token_verifier     freeze_account            PostgresAccountRepository      PostgresAuditLog
   │                  │              │                    │                              │                        │
   │──POST /banking/accounts/{id}/freeze (admin Bearer)─▶│                              │                        │
   │                  │──bearer_caller ─▶ Caller(user_id, role="admin")                                            │
   │                                                                                                              │
   │            [open main + audit conns, begin main txn]                                                          │
   │                  │──freeze_account(id, caller, deps)──▶│                                                      │
   │                  │                                    │──require_admin(caller) ─▶ ok                          │
   │                  │                                    │──accounts.get(id) ────────────────▶│                 │
   │                  │                                    │◀──Account(status="active")─────────│                 │
   │                  │                                    │                                                       │
   │                  │                                    │──replace(status="frozen")                             │
   │                  │                                    │──accounts.update(frozen) ─────────▶│                 │
   │                  │                                    │      [re-encrypt fields, UPDATE row]                  │
   │                  │                                    │◀──────────────────────────────────                    │
   │                  │                                    │──emit "account_frozen"                                │
   │                  │                                    │       ──record──────────────────────────────────────▶│
   │                  │                                    │       [autocommit conn own txn: LOCK + chain + INSERT]│
   │                  │◀──Account(status="frozen")─────────│                                                       │
   │            [commit main txn]                                                                                  │
   │◀──200 AccountResponse                                                                                         │
```

Unfreeze is the exact mirror with `"active"` swapped in and `emit "account_unfrozen"`.

## Idempotency

Both use cases short-circuit if the account is already in the target state, **before** emitting an audit event:

```python
def freeze_account(*, account_id, caller, deps):
    require_admin(caller)
    account = deps.accounts.get(account_id)
    if account is None: raise AccountNotFound
    if account.status == "frozen":
        return account                 # no update, no audit event
    ...
```

Consequence: calling freeze twice results in one `account_frozen` event, not two. Same for unfreeze. This is deliberate — the audit log records **state changes**, not requests. An operator scripting a bulk freeze can re-run it safely.

Locked by:

- {{ src("banking_service/tests/test_freeze_account.py", text="test_freeze_is_idempotent") }}
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_unfreeze_is_idempotent_on_active_account") }} — even on a never-frozen account, calling unfreeze twice emits zero events.
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_unfreeze_emits_single_audit_event") }} — freeze then unfreeze produces exactly one `account_unfrozen` event.

## Effect on transfers

Frozen accounts reject transfers on **both sides**:

```python
if source.status == "frozen" or destination.status == "frozen":
    raise AccountFrozen              # → HTTP 409
```

A frozen source can't send. A frozen destination can't receive. Unfreezing restores both directions. Locked by:

- {{ src("banking_service/tests/test_freeze_account.py", text="test_frozen_source_blocks_transfer") }}
- {{ src("banking_service/tests/test_freeze_account.py", text="test_frozen_destination_blocks_transfer") }}
- {{ src("banking_service/tests/test_unfreeze_account.py", text="test_unfrozen_account_can_transfer_again") }}

Note that the frozen check runs *after* the role and existence checks — a customer trying to transfer from someone else's frozen account gets a 403 (not their account), not a 409 (frozen). That order is deliberate: we don't leak "yes this account exists and it's frozen" to unrelated callers.

## Code path

Routes: {{ src("banking_service/src/banking_service/infrastructure/app.py", text="freeze_route / unfreeze_route in app.py") }}:

```python
@app.post("/accounts/{account_id}/freeze", response_model=AccountResponse)
def freeze_route(account_id, request, caller=Depends(caller_dep), deps=Depends(deps_factory)):
    try:
        account = freeze_account(account_id=account_id, caller=caller, deps=deps)
    except Forbidden:
        raise HTTPException(403, "admin only")
    except AccountNotFound:
        raise HTTPException(404, "account not found")
    logger.info("ACCOUNT_FROZEN ip=%s actor=%s account_id=%s", ...)
    return _account_response(account)
```

Unfreeze route is the same shape with `unfreeze_account` and `ACCOUNT_UNFROZEN`.

Use cases: {{ src("banking_service/src/banking_service/application/freeze_account.py") }} and {{ src("banking_service/src/banking_service/application/unfreeze_account.py") }}.

## Malformed account id → 404, not 500

A client sending a non-UUID `account_id` (e.g. `"not-a-uuid"`) would otherwise cause psycopg to raise `InvalidTextRepresentation` on the `WHERE id = %s` cast, which would bubble up as a 500. {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py", text="PostgresAccountRepository.get") }} catches that error family and returns `None`, so the route returns a clean 404. Same behaviour for `read_account` and every other id-scoped route.

## Audit events

```json
{"event":"account_frozen","at":…,"account_id":"…","actor_user_id":"<admin_id>"}
{"event":"account_unfrozen","at":…,"account_id":"…","actor_user_id":"<admin_id>"}
```

Hash-chained. `actor_user_id` is the *admin* who ran the operation, not the account owner. That is the value an auditor wants: "who froze this and when".

Stdout for grep:

```
ACCOUNT_FROZEN ip=X actor=<admin_id> account_id=<uuid>
ACCOUNT_UNFROZEN ip=X actor=<admin_id> account_id=<uuid>
```

## Failure modes

| Status | Cause | Body |
|--------|-------|------|
| `200` | Success (including no-op idempotent case) | `AccountResponse` |
| `401` | Missing / bad bearer | as [flow-open-account.md](flow-open-account.md) |
| `403` | Caller is a customer, not admin | `{"detail":"admin only"}` |
| `404` | Unknown id, malformed id, or account row missing | `{"detail":"account not found"}` |

## Tests that pin this flow

Freeze — {{ src("banking_service/tests/test_freeze_account.py") }}:

- `test_admin_can_freeze_account`
- `test_customer_cannot_freeze_account`
- `test_freeze_missing_account_raises`
- `test_freeze_is_idempotent`
- `test_frozen_source_blocks_transfer`
- `test_frozen_destination_blocks_transfer`

Unfreeze — {{ src("banking_service/tests/test_unfreeze_account.py") }}:

- `test_admin_can_unfreeze_frozen_account`
- `test_customer_cannot_unfreeze_account`
- `test_unfreeze_missing_account_raises`
- `test_unfreeze_is_idempotent_on_active_account`
- `test_unfreeze_emits_single_audit_event`
- `test_unfrozen_account_can_transfer_again`

Plus UI-level coverage in {{ src("ui-tests/tests/admin.spec.js") }}: freeze from admin view flips the status pill, unfreeze restores it, and a previously-frozen customer can transfer again after unfreeze.
