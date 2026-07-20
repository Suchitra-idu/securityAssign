# Input validation

Every request body is validated by Pydantic **before** the use case runs. Malformed input → 422 with a field-scoped error detail; nothing else executes. Same principle as auth's input validation ([../03-auth-service/input-validation.md](../03-auth-service/input-validation.md)), scoped to the banking API.

Location: {{ src("banking_service/src/banking_service/infrastructure/schemas.py") }}.

## Global setting: `extra="forbid"`

`TransferRequest` uses:

```python
model_config = ConfigDict(extra="forbid")
```

Unknown fields cause 422 rather than being silently ignored. Concretely, a client sending `{"from_account_id": "...", "to_account_number": "...", "amount_minor": 100, "signature_valid": true}` to `/transfers` gets 422 — the client cannot smuggle a `signature_valid=true` claim past the server-side signing step.

Same defence against any imagined extras: `owner_id`, `role`, `caller_id`, etc.

## Model-by-model rules

### `TransferRequest`

```python
class TransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_account_id:   str = Field(min_length=1, max_length=64)
    to_account_number: str = Field(pattern=r"^\d{8,32}$")
    amount_minor:      int = Field(gt=0, le=10_000_000_00)
```

- **`from_account_id` — 1–64 chars.** The application layer treats it as opaque and the repo lets Postgres cast it to UUID. If the cast fails (malformed UUID), the repo returns `None` → the use case raises `AccountNotFound` → 404. The 64-char cap is a sanity bound; a real UUID is 36 chars.
- **`to_account_number` — `^\d{8,32}$`.** Exactly ASCII digits, 8 to 32 characters. Locks out URL fragments, SQL, whitespace, unicode confusables. Banking generates 12-digit numbers ({{ src("banking_service/src/banking_service/application/numbers.py") }}); the wider band leaves room for future formats without a schema change.
- **`amount_minor` — positive integer, ≤ `10_000_000_00`.** Positive rules out debits-disguised-as-credits at the boundary — the use case *also* re-checks (`InvalidTransfer`) as defence in depth, so a schema drift can't silently allow zero. The $10M cap prevents accidental / adversarial huge numbers.

### `AccountResponse`, `TransactionResponse`, `HealthResponse`

Response models. Field types declared so FastAPI generates accurate OpenAPI. `TransactionResponse.signature_hex` carries the signature as 128 hex chars — hex rather than base64 to match the format `psql` produces (`encode(signature, 'hex')`) so operators can eyeball-compare.

## Query and path parameters

The routes use path parameters (`{account_id}`) that FastAPI hands over as `str`. There is no Pydantic model per path parameter; the repo defends against malformed values (see the `InvalidTextRepresentation` catch in {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py") }}).

Rationale: adding path-parameter validation would move the rejection from 404 ("account not found") to 422 ("bad path"), which is a slight information leak — the client would learn that the *format* was wrong, which distinguishes "unknown but well-formed" from "malformed". Uniform 404 is better.

## The routes with no body

`POST /accounts`, `POST /accounts/{id}/freeze`, `POST /accounts/{id}/unfreeze`, `GET /accounts/me`, `GET /accounts`, `GET /accounts/{id}`, `GET /transactions/{id}`, `GET /health` all take no request body. No Pydantic model needed. FastAPI still enforces:

- `application/json` is not required (no body).
- If a client sends a body anyway, FastAPI ignores it for these routes.

## Where the token is validated

Not by Pydantic. The `Authorization: Bearer …` header is validated by the FastAPI dependency `bearer_caller` in {{ src("banking_service/src/banking_service/infrastructure/token_verifier.py") }}:

- Header missing / not `Bearer ` prefix → 401 `"missing bearer token"`.
- Signature invalid / expired / structurally broken → 401 `"invalid token"`.
- Signature valid but `role` isn't `customer|admin` or `sub` isn't a string → 401 `"malformed token claims"`.

That last check is the guardrail against contract drift with auth — see {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md") }} for the locked token payload.

## What happens on 422

FastAPI catches Pydantic `ValidationError` and returns:

```json
{
  "detail": [
    {
      "type": "string_pattern_mismatch",
      "loc": ["body", "to_account_number"],
      "msg": "String should match pattern '^\\d{8,32}$'",
      "input": "abc",
      "ctx": {"pattern": "^\\d{8,32}$"}
    }
  ]
}
```

Structured, field-scoped, and never contains anything the caller didn't send.

## What input validation does *not* do

- **No balance-based transfer rejection at the schema layer.** "Amount exceeds source balance" is business logic — it belongs in the use case and returns 409, not 422.
- **No ownership check.** "Caller isn't the source owner" is RBAC, enforced by `require_owner_or_admin` at use-case entry.
- **No account-number check-digit.** The 12-digit accounts are random; no Luhn or ISO scheme. If a real payment scheme is added, its check-digit rule goes in a `field_validator`.
- **No content-based amount validation.** No "amounts must be multiples of 5", no "no odd hundredths" — currency-agnostic.
- **No CSRF, replay, or origin checks.** Those are the proxy / WAF's job.
- **JSON body size limits.** FastAPI's underlying starlette default applies. A production Caddy directive would cap this earlier.

## Why input validation belongs in infrastructure, not domain

Same reasoning as auth. The domain sees already-validated primitives; the edge decides what a valid request looks like. If a second delivery mechanism ever appears (CLI, gRPC), it applies its own edge validation before calling the same use cases.

## Tests that pin this

Route-level negative tests are in {{ src("banking_service/tests/test_integration.py") }}. Application-layer positive tests hit the use case directly with already-valid inputs. The schema is intentionally small enough to reason about by inspection.
