## CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repo currently contains only [DEV_GUIDE.md](DEV_GUIDE.md) — a design document for a secure banking application. No code, build system, or tests exist yet. Any work here is greenfield; treat [DEV_GUIDE.md](DEV_GUIDE.md) as the source of truth for architecture, ownership, and scope decisions until code lands.

## What is being built

A secure banking application (customer + admin roles) whose purpose is to demonstrate real security controls at algorithm, protocol, and system level. Feature set is deliberately small — depth on security beats feature breadth. Timeline is 14 days with no buffer, so every architectural choice trades against that.

## Planned stack

- Backend services: FastAPI (Python)
- Database: PostgreSQL (also used as the audit log store)
- Reverse proxy + WAF: Caddy with Coraza (OWASP core rule set), automatic TLS
- Orchestration: Docker Compose (Caddy is the only exposed service; Postgres has no published port)
- Host IDS: fail2ban watching auth logs
- Password hashing: bcrypt (deliberate pick over Argon2id — document the choice in the report)

Anything here can be swapped if it fights the build — update [DEV_GUIDE.md](DEV_GUIDE.md) when you swap so the other person is not surprised.

## Repository layout (planned)

One git repo, four codebases:

1. **Shared security module** — all crypto/security primitives (password hashing, asymmetric token sign/verify, AES-256-GCM field encryption, transaction digital signatures, SHA-256 hash-chain helper for the audit log). Single source of truth — both services depend on it, neither duplicates it.
2. **Auth service** (FastAPI) — holds the *private* signing key. Register, login, refresh with rotation, public key endpoint, role claims, audit-logs every auth event.
3. **Banking service** (FastAPI) — holds *only* the public key. Verifies tokens, enforces customer-vs-admin RBAC, encrypts sensitive fields (account number, balance, card details) on write and decrypts on read as the default path, signs transactions, audit-logs data changes.
4. **Proxy + WAF** — Caddy config + Coraza rules. Terminates TLS, rate limits, reverse-proxies to services over HTTPS.

## Architecture rules (apply to each FastAPI service)

Light clean architecture, three layers, dependencies point inward only:

- **Domain** — pure business rules and data shapes. No FastAPI, no Postgres, no HTTP imports here.
- **Application** — use cases (register, login, transfer, read account). Orchestrates domain and calls out through thin interfaces. Does not know it is being called from a web request.
- **Infrastructure** — FastAPI routes, Postgres access, config, wiring. Depends on the two inner layers; never the reverse.

Crypto is called from the application layer through a thin boundary so use cases stay unit-testable without real keys. Do **not** wrap every external dependency in a formal port/adapter — only add one where there is a concrete benefit (e.g. swappable crypto backend).

## Testing rules

TDD strictly on security-critical code, lighter testing on plumbing:

- **Test first**: shared security module (round trips, forged tokens rejected, tampered ciphertext fails, broken hash chain detectable, wrong password fails) and authorization checks (customer cannot reach another customer's account, customer blocked from admin-only actions, missing/invalid token rejected).
- **Not test first**: FastAPI route wiring, Postgres access code, Docker/Caddy config — cover with a few integration checks once wired.

The security-module tests double as the readable spec of the crypto boundary that Person B builds against.

## Ownership split — do not cross this line

- **Person A** owns: shared security module (code + tests), auth service, proxy + WAF, Docker Compose, network isolation, fail2ban, encrypted backup job.
- **Person B** owns: banking service end-to-end. Consumes the shared module as a fixed dependency and **does not modify it** — any crypto change is requested from Person A, not edited directly.

Two contracts must be agreed up front and never changed silently:

1. **Crypto function boundary** — names and signatures of shared security functions.
2. **Token payload** — claims (role, user identity, expiry) that auth mints and banking reads.

A change to either is a conversation between the two people, not a silent edit. Keep both written down and in sync with reality.

## Build order (dependencies matter)

1. Person A builds the shared security module first, locks the crypto boundary and token payload. Person B works in parallel on banking domain/application layers (pure logic, no crypto yet).
2. Person A builds the auth service on the shared module. Person B wires crypto into banking infrastructure.
3. Person A picks up proxy, WAF, deployment. Person B finishes banking.
4. Integration: fire test attacks at the WAF, verify the audit chain detects tampering, test a backup restore.

## Release valves if time runs short

Depth on the assessed security points beats adding more. Pre-agreed fallbacks:

- WAF drops to Caddy rate limiting + filtering, with Coraza described fully in the report.
- mTLS between proxy and services stays documented only (not implemented).
- Audit log stays a single table.

## Security points that count toward the grade

TLS 1.3 client→proxy, network isolation (no published DB port), WAF, HTTPS proxy→services, password hashing + token signing, customer/admin RBAC enforcement on every banking request, token verification + field encryption + transaction signing in banking, TLS services→DB, encryption at rest for sensitive fields, hash-chained audit log, encrypted backups, plus fail2ban IDS on auth logs.

## Coding rules

- **No excessive comments or docstrings.**
- **Keep code super clean.** Small functions, meaningful names, no dead branches, no defensive checks for conditions that cannot happen inside trusted internal code. Validate only at real boundaries (user input, external I/O, crypto inputs coming from untrusted callers). No feature flags or backwards-compat shims when the code can just change.
- **DRY principle.** Do not duplicate logic across modules. If two functions share a non-trivial step (canonical serialisation, key loading, error mapping), extract it once and reuse.
- **DRY analysis after every implementation.** As soon as a module or feature is finished, re-read the surrounding code and check for: repeated constants, repeated serialisation, repeated exception-mapping patterns, near-identical function bodies. Collapse duplication before moving on. Record the outcome ("checked, nothing to collapse" or "extracted X into Y") so the next implementation starts from a clean base.
