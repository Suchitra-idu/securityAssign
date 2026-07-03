# Audit hash chain

Tamper-evident append-only log. Each record's stored hash includes the previous record's stored hash, so any retroactive edit or deletion breaks the chain.

## API

```python
GENESIS_HASH: bytes = bytes(32)  # 32 zero bytes

def compute_chain_hash(previous_hash: bytes, record: bytes) -> bytes
def verify_chain(chain: list[tuple[bytes, bytes]]) -> bool
```

Implementation: [audit_chain.py](../../shared_security/src/shared_security/audit_chain.py).

- `compute_chain_hash(prev, record) = SHA256(prev || record)`.
- `verify_chain(chain)` walks the chain from `GENESIS_HASH` and returns `False` if any stored hash disagrees.

## The idea

Store each audit event with two extra columns: the hash of the previous record, and the hash of *this* record. On insert, compute:

```
new_hash = SHA256(prev_hash || canonical_record_bytes)
```

To verify: walk the log in order, recomputing each hash from `(prev_hash, record)`, and compare against the stored hash.

Any single-record edit changes that record's recomputed hash, which no longer matches the stored hash — and every subsequent record's recomputed hash will also mismatch. Deletion is detected the same way: the "next" record's `prev_hash` no longer points to what it should. Insertion in the middle rewrites all following stored hashes, which by definition can't be done silently in an append-only design.

## Why SHA-256

- Widely available, hardware-accelerated on modern CPUs.
- 256-bit output gives collision resistance far beyond anything practical here.
- Simpler than SHA-3 with no material security difference for this use case.

## Why not sign each record

Signing would give non-repudiation ("this record came from this signer"), but signing is expensive per record (Ed25519 signing is ~30 µs — cheap, but still). More importantly, hash-chaining catches *any* mutation, including a mutation done by a legitimate signer. For an audit log, we care about integrity of the sequence, not about which subject wrote each row. If a signer is required (e.g. for external audit), sign the *chain head* periodically rather than every record.

## Record shape

The primitive takes arbitrary `bytes`. The auth service serialises each event dict with `shared_security.canonical.canonical_json_bytes` before hashing. Canonicalisation matters because verification recomputes the hash from the reconstructed record — if the reconstruction produces different bytes, verification fails.

See [../03-auth-service/audit-log-durability.md](../03-auth-service/audit-log-durability.md) for how the auth service actually persists the chain.

## Concurrency

Two concurrent writers reading `prev_hash` at the same time would both derive `new_hash` from the same predecessor, then both insert. The second insertion's `prev_hash` claim would be wrong — the chain would fork.

The primitive itself does not solve this. The *auth service* solves it by acquiring `LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE` inside the audit write transaction, which serialises writers without blocking readers. See [audit_log.py](../../auth_service/src/auth_service/infrastructure/audit_log.py).

## What this defends against

- **Retroactive tampering with a single row.** Recomputed hash diverges.
- **Silent deletion of rows.** Subsequent recomputed hashes diverge.
- **Silent insertion of rows in the middle.** All following stored hashes need to be rewritten, which cannot be done atomically without discovery.

## What this does *not* defend against

- **Rewriting the entire log.** If an attacker can rewrite every row and every stored hash consistently — which requires DB write access — the chain remains internally consistent. Two defenses of this are: (a) periodically publish the current chain head to an external, harder-to-tamper location, and (b) sign the chain head with a key held elsewhere. Neither is implemented; both are noted in the report writeup.
- **Recording the wrong event.** If the writer records `login_success` when a failure occurred, the chain is still integrity-intact. Correctness of the record is a logging-code concern.
- **Missing writes.** If a writer crashes before flushing, the missing event was never in the chain. Nothing signals its absence unless combined with a sequence-number check.

## Tests that pin this behaviour

[test_audit_chain.py](../../shared_security/tests/test_audit_chain.py):

- Verify passes on a correctly built chain of several records.
- Verify passes on the empty chain.
- Mutating any record's bytes fails verification.
- Mutating any stored hash fails verification.
- The genesis case (`prev_hash = GENESIS_HASH`) is exercised by every test since chains start there.

## Usage sites in the current build

- [PostgresAuditLog](../../auth_service/src/auth_service/infrastructure/audit_log.py) — auth service's persistent audit sink. Every register, login (success and failure), and refresh (success and failure) event is chained.

Banking service will use the same primitive for its data-change audit log when built.
