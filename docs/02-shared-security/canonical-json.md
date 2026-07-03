# Canonical JSON

Deterministic JSON serialisation. One helper, three lines. Called from transaction signatures and the audit hash chain — anywhere the same dict must produce identical bytes.

## API

```python
def canonical_json_bytes(payload: dict) -> bytes
```

Implementation: [canonical.py](../../shared_security/src/shared_security/canonical.py).

## The rules

```python
json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
```

- **`sort_keys=True`** — keys serialised in lexicographic order. Object equality by content, regardless of insertion order.
- **`separators=(",", ":")`** — no whitespace between elements or between keys and values. `{"a":1,"b":2}`, not `{"a": 1, "b": 2}`.
- **UTF-8 encoding** — bytes are what get hashed or signed.

## Why extract this at all

Both `transaction_signatures.sign_transaction` and `PostgresAuditLog.record` need to convert a dict to a stable byte sequence before hashing. Two places doing "the same" serialisation with slightly different code is exactly the recipe for a bug where signatures verify in one place and fail in the other. CLAUDE.md is explicit:

> **DRY principle.** Do not duplicate logic across modules. If two functions share a non-trivial step (canonical serialisation, key loading, error mapping), extract it once and reuse.

Extracting one function fixes this: any signer and any verifier that pass their payload through this helper produce byte-identical output.

## What is intentionally *not* guaranteed

- **Cross-language interoperability.** Python's `json.dumps` is deterministic on a given Python version with the specified options, but a Java or Go canonicaliser might handle unicode escaping or number formatting slightly differently. If a non-Python verifier ever needs to check our signatures or hashes, both sides must agree on the exact rules — that is a separate contract negotiation.
- **Handling of non-JSON types.** `datetime`, `bytes`, `Decimal`, and custom objects are not serialisable by default. Callers must convert to JSON-friendly types (`str`, `int`, `float`, `bool`, `None`, `list`, `dict`) before calling.
- **Floating-point normalisation.** Python's `json` writes `1.0` and `1` differently. If banking uses `float` for amounts, two records that are "equal in dollars" but built from different intermediate math might canonicalise differently. The standard mitigation is to use integer minor units (e.g. cents) — this doc flags the concern, banking's schema will decide.
- **Unicode normalisation.** JSON escapes non-ASCII characters by default; NFC/NFD equivalent strings will canonicalise differently. Usernames and other user-supplied strings should be NFC-normalised at the boundary if this matters.

## What this does *not* defend against

Nothing on its own — it is a serialisation helper. It gains meaning only when combined with a hash or signature. See [transaction-signatures.md](transaction-signatures.md) and [audit-chain.md](audit-chain.md).

## Tests that pin this behaviour

The primitive is small enough that it doesn't have its own test file. It is *transitively* pinned by:

- Transaction signature round-trip tests in [test_transaction_signatures.py](../../shared_security/tests/test_transaction_signatures.py) — specifically the "insertion order does not matter" test proves the canonicalisation guarantee.
- Audit chain tests in [test_audit_chain.py](../../shared_security/tests/test_audit_chain.py) — proves that the same event dict produces the same recorded hash.

If a future refactor changes the serialisation rules, both test files will break — the tests are the guardrail.

## Usage sites in the current build

- [transaction_signatures.py](../../shared_security/src/shared_security/transaction_signatures.py) — hashes over canonical form.
- [audit_log.py](../../auth_service/src/auth_service/infrastructure/audit_log.py) — canonicalises each event dict before chaining.
