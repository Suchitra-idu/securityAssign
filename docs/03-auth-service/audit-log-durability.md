# Audit-log durability model

Two subtle decisions in {{ src("auth_service/src/auth_service/infrastructure/audit_log.py", text="PostgresAuditLog") }} that deserve their own page: the **separate autocommit connection** for audit writes, and the **`LOCK TABLE ... IN SHARE ROW EXCLUSIVE MODE`** inside each write. Both exist to preserve properties that a naive implementation would violate.

## Property 1: Failed operations must still audit

Failed logins are exactly the events fail2ban and analysts care about most. If they vanish when the request rolls back, the audit log is worse than useless — it flatters the operator into thinking nothing bad is happening.

The naive design puts audit writes in the same transaction as everything else. Then:

- Login succeeds → main txn commits → refresh-token INSERT and audit event persist together. ✅
- Login fails → main txn rolls back → refresh-token wasn't inserted anyway → **audit event also rolls back**. ❌ Attack invisible.

The fix is to give the audit sink its own connection, set to **autocommit**. Every `record()` call opens a brief explicit transaction on that connection and commits before returning to the caller. The caller's main transaction is unaffected — it can commit or roll back on its own timeline without touching audit durability.

Concretely, the FastAPI dependency generator in {{ src("auth_service/src/auth_service/infrastructure/app.py") }} opens **two connections** per request:

```python
def deps_factory() -> Iterator[AuthDeps]:
    with pool.connection() as main_conn, pool.connection() as audit_conn:
        audit_conn.autocommit = True
        with main_conn.transaction():
            yield AuthDeps(
                users=PostgresUserRepository(main_conn),
                refresh_tokens=PostgresRefreshTokenStore(main_conn),
                audit=PostgresAuditLog(audit_conn),
                clock=SystemClock(),
                settings=config.tokens(),
            )
```

The main connection is transactional. The audit connection is autocommit. Repos over the main connection all share the request's transaction. The audit sink commits independently.

### Cost

- Two connections per request halves the pool's effective concurrency. Default pool size 10 → ~5 in-flight requests. Bumpable via `AUTH_POOL_MAX_SIZE`.
- Bcrypt inside the transaction still holds the main connection for ~100 ms per login/register. Higher pool size compensates. This is a trade we consciously make — the alternative (hashing outside the transaction) would leak crypto out of the application layer.

### Property preserved

If the main transaction commits, both main writes and audit writes are visible.

If the main transaction rolls back, main writes are gone but the audit write persists. **Failed logins are always logged.**

## Property 2: Concurrent writers must not fork the chain

The chain hash is computed as:

```
new_hash = SHA256(prev_hash || canonical_record_bytes)
```

If two writers concurrently:
1. Both read the same "last hash" = `H`.
2. Both compute their new hash relative to `H`.
3. Both insert.

Now two consecutive rows both claim `prev_hash = H`. Neither points to the other. The chain has forked. `verify_chain` will fail on one of them regardless of which is the "real" successor — the chain is corrupt.

Postgres' default isolation level (READ COMMITTED) does not prevent this. Even SERIALIZABLE would raise a serialisation-anomaly error and require the loser to retry, which is more overhead than we need.

The fix: acquire an explicit table-level lock that serialises writers:

```python
def record(self, event: dict) -> None:
    with self._conn.transaction():
        self._conn.execute("LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE")
        ...
```

`SHARE ROW EXCLUSIVE` is the lightest lock that conflicts with itself. It allows concurrent readers (which take `ACCESS SHARE`) but blocks concurrent `LOCK TABLE ... IN SHARE ROW EXCLUSIVE` from another writer. Writers queue; readers do not.

The `with self._conn.transaction():` is required because table locks are held until end of transaction. In an autocommit connection, `execute("LOCK TABLE ...")` alone would release the lock at end of that single statement — useless. Wrapping in an explicit transaction holds the lock until the audit row is inserted, then commits and releases.

### Cost

- Serialised audit throughput. On this service that is fine — auth events are low volume.
- Blocks readers only briefly (SHARE ROW EXCLUSIVE holds until the audit transaction ends, ~1 ms).

### Property preserved

`prev_hash` in each row always refers to the *previous inserted row*'s stored `hash`. Chain never forks. `verify_chain` succeeds on a well-behaved log.

## Verification story

To check the chain end-to-end, an auditor reads:

```sql
SELECT event::text, prev_hash, hash FROM audit_log ORDER BY id ASC;
```

Passes each `(record, hash)` pair through `shared_security.audit_chain.verify_chain`. Any mismatch means the log was tampered with, deleted from, inserted into, or the chain was forked (per Property 2).

`event::text` needs to be re-parsed and re-canonicalised through `canonical_json_bytes` — the primitive is documented in {{ src("02-shared-security/canonical-json.md", text="../02-shared-security/canonical-json.md") }}.

## What this design does *not* guarantee

- **Absence of records.** If a writer crashed before `audit.record()` was called, the event was never emitted. The chain remains internally consistent; the missing event is not detectable from the chain alone. Sequence numbers with expected next-id would catch this — not implemented.
- **Correctness of the recorded event.** Nothing prevents the application code from writing `"event": "login_success"` when the login actually failed. That is a logging-correctness issue in the application layer, not a chain integrity issue.
- **Repudiation.** The chain proves that a sequence of records was not tampered with after insertion, but not that they were inserted by a legitimate signer. If tighter guarantees are needed, sign the chain head periodically with a key held outside the DB — noted in the report writeup, not implemented.

## Simpler alternatives we rejected

| Alternative | Why rejected |
|-------------|--------------|
| Single transaction, audit inside | Loses failed-login events (property 1). |
| SERIALIZABLE isolation instead of LOCK TABLE | Adds retry loops; retries are complex under FastAPI's request model. |
| Advisory transaction lock (`pg_advisory_xact_lock`) | Works equivalently but with an integer key that has no natural documentation; `LOCK TABLE` names its subject. |
| Application-level mutex | Doesn't survive process restarts, wouldn't work across replicas. |
| Kafka / append-only external log | Overkill for the demo, and DEV_GUIDE explicitly says "audit log stays a single table" as a release valve. |

## Tests that pin this behaviour

- The application-layer tests use a `FakeAudit` that always accepts writes, so they cover *what gets recorded* but not *how it persists*. See {{ src("auth_service/tests/test_login.py") }} `test_login_failure_writes_audit_event_without_leaking_password` for the "failed operation still records an audit event" property at the use-case level.
- The chain integrity primitive itself is tested in {{ src("shared_security/tests/test_audit_chain.py") }}.
- **Real Postgres integration tests** for `PostgresAuditLog` (verifying concurrent writers don't fork, chain survives round trip, LOCK behaves) are a follow-up — {{ src("flags.md", text="flag 6") }}.
