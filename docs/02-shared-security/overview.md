# shared_security — overview

A small Python package of cryptographic and integrity primitives, imported by every service. **One implementation of each primitive** — no service duplicates crypto code.

## Layout

Flat, deliberately. See {{ src("01-architecture/clean-architecture.md", text="../01-architecture/clean-architecture.md") }} for why the layering rule that applies to FastAPI services does *not* apply here.

```
shared_security/
├── pyproject.toml
├── src/shared_security/
│   ├── __init__.py
│   ├── passwords.py              — bcrypt hash/verify
│   ├── tokens.py                 — Ed25519 JWT sign/verify + keygen
│   ├── field_crypto.py           — AES-256-GCM encrypt/decrypt
│   ├── transaction_signatures.py — Ed25519 sign/verify over canonical-JSON tx
│   ├── audit_chain.py            — SHA-256 chain-hash + full-chain verify
│   └── canonical.py              — deterministic JSON serialisation
└── tests/
    ├── conftest.py               — Ed25519 keypair fixture
    ├── test_passwords.py
    ├── test_tokens.py
    ├── test_field_crypto.py
    ├── test_transaction_signatures.py
    └── test_audit_chain.py
```

## The five primitives

| Primitive | File | Doc |
|-----------|------|-----|
| Password hashing (bcrypt) | {{ src("shared_security/src/shared_security/passwords.py") }} | [passwords.md](passwords.md) |
| Token signing (Ed25519 JWT) | {{ src("shared_security/src/shared_security/tokens.py") }} | [tokens.md](tokens.md) |
| Field encryption (AES-256-GCM) | {{ src("shared_security/src/shared_security/field_crypto.py") }} | [field-crypto.md](field-crypto.md) |
| Transaction signatures (Ed25519) | {{ src("shared_security/src/shared_security/transaction_signatures.py") }} | [transaction-signatures.md](transaction-signatures.md) |
| Audit hash chain (SHA-256) | {{ src("shared_security/src/shared_security/audit_chain.py") }} | [audit-chain.md](audit-chain.md) |
| Canonical JSON | {{ src("shared_security/src/shared_security/canonical.py") }} | [canonical-json.md](canonical-json.md) |

## Guarantees at the boundary

- **Deterministic behaviour where required.** `canonical_json_bytes` produces byte-identical output for equal dicts. Transaction verification depends on this.
- **Explicit failure modes.** Every primitive documents whether it raises or returns `False` on failure. See {{ src("01-architecture/contracts.md", text="../01-architecture/contracts.md") }}.
- **No global state.** Every function takes its keys and material as arguments. No key registry, no module-level singletons, no environment reads. Callers own key management.
- **Pinned algorithms.** Where an algorithm choice exists (JWT `alg`), it is pinned in code and the token header is never trusted to override it.

## Non-goals — things this module deliberately does not do

- **Key management.** No rotation, storage, or retrieval helpers. Auth service reads keys from env vars; banking service will fetch the public key from `/public-key`. That is the callers' problem, not shared_security's.
- **Session models.** No `User`, no `Session`, no `Token` domain type. Those live in each service's domain layer.
- **Retry logic, timeouts, or connection management.** shared_security is a pure library.
- **Logging.** Callers log around the primitive if they need to.

## Test-first policy

Per {{ src("CLAUDE.md", text="../../CLAUDE.md") }}, shared_security is built test-first. Every test in {{ src("shared_security/tests/", text="shared_security/tests/") }} was written before the implementation. The tests double as the readable specification of the crypto boundary — {{ src("05-testing/what-tests-prove.md", text="../05-testing/what-tests-prove.md") }} walks through what each one asserts.

## Ownership

Person A owns this module. Person B *depends* on it but does not modify it. If a change is required for banking service, it goes through Person A.

## Dependencies

```toml
dependencies = [
    "bcrypt>=4.0",
    "cryptography>=42",
    "PyJWT[crypto]>=2.8",
]
```

- **bcrypt** — password hashing.
- **cryptography** — Ed25519 key generation, AES-GCM primitive.
- **PyJWT[crypto]** — JWT sign/verify. The `[crypto]` extra pulls the asymmetric-key backends.

No other runtime dependencies. Standard library covers hashlib, hmac, base64, json, os.urandom, secrets.
