# Locked contracts

Per {{ src("CLAUDE.md", text="../../CLAUDE.md") }}:

> Two contracts must be agreed up front and never changed silently:
>
> 1. **Crypto function boundary** — names and signatures of shared security functions.
> 2. **Token payload** — claims (role, user identity, expiry) that auth mints and banking reads.

Both are documented here. **A change to either is a conversation between Person A and Person B, not a silent edit.**

---

## Contract 1: Crypto function boundary

Public API of `shared_security`. Callers depend only on the names, arguments, and return types documented below. Internal implementation may change.

### `shared_security.passwords`

```python
def hash_password(password: str) -> str
def verify_password(password: str, hashed: str) -> bool
```
- Hash string is bcrypt-formatted (starts with `$2b$`).
- `verify_password` returns `False` on mismatch and on malformed hash. It does not raise.

### `shared_security.tokens`

```python
ALGORITHM = "EdDSA"

class TokenError(Exception): ...

def generate_signing_keypair() -> tuple[str, str]      # (private_pem, public_pem)
def sign_token(claims: dict, private_key: str) -> str  # returns compact JWT
def verify_token(token: str, public_key: str) -> dict  # returns claims, raises TokenError
```
- Keys are PEM-encoded strings.
- `verify_token` raises `TokenError` on any failure (bad signature, expired, wrong algorithm, malformed). It does not return `None`.
- Algorithm is pinned to `EdDSA` — the `alg` field in the token header is never trusted.

### `shared_security.field_crypto`

```python
class DecryptionError(Exception): ...

def generate_field_key() -> bytes                       # 32 bytes
def encrypt_field(plaintext: bytes, key: bytes) -> bytes  # nonce || ciphertext_with_tag
def decrypt_field(blob: bytes, key: bytes) -> bytes     # raises DecryptionError on tag mismatch
```
- Encrypted blob format: 12-byte random nonce followed by AES-256-GCM ciphertext (which includes the 16-byte auth tag).
- Callers do not manage the nonce; each `encrypt_field` call draws a fresh nonce from `os.urandom`.

### `shared_security.transaction_signatures`

```python
def sign_transaction(tx: dict, private_key: str) -> bytes
def verify_transaction(tx: dict, signature: bytes, public_key: str) -> bool
```
- Input `tx` is a JSON-serializable dict.
- Signature is computed over `canonical_json_bytes(tx)` — see below.
- `verify_transaction` returns `False` on mismatch. It does not raise.

### `shared_security.audit_chain`

```python
GENESIS_HASH: bytes = bytes(32)                                       # 32 zero bytes

def compute_chain_hash(previous_hash: bytes, record: bytes) -> bytes  # SHA-256
def verify_chain(chain: list[tuple[bytes, bytes]]) -> bool
```
- `chain` is a list of `(record, stored_hash)` pairs in insertion order.
- `verify_chain` returns `False` if any hash does not match `SHA256(previous_hash || record)`.

### `shared_security.canonical`

```python
def canonical_json_bytes(payload: dict) -> bytes
```
- Deterministic JSON serialisation: `sort_keys=True`, no whitespace between separators, UTF-8 encoded.
- Used by transaction signatures and audit-log record hashing so hashes are stable across runs and languages.

### What is *not* in the contract
- Internal helpers (any function starting with `_`).
- Internal module structure.
- Choice of underlying library (bcrypt version, PyJWT, cryptography). These may change if all listed guarantees hold.

---

## Contract 2: Token payload

Auth service mints. Banking service verifies with the public key from `GET /public-key` and reads these claims.

### Access token

Signed JWT, algorithm `EdDSA`, verified with the public key served by auth.

```json
{
  "sub": "b3d9142-b1bc-411a-813f-0b6534e793a8",
  "role": "customer",
  "iat": 1783072578,
  "exp": 1783072878
}
```

| Claim | Type | Meaning |
|-------|------|---------|
| `sub` | string (UUID) | User ID. Stable per-user. Do not use `username` for authorization decisions. |
| `role` | `"customer"` \| `"admin"` | Role at time of issue. Not refreshed on token expiry — banking receives whatever role was in effect at login/refresh. |
| `iat` | int | Issued-at, Unix seconds. |
| `exp` | int | Expiry, Unix seconds. Enforced by `verify_token` against real wall-clock time. |

Default TTL: **300 seconds** (5 minutes). Configurable via `AUTH_ACCESS_TTL_SECONDS`, minimum 60 seconds.

### Refresh token

**Not a JWT.** An opaque high-entropy string (32 bytes from `secrets.token_urlsafe`, URL-safe base64-encoded, ~43 characters).

- The auth service persists a SHA-256 hash of the token in the `refresh_tokens` table alongside `user_id` and `expires_at`.
- Presenting the token to `POST /refresh` looks it up by hash, verifies expiry, deletes the row (rotation), and issues a fresh access + refresh pair.
- **Reusing a rotated refresh token is rejected** — the row is gone. This does not currently trigger "reuse detected → invalidate all sessions" behaviour; see {{ src("03-auth-service/flow-refresh.md", text="../03-auth-service/flow-refresh.md") }}.

Default TTL: **86 400 seconds** (24 hours). Configurable via `AUTH_REFRESH_TTL_SECONDS`, minimum 3 600.

### Verification steps on the banking side (when built)

1. Fetch public key from `GET /public-key`. Cache it. Rotate cache on 401.
2. Call `shared_security.tokens.verify_token(bearer_token, public_key)`. This handles: signature check, algorithm pinning, `exp` check against wall clock. Any failure raises `TokenError`.
3. Read `sub` (user id) and `role` from the returned claims.
4. Enforce RBAC before any data access.

### What is *not* in the contract
- Wire format details of the refresh token (opacity is guaranteed, but exact character count is not).
- Whether refresh tokens contain any metadata (currently they do not).
- Internal audit event shapes (those are auth-internal, not read by banking).

---

## Changing a contract

If either contract must change:
1. Announce in a doc/PR/message to the other person.
2. Update this file.
3. Update the tests that pin the contract (contract-1 tests: {{ src("shared_security/tests/", text="shared_security/tests/") }}; contract-2 tests: {{ src("auth_service/tests/test_login.py", text="auth_service/tests/test_login.py") }}, {{ src("auth_service/tests/test_refresh.py") }}).
4. Update the consumer side.
5. Ship in one coordinated change, not two half-changes.
