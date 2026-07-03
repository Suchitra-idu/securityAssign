# Transaction signatures

Ed25519 signatures over canonical-JSON transaction records. Not used by any implemented service yet — banking service will sign transactions on write and verify on read.

## API

```python
def sign_transaction(tx: dict, private_key: str) -> bytes
def verify_transaction(tx: dict, signature: bytes, public_key: str) -> bool
```

Implementation: [transaction_signatures.py](../../shared_security/src/shared_security/transaction_signatures.py).

- `sign_transaction` returns raw 64-byte Ed25519 signature.
- `verify_transaction` returns `True` on valid signature, `False` otherwise. Does not raise.

## Why not just re-use JWTs

JWTs are for identity claims that carry an expiry and need to be presented in HTTP headers. Transactions are records that live forever in a database and get signed once. Different lifetime, different serialisation, different verification story.

Reasons for a dedicated primitive:

- **No expiry.** A transaction signature must remain valid indefinitely for audit.
- **Canonical serialisation.** JWT signs the base64-encoded header+payload. For a transaction record we want to sign the *canonical* form of the dict so the verifier can reproduce the exact bytes from the reconstructed record.
- **Simpler storage.** A raw 64-byte signature stored next to the transaction row is smaller than a JWT.

## Canonical serialisation

Both sign and verify hash over `canonical_json_bytes(tx)`. Canonicalisation guarantees:

- Same dict → same bytes → same signature.
- Different dict → different bytes → verification fails.
- Insertion order does not matter; whitespace does not matter; float format is deterministic.

See [canonical-json.md](canonical-json.md).

This is exactly the CLAUDE.md-listed reason to DRY: canonical serialisation is called out as a "shared non-trivial step". The audit-log sink uses the same helper (`shared_security.canonical.canonical_json_bytes`). One source of truth.

## Keys

PEM strings, same format and generation as [tokens.md](tokens.md). In the banking service, transaction-signing keys will likely be a *separate* keypair from token-signing so their lifetimes and access control can differ. That is a banking-service decision, not a shared-module decision.

## What this defends against

- **Non-repudiation.** A user cannot claim "I did not authorise this transaction" if the record is signed. (Assuming private key custody is what it should be — see below.)
- **Silent tampering.** If a DB writer or backup restore mutates the transaction row after signing, `verify_transaction` returns `False`.
- **Injection during read paths.** Even if the read path is compromised, a returned transaction fails verification unless it was signed by the legitimate key.

## What this does *not* defend against

- **Compromised signing key.** Same trust root as tokens. If banking's transaction-signing private key leaks, attackers can forge transactions.
- **Business-logic misuse.** Signing over `{"amount": 100, ...}` proves the record was authorised, not that transferring 100 was legitimate. Fraud detection is orthogonal.
- **Replay of a signed transaction.** If the same signed record can be inserted twice, both signatures are valid. Uniqueness must be enforced at the DB level (idempotency key, PK constraint).
- **Denial via key rotation.** If keys rotate and old records need verification, the verifier must know which historical public key was in use. Not built.

## Serialisation gotchas at the boundary

`canonical_json_bytes` uses Python's `json.dumps` internals. This is deterministic across Python versions on the tested implementations, but is *not* automatically interoperable with a different language's canonical-JSON. If banking is ever consumed by a non-Python signer, both sides must agree on the exact serialisation rules — see [canonical-json.md](canonical-json.md) for the details we rely on.

## Tests that pin this behaviour

[test_transaction_signatures.py](../../shared_security/tests/test_transaction_signatures.py):

- Round trip: `verify_transaction(tx, sign_transaction(tx, priv), pub) is True`.
- Wrong-key signature fails.
- Mutating a field in `tx` before verify fails.
- Truncated signature fails.
- Key insertion order does not matter: `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` produce identical signatures. This test locks in the canonicalisation guarantee that transaction records equal by content sign identically regardless of how they were constructed.

## Usage sites in the current build

None — the primitive exists but no service consumes it. Banking will call this from its transactions use case.
