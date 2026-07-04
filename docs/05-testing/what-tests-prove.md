# What each test proves

Every test in this repo picks one security property and asserts it. This page walks each test file, one line per test, so you can find the test that pins a specific claim you want to make in the report.

## `shared_security/tests/`

### {{ src("shared_security/tests/test_passwords.py") }}
- **round trip verifies** — `verify_password(pw, hash_password(pw)) is True`. Bcrypt actually works.
- **wrong password fails** — verifying a different password against the stored hash returns `False`.
- **two hashes differ** — hashing the same password twice produces different hashes. Salt is random and used.
- **malformed hash returns False** — a corrupted or truncated hash string does not crash; `verify_password` returns `False`.

### {{ src("shared_security/tests/test_tokens.py") }}
- **round trip preserves claims** — `verify_token(sign_token(claims, priv), pub)` returns the same `sub`, `role`, `exp`.
- **forged token fails** — a token signed by an attacker's private key fails verification with our public key. Signature is what pins identity.
- **tampered payload fails** — flipping bytes in the signature segment fails. Any bit-flip is detected.
- **expired token fails** — `exp` in the past raises `TokenError`. Wall-clock expiry is enforced.
- **algorithm confusion HS256 rejected** — a hand-crafted HS256 token signed with the public key as an HMAC secret is rejected. The verifier pins `algorithms=["EdDSA"]` so the token's `alg` header is not trusted. The test hand-builds the forgery with base64+HMAC because PyJWT's own encode-side check refuses this shape.

### {{ src("shared_security/tests/test_field_crypto.py") }}
- **round trip returns original plaintext** — `decrypt(encrypt(pt))` == pt.
- **wrong key raises DecryptionError** — decrypting with a different key fails.
- **tampered ciphertext raises DecryptionError** — flipping any byte, including in the nonce prefix or auth tag, fails.
- **two encryptions differ** — encrypting the same plaintext twice produces different ciphertexts. Nonce is fresh and random.

### {{ src("shared_security/tests/test_transaction_signatures.py") }}
- **round trip verifies** — `verify_transaction(tx, sign_transaction(tx, priv), pub) is True`.
- **wrong key fails** — attacker-signed tx does not verify.
- **mutated tx fails** — changing any field of `tx` after signing fails.
- **truncated signature fails** — signature bytes must be intact.
- **insertion order doesn't matter** — `{"a":1,"b":2}` and `{"b":2,"a":1}` produce identical signatures because canonicalisation sorts keys.

### {{ src("shared_security/tests/test_audit_chain.py") }}
- **empty chain verifies** — the trivial case works.
- **correct chain verifies** — a well-built chain of several records passes `verify_chain`.
- **tampered record fails** — modifying any record byte fails verification.
- **tampered stored hash fails** — modifying any stored hash byte fails verification.
- **genesis linkage is checked** — the first record's `prev_hash` must equal `GENESIS_HASH`.

## `auth_service/tests/`

### {{ src("auth_service/tests/test_register.py") }}
- **stores hashed password not plaintext** — the plaintext never appears in the stored `User.password_hash`. `verify_password` against the stored hash succeeds.
- **records role verbatim** — role parameter propagates to the stored user.
- **assigns stable user id** — two registers produce different, non-empty ids.
- **rejects duplicate username** — a second register with the same username raises `UsernameTaken`.
- **writes audit event** — exactly one `event="register"` audit event with the new user's id, username, and timestamp.
- **audit event never carries password** — plaintext password does not appear in any audit event field.

### {{ src("auth_service/tests/test_login.py") }}
- **success returns verifiable access token with role claim** — the returned access token, verified with the public key, contains `sub` = user id, `role` = user role, `iat` = now, `exp` = now + `access_ttl`.
- **success carries admin role** — admin users get `role: "admin"` in the token.
- **wrong password rejected, no refresh token stored** — `InvalidCredentials` is raised and `refresh_tokens` remains empty. Session state is only created on success.
- **unknown user rejected** — same error class as wrong password. No refresh token stored.
- **refresh token is opaque and not stored plaintext** — the returned refresh token is not a JWT (no dots), is ≥32 chars, and the refresh store does not contain the raw value (only the hash).
- **stored refresh record expires in future** — the persisted `RefreshRecord.expires_at` is `now + refresh_ttl`.
- **success writes audit event** — `event="login_success"` with `user_id` and `at`.
- **failure writes audit event without leaking password** — `event="login_failed"` fires, plaintext password does not appear.
- **failure for unknown user still audited** — even without a user id, the audit event records the attempted username.

### {{ src("auth_service/tests/test_refresh.py") }}
- **rotates and issues new pair** — new access and refresh tokens differ from the old ones. Store contains exactly one row (the new one).
- **old token rejected after rotation** — presenting the pre-rotation token raises `InvalidRefreshToken`.
- **expired token rejected** — after advancing the fake clock past `refresh_ttl`, refresh raises.
- **unknown token rejected** — arbitrary string raises.
- **preserves subject and role** — refresh's new access token has the same `sub` and `role` as the pre-refresh user. Role is stable across rotations.
- **success writes audit event** — `event="refresh_success"` with user id.
- **failure writes audit event** — `event="refresh_failed"` on unknown token.
- **reused token never leaks new pair** — after rotation, presenting the old token does not add anything to the store.

### {{ src("auth_service/tests/test_integration.py") }} — full HTTP layer
- **register returns 201 with customer role** — response body shape.
- **register duplicate returns 409** — HTTP mapping of `UsernameTaken`.
- **register rejects short password** — 422 from Pydantic before use case runs.
- **register rejects bad username** — 422 from the regex validator on a SQL-fragment input.
- **register forbids role field from request** — `extra="forbid"` rejects `{"role":"admin"}` with 422. Client cannot smuggle a role.
- **login returns tokens** — 200 with `access_token`, `refresh_token`, `token_type: "Bearer"`. Access token verifies against the configured public key and carries `role: "customer"`.
- **login wrong password returns 401** — HTTP mapping of `InvalidCredentials`.
- **refresh rotates tokens** — 200 with new pair, both distinct from the old pair.
- **refresh old token after rotation returns 401** — HTTP mapping of `InvalidRefreshToken`.
- **public-key endpoint returns PEM** — 200 with configured public key and `algorithm: "EdDSA"`.
- **health endpoint** — 200 `{"status":"ok"}`.

## Cross-referenced from the security controls map

If you want to jump directly from a security point (see {{ src("01-architecture/security-controls.md", text="../01-architecture/security-controls.md") }}) to the tests that prove it:

- **Password hashing** → `test_passwords.py` + register/login tests.
- **Token signing** → all of `test_tokens.py` + the login/refresh tests that assert on returned claim shape.
- **Algorithm confusion defence** → `test_algorithm_confusion_hs256_rejected`.
- **Role in token** → `test_login_success_returns_verifiable_access_token_with_role`, `test_refresh_preserves_subject_and_role`.
- **Role smuggling defence** → `test_register_forbids_role_field_from_request`.
- **Hash-chained audit log** → `test_audit_chain.py` (primitive) + login/refresh tests that assert audit events on success and failure.
- **Refresh rotation** → `test_refresh_rotates_and_issues_new_pair`, `test_refresh_old_token_rejected_after_rotation`.
- **Failed events still audited** → `test_login_failure_writes_audit_event_without_leaking_password`, `test_refresh_failure_writes_audit_event`.
