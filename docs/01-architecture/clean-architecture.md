# Clean architecture applied

The auth service follows the **light clean architecture** described in {{ src("DEV_GUIDE.md", text="../../DEV_GUIDE.md") }} and {{ src("CLAUDE.md", text="../../CLAUDE.md") }}. Three layers, dependencies pointing inward only. The shared_security module is intentionally flat — it is a library of primitives, not a service.

## The rule

```
    ┌─────────────────────────────────────────────────┐
    │              Infrastructure                     │
    │  FastAPI routes · Postgres repos · config       │
    │  · Docker · pydantic-settings · psycopg3        │
    │                                                 │
    │   ┌───────────────────────────────────────┐    │
    │   │           Application                 │    │
    │   │  register · login · refresh use cases │    │
    │   │  Ports (Protocols) · TokenSettings    │    │
    │   │  AuthDeps · TokenPair · audit.emit    │    │
    │   │                                       │    │
    │   │   ┌─────────────────────────────┐    │    │
    │   │   │         Domain              │    │    │
    │   │   │  User · Role · RefreshRecord │    │    │
    │   │   │  Errors                     │    │    │
    │   │   └─────────────────────────────┘    │    │
    │   │                                       │    │
    │   └───────────────────────────────────────┘    │
    │                                                 │
    └─────────────────────────────────────────────────┘

           dependencies point inward only  ──▶
```

## What "points inward only" means concretely

- The **domain layer** ({{ src("auth_service/src/auth_service/domain/", text="auth_service/src/auth_service/domain/") }}) imports from nothing except the standard library. Confirm this yourself:
  ```
  $ grep -R "^import\|^from" auth_service/src/auth_service/domain/
  domain/users.py:from dataclasses import dataclass
  domain/users.py:from typing import Literal
  domain/refresh.py:from dataclasses import dataclass
  ```
  No FastAPI, no Postgres, no shared_security. Pure data + errors.
- The **application layer** ({{ src("auth_service/src/auth_service/application/", text="auth_service/src/auth_service/application/") }}) imports from the domain layer and from shared_security. It does not import FastAPI or psycopg.
- The **infrastructure layer** ({{ src("auth_service/src/auth_service/infrastructure/", text="auth_service/src/auth_service/infrastructure/") }}) imports from application and domain — never the reverse.

## Why "light" and not "strict"

Strict clean architecture wraps every external dependency in a formal port/adapter. That is a lot of indirection for a 14-day build. The pragmatic rule from CLAUDE.md is:

> Do not wrap every external dependency in a formal port/adapter — only add one where there is a concrete benefit (e.g. swappable crypto backend).

Where we did add ports:

- {{ src("auth_service/src/auth_service/application/ports.py") }} — `UserRepository`, `RefreshTokenStore`, `AuditLog`, `Clock`. These have real benefit: tests swap in fakes so use cases can be unit-tested without Postgres, and infrastructure swaps in the Postgres implementations at runtime. This is exactly the "swappable backend" case CLAUDE.md talks about.

Where we did **not** add ports:

- Password hashing, token signing, refresh-token hashing — all called directly through `shared_security` functions. Reason: there is no realistic scenario where we want a fake bcrypt or fake Ed25519 in tests. Real primitives are fast enough (bcrypt at cost factor 12 ≈ 100 ms; Ed25519 signing ≪ 1 ms).
- FastAPI itself. FastAPI-shaped adapters over FastAPI would be theatre.

## Where crypto is called from

Only from the application layer. The rule from CLAUDE.md:

> Crypto is called from the application layer through a thin boundary so use cases stay unit-testable without real keys.

Concretely:
- {{ src("auth_service/src/auth_service/application/tokens.py") }} calls `shared_security.tokens.sign_token`.
- {{ src("auth_service/src/auth_service/application/login.py") }} calls `shared_security.passwords.verify_password`.
- {{ src("auth_service/src/auth_service/application/register.py") }} calls `shared_security.passwords.hash_password`.

The domain layer does not touch crypto. The infrastructure layer does not touch crypto except through the `PostgresAuditLog` which uses `shared_security.audit_chain` to build the hash chain (that is application-adjacent — see {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }} for the split-of-concerns argument).

## The AuthDeps container

To keep use-case signatures short, dependencies are grouped in one dataclass:

```python
@dataclass(frozen=True)
class AuthDeps:
    users: UserRepository
    refresh_tokens: RefreshTokenStore
    audit: AuditLog
    clock: Clock
    settings: TokenSettings
```

Every use case takes `deps: AuthDeps` and pulls the fields it needs. This has one small downside — a use case that only needs `users` still receives everything else — but the ergonomic win at call sites is large. See {{ src("auth_service/src/auth_service/application/deps.py") }}.

## Why the shared_security module is flat

{{ src("02-shared-security/overview.md", text="../02-shared-security/overview.md") }} covers this, but the summary: shared_security is a library of primitives, not a service. Each primitive is a small module (`passwords.py`, `tokens.py`, ...). Layering a library that has no application-level use cases and no delivery-mechanism concerns would be over-engineering. If a caller wants to build a service around these primitives, they impose their own layering (as auth_service does).

## What this buys us

- **Use-case tests run in ~7 seconds** ({{ src("auth_service/tests/", text="auth_service/tests/") }}) with no database, no HTTP, no keys loaded from disk. Every one of the 23 pure-application tests instantiates fake ports directly.
- **Integration tests run at TestClient speed** without a real Postgres because we override the deps factory. See {{ src("auth_service/tests/test_integration.py") }}.
- **The application layer is a printed spec.** A reader who wants to know exactly what `refresh` does opens {{ src("auth_service/src/auth_service/application/refresh.py") }} — 20 lines — and sees the whole rule.
