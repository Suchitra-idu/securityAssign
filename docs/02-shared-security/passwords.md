# Password hashing

Bcrypt with library defaults. Two functions.

## API

```python
def hash_password(password: str) -> str
def verify_password(password: str, hashed: str) -> bool
```

Implementation: [passwords.py](../../shared_security/src/shared_security/passwords.py).

- `hash_password` returns a bcrypt hash string (starts with `$2b$12$…` at library default cost).
- `verify_password` returns `True` on match, `False` on mismatch or malformed hash.
- Both take/return `str`. Encoding to UTF-8 is done internally.

## Why bcrypt and not Argon2id

CLAUDE.md and DEV_GUIDE both call this out explicitly. Argon2id is the current OWASP first choice. Bcrypt was picked because:

1. It is what the course covered — the students building this understand its parameters and failure modes.
2. Adaptive work factor (bcrypt cost) — the same knob as Argon2id's time cost.
3. Built-in salt — no separate salt column to manage or leak.
4. Widely audited and battle-tested for two decades.
5. On a 14-day build, an unfamiliar library is a schedule risk without a security win.

The bcrypt choice is documented as a deliberate one. The report will note that Argon2id is the modern default and that a real production build would revisit this.

## Cost factor

`bcrypt.gensalt()` uses cost 12 by default in the `bcrypt` library currently pinned. That is ~100 ms per hash on a modern CPU — the intended slowdown to make offline dictionary attacks expensive. We accept the latency for register and login.

If the cost factor is ever adjusted, `verify_password` still works — bcrypt encodes the cost in the hash string. Old hashes stay valid without rehashing.

## Salting

Bcrypt generates a fresh 16-byte random salt on every `hash_password` call and embeds it in the returned string. Verifying is deterministic given the stored hash. Two hashes of the same password will differ — that is the entire point.

## What this defends against

- **Rainbow tables.** Per-user salt makes precomputed tables useless.
- **Offline dictionary attacks.** Cost 12 makes brute force prohibitively slow — hundreds of milliseconds per guess even on GPU-oriented setups.
- **Password reuse across sites.** If our database leaks, cracking a hash to recover the plaintext for use on another site is still feasible if the password is weak, but not fast.

## What this does *not* defend against

- **Weak passwords.** A user picking `password123` will be cracked eventually. Mitigation is at the application layer: minimum length is enforced by [schemas.py](../../auth_service/src/auth_service/infrastructure/schemas.py) at 12 characters. No dictionary check or entropy score is done — a real deployment would add one.
- **Online guessing.** Rate limiting is the WAF's job. Not implemented yet.
- **Timing attacks on username existence.** `login()` short-circuits when the user is unknown, so response time reveals user existence. See [flag 1](../../flags.md).
- **Bcrypt truncation quirks.** Bcrypt truncates passwords at 72 bytes. Our max password length (128 chars) exceeds this. If a user picks a very long password, only the first 72 bytes matter. Documented; not compensated for. A real deployment might pre-hash with SHA-256 and base64-encode, then bcrypt — the standard workaround.

## Tests that pin this behaviour

[test_passwords.py](../../shared_security/tests/test_passwords.py):

- Round trip: `verify_password(pw, hash_password(pw))` is `True`.
- Wrong password fails: `verify_password("other", hash_password(pw))` is `False`.
- Two hashes of the same password differ (salt is random).
- Verify returns `False` for a malformed hash rather than raising.

## Usage sites in the current build

- [register.py](../../auth_service/src/auth_service/application/register.py) — hashes password on user creation.
- [login.py](../../auth_service/src/auth_service/application/login.py) — verifies password on authentication.
