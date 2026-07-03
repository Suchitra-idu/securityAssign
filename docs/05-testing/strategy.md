# Testing strategy

TDD strictly on the security-critical core; lighter testing on plumbing. The rule comes from [../../CLAUDE.md](../../CLAUDE.md):

> **Test first**: shared security module and authorization checks.
>
> **Not test first**: FastAPI route wiring, Postgres access code, Docker/Caddy config — cover with a few integration checks once wired.

## Why this split

Test-first is slow up front. On a 14-day build we spend that cost only where the payback is real:

- **Security primitives.** A wrong answer here is a vulnerability. Writing the test first forces us to state the security property precisely ("a token signed with an attacker's key must fail verification") before writing the primitive. It also means the tests double as the readable specification of the crypto boundary — [contract 1](../01-architecture/contracts.md) is essentially "read the tests".
- **Authorization checks.** Same logic. Getting "customer cannot see admin data" wrong is a real bug that a passing HTTP smoke test could hide.

For plumbing (route wiring, DB access, container config), TDD mostly re-tests the framework. Not worth the time on this schedule.

## What that looks like in practice

### Shared security module — 21 tests, test-first ([shared_security/tests/](../../shared_security/tests/))

Every primitive:
- Round-trip test: `verify(sign(x)) == x`, `decrypt(encrypt(x)) == x`.
- Negative test: forged / tampered / wrong-key fails.
- Boundary tests: expired, empty chain, insertion-order-independence.

The tests were written before the implementation. The commit history shows this.

### Auth service, application layer — 23 tests, test-first ([auth_service/tests/test_register.py](../../auth_service/tests/test_register.py), etc.)

The three use cases (register, login, refresh) each got a full test file before the use-case code was written. Every test runs against fake ports — no HTTP, no Postgres, no key material loaded from disk. Time to run: ~7 seconds.

### Auth service, infrastructure — 11 integration tests, *not* test-first ([test_integration.py](../../auth_service/tests/test_integration.py))

Written after the FastAPI app + Pydantic schemas were wired. Uses `TestClient` for real HTTP. Uses fake ports (injected via the `deps_factory` override) so no Postgres is required. Covers:

- Route wiring.
- Pydantic input validation → 422 response.
- Domain error → HTTP status mapping (409, 401).
- Response body shape (Pydantic response models).

Not TDD because these tests would mostly assert on FastAPI's own behaviour if written first.

### Postgres integration — not yet built

The Postgres repos and the `PostgresAuditLog` chain-lock behaviour are covered only by manual smoke testing (`docker compose up`). Automated Postgres tests (via testcontainers-python or a compose profile) are a follow-up — [flag 6](../../flags.md).

## Tests as spec, not tests as coverage

The shared_security tests are consciously designed as the readable specification of the crypto boundary. Person B (who owns banking service) reads these tests to understand exactly what each shared function does — Person B does not write them. From [../../DEV_GUIDE.md](../../DEV_GUIDE.md):

> The tests here do double duty. They are also the readable specification of the crypto boundary that Person B builds against.

Auth's application-layer tests do the same job for the token payload contract — a test that asserts `claims["role"] == "customer"` is the contract.

## What we deliberately do not test

- **Framework behaviour.** No test that FastAPI returns 404 for an unknown route. FastAPI's own tests cover that.
- **The clock is really the clock.** No test that `SystemClock.now()` returns real time. `time.time()` is stdlib.
- **Bcrypt cost factor.** No test that hashing takes ~100 ms. That is a bcrypt-library concern.
- **JSON serialisation of dataclasses via Pydantic.** No test that `UserResponse` serialises to the right shape. Pydantic covers that.

Overtesting the framework is a common mistake on a rushed timeline. The security tests are the ones the assignment marks against; the plumbing tests are for our own sanity.

## What every security test *does* prove

Each security test picks a single property and asserts it. The full walkthrough of "what each test proves" is in [what-tests-prove.md](what-tests-prove.md).

## Running

See [running-tests.md](running-tests.md).
