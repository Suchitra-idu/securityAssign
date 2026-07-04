# Contract: Crypto function boundary

**Owner**: Person A (shared_security).
**Consumers**: auth service (built), banking service (planned).

Public API of the `shared_security` package. Consumers depend only on the names, signatures, and behavior listed here. Internal implementation may change.

Full explanation lives in the docs — see [docs/01-architecture/contracts.md](../docs/01-architecture/contracts.md#contract-1-crypto-function-boundary). This file is the short pinned reference so both people can find it at a glance.

---

## `shared_security.passwords`

```python
def hash_password(password: str) -> str
def verify_password(password: str, hashed: str) -> bool
```

- Hash strings start with `$2b$` (bcrypt).
- `verify_password` returns `False` on mismatch OR malformed hash. **Does not raise.**

## `shared_security.tokens`

```python
ALGORITHM = "EdDSA"

class TokenError(Exception): ...

def generate_signing_keypair() -> tuple[str, str]      # (private_pem, public_pem)
def sign_token(claims: dict, private_key: str) -> str  # returns compact JWT
def verify_token(token: str, public_key: str) -> dict  # returns claims, raises TokenError on any failure
```

- Keys are PEM-encoded `str`.
- `verify_token` **raises** `TokenError` on: bad signature, expired, wrong algorithm, malformed. Never returns `None`.
- Algorithm pinned to `EdDSA`. Token `alg` header is not trusted.

## `shared_security.field_crypto`

```python
class DecryptionError(Exception): ...

def generate_field_key() -> bytes                       # 32 bytes
def encrypt_field(plaintext: bytes, key: bytes) -> bytes  # nonce || ciphertext || tag
def decrypt_field(blob: bytes, key: bytes) -> bytes     # raises DecryptionError on tag mismatch
```

- Blob format: **12-byte random nonce prepended** to AES-256-GCM ciphertext (which includes the 16-byte tag).
- Callers do not manage the nonce. Each `encrypt_field` call draws fresh randomness from `os.urandom`.

## `shared_security.transaction_signatures`

```python
def sign_transaction(tx: dict, private_key: str) -> bytes
def verify_transaction(tx: dict, signature: bytes, public_key: str) -> bool
```

- Signature computed over `canonical_json_bytes(tx)` — see below.
- `verify_transaction` returns `False` on mismatch. **Does not raise.**

## `shared_security.audit_chain`

```python
GENESIS_HASH: bytes = bytes(32)  # 32 zero bytes

def compute_chain_hash(previous_hash: bytes, record: bytes) -> bytes  # SHA-256
def verify_chain(chain: list[tuple[bytes, bytes]]) -> bool
```

- `chain` is `[(record, stored_hash), ...]` in insertion order.
- `verify_chain` returns `False` if any stored hash does not equal `SHA256(previous_hash || record)`.

## `shared_security.canonical`

```python
def canonical_json_bytes(payload: dict) -> bytes
```

- Deterministic: `sort_keys=True`, no whitespace between separators, UTF-8. Same dict → same bytes.
- Used by transaction signatures and the audit hash chain.

---

## What is *not* in this contract

- Internal helpers (`_name`).
- Internal module structure.
- Choice of underlying library (bcrypt version, PyJWT, cryptography). These may change if all guarantees above hold.
- Concrete key formats beyond "PEM string".

---

## Changing this contract

1. Announce.
2. Update this file.
3. Update the tests that pin the contract — see [shared_security/tests/](../shared_security/tests/).
4. Update every consumer.
5. Ship in one coordinated change.
