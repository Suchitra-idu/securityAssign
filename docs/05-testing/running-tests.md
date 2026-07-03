# Running tests

Two test suites. Both use pytest.

## One-time setup

From the repo root, with a Python 3.11+ venv activated:

```
pip install -e './shared_security[dev]' -e './auth_service[dev]'
```

`[dev]` pulls pytest and (for auth_service) httpx.

## Running shared_security tests

```
cd shared_security
pytest -q
```

Expected: `21 passed in ~1.5s`.

Fast because every primitive is either pure computation or a bcrypt call — no I/O, no network.

## Running auth_service tests

```
cd auth_service
pytest -q
```

Expected: `34 passed in ~10s`.

The bulk of the time (~7 seconds) is bcrypt inside the login / register tests. Bcrypt-cost 12 takes ~100 ms per hash, and the suite exercises ~70 hashes.

The remaining ~3 seconds is FastAPI TestClient overhead.

## Running everything

From repo root:

```
(cd shared_security && pytest -q) && (cd auth_service && pytest -q)
```

## Running a specific test file

```
pytest tests/test_login.py -q
```

## Running a specific test

```
pytest tests/test_login.py::test_login_wrong_password_rejected_and_no_refresh_token_stored -q
```

## Running with verbose output

```
pytest -v
```

Shows every test name and status. Useful when a failure isn't in the last few tests.

## Running with print debugging

```
pytest -s
```

Doesn't capture stdout, so `print()` statements appear inline. `pytest.set_trace()` also works for pdb.

## Running with coverage (optional)

Coverage isn't part of the standard workflow but is one install away:

```
pip install coverage
coverage run -m pytest && coverage report -m
```

Skip this if you're just running tests during development. The security tests are targeted rather than coverage-driven.

## What is *not* run

- **Postgres integration tests.** They don't exist yet. See [strategy.md](strategy.md) and [../../flags.md](../../flags.md#6-real-postgres-integration-test).
- **End-to-end tests through Caddy / WAF.** Neither is built.
- **Load tests.** Not in scope.

## Test discovery

Each package's `pyproject.toml` configures pytest:

```
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- `pythonpath = ["src"]` — makes the `src/` layout importable during tests.
- `testpaths = ["tests"]` — where pytest looks for test files.

That's why you run pytest *from inside* each package directory. Running from the repo root would need `-c` or explicit paths.

## Fixture wiring

- Shared_security uses one fixture: `keypair` in [conftest.py](../../shared_security/tests/conftest.py). Yields a fresh Ed25519 keypair for tests that need one.
- Auth_service uses richer fixtures in [conftest.py](../../auth_service/tests/conftest.py): `FakeUserRepo`, `FakeRefreshStore`, `FakeAudit`, `FakeClock`, and a `bag` fixture that bundles everything into `AuthDeps`.

The application-layer tests use `bag` directly. The integration tests reference the same fake classes to build a `deps_factory` override for `create_app`.
