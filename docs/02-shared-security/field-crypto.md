# Field encryption (AES-256-GCM)

Symmetric authenticated encryption for individual field values (account number, balance, card details). Not used by any implemented service yet — banking service will be the first consumer.

## API

```python
class DecryptionError(Exception): ...

def generate_field_key() -> bytes                        # 32 bytes
def encrypt_field(plaintext: bytes, key: bytes) -> bytes # nonce || ciphertext (with tag)
def decrypt_field(blob: bytes, key: bytes) -> bytes      # raises DecryptionError on tag mismatch
```

Implementation: {{ src("shared_security/src/shared_security/field_crypto.py") }}.

## Why AES-256-GCM and not another mode

- **Authenticated encryption** — GCM produces a MAC tag alongside the ciphertext. Any single-bit change to the ciphertext, nonce, or associated data causes `decrypt_field` to fail. This is what "tampered ciphertext fails to decrypt" means in {{ src("CLAUDE.md", text="../../CLAUDE.md") }}.
- **256-bit key** — 128-bit is fine cryptographically; 256-bit is the extra margin for a security-focused build. No practical performance hit on modern CPUs with AES-NI.
- **Widely available** — the `cryptography` library ships hardware-accelerated AES-GCM. No custom implementation.

## Blob format

```
| nonce (12 bytes) | ciphertext (variable) | tag (16 bytes, appended by GCM) |
```

The output of `encrypt_field` is a single `bytes` object concatenating these. Storing one column per encrypted field is the intended pattern — no separate nonce or tag columns.

- **Nonce size: 12 bytes** — the value GCM standardises to; anything else risks security proofs breaking. Constant `_NONCE_SIZE` in {{ src("shared_security/src/shared_security/field_crypto.py") }}.
- **Tag size: 16 bytes** — GCM default. Included at the end of the AESGCM.encrypt output automatically.

## Nonce discipline

**A single (key, nonce) pair must never be reused.** GCM is catastrophically broken if it is — an attacker can XOR two ciphertexts to recover plaintext, and can forge messages.

`encrypt_field` protects against reuse by drawing the nonce from `os.urandom(12)` every call. With a 96-bit random space, the birthday collision probability crosses ~2⁻³² after roughly 2⁴⁸ encryptions with the same key — comfortably outside any real workload for this service. Callers do not manage the nonce.

The rule that follows: **do not roll your own encrypt loop by reusing nonces from a counter.** Always call `encrypt_field` for each value. If a service ever encrypts under a hot key at extreme volume, rotate keys before the birthday bound approaches.

## What this defends against

- **Passive database read.** An attacker who reads the DB (dump, backup, replica leak) sees ciphertext they cannot decrypt without the key.
- **Tampered ciphertext.** Any modification — bit flips, truncation, appended bytes — fails the GCM tag check and raises `DecryptionError`. The test `test_tampered_ciphertext_fails` in {{ src("shared_security/tests/test_field_crypto.py") }} covers this.
- **Nonce collisions during normal operation.** Random 96-bit nonces at expected volumes.

## What this does *not* defend against

- **Compromised application memory.** If an attacker reads live process memory, the key is there. Encryption-at-rest is exactly what it says — rest, not runtime.
- **Deterministic key derivation.** There is no KDF or password-based key generation. The key is a raw 32-byte value. Callers do their own key management. `generate_field_key()` is the only helper.
- **Key rotation.** If a key is rotated, old ciphertexts stay encrypted under the old key and must be re-encrypted separately. Not automated.
- **Length side channel.** GCM does not hide plaintext length. If field values have very different sizes, ciphertext size reveals plaintext size. Usually not a concern for banking fields; document if it is.
- **Search over encrypted values.** GCM ciphertext is randomised (nonce), so identical plaintexts produce different ciphertexts. Equality queries on the encrypted column will not match. Banking service will need a deterministic index (e.g. HMAC(field)) if it needs to look up by encrypted value — that is a separate design decision.

## Tests that pin this behaviour

{{ src("shared_security/tests/test_field_crypto.py") }}:

- Round trip: `decrypt_field(encrypt_field(pt, key), key) == pt`.
- Wrong key raises `DecryptionError`.
- Tampering with any byte of the ciphertext (including the nonce prefix and tag suffix) raises `DecryptionError`.
- Two encryptions of the same plaintext produce different ciphertexts (nonce randomness).

## Usage sites in the current build

None — the primitive exists but no service consumes it. Banking service will encrypt on write and decrypt on read as the default path (per DEV_GUIDE, "not bolted on later").
