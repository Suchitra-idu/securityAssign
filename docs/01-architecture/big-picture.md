# The whole system, in diagrams

One page for the lazy reviewer. Every security control marked on a picture, with the code that implements it linked underneath. If this is the only page you read, you should still leave knowing what defends what, where every key lives, and how the request path is protected end to end.

Legend for every diagram on this page:

- **Solid arrow** — request / data flow.
- **Double arrow (==)** — encrypted transport (TLS).
- **Dotted arrow (-.-)** — configuration / trust relationship, not runtime traffic.
- **🔑** — key material owned by that box (private = the box can sign / decrypt; public = the box can only verify).
- **Yellow box** — key or crypto artefact. **Green box** — service. **Red box** — persistent storage. **Blue box** — network boundary.

---

## 1. Deployment topology — one page, everything

Every container, every network, every published or non-published port, every crypto choke point.

```mermaid
flowchart TB
  subgraph EXT["<b>Client side</b>"]
    Browser["Browser<br/>(single-page UI)"]
    Curl["curl / scripts"]
  end

  subgraph EDGE["<b>Docker network: edge</b> — only Caddy is published to the host"]
    Caddy["<b>Caddy 2.11</b> — xcaddy build<br/>─────────────<br/>• TLS 1.3 termination (auto cert on localhost)<br/>• <b>Coraza WAF</b> — OWASP CRS v4.16 (DetectionOnly)<br/>• <b>Rate limit</b> — 300 req / min / IP<br/>• <b>Static UI file_server</b> from /srv/ui (baked in image)<br/>• Router:<br/>&nbsp;&nbsp;/banking/* → banking (https)<br/>&nbsp;&nbsp;/register /login /refresh /public-key /health → auth (https)<br/>&nbsp;&nbsp;/* → file_server"]
  end

  subgraph INT["<b>Docker network: internal</b> — internal:true. No host route. No outbound internet."]

    subgraph AUTH["<b>auth_service</b> — FastAPI + uvicorn with self-signed TLS"]
      AuthRoutes["<b>Routes</b><br/>POST /register (customer role hardcoded)<br/>POST /login (bcrypt-verify + mint pair)<br/>POST /refresh (rotate refresh token)<br/>GET /public-key (Ed25519 PEM + alg)<br/>GET /health"]
      AuthCore["<b>Application layer</b><br/>register · login · refresh<br/>admin bootstrap on boot<br/><br/>every write route runs<br/>inside 'with deps.transaction():'<br/>(commit before response)"]
      AuthKeys["🔑 <b>Ed25519 PRIVATE</b> — signs JWTs<br/>🔑 <b>Ed25519 PUBLIC</b> — served on /public-key"]
    end

    subgraph BANK["<b>banking_service</b> — FastAPI + uvicorn with self-signed TLS"]
      BankRoutes["<b>Routes</b><br/>POST /accounts (customer or admin)<br/>GET /accounts/me · GET /accounts/{id}<br/>GET /accounts (admin only)<br/>POST /accounts/{id}/freeze (admin)<br/>POST /accounts/{id}/unfreeze (admin)<br/>POST /transfers · GET /transactions/{id}<br/>GET /health"]
      BankVerify["<b>Token verifier (FastAPI dep)</b><br/>bearer_caller: extracts JWT,<br/>verify_token(auth_pubkey),<br/>checks role ∈ {customer, admin},<br/>returns Caller(user_id, role) or 401"]
      BankCore["<b>Application layer</b><br/>open · read · list · transfer<br/>freeze · unfreeze · list_transactions<br/><br/>RBAC choke point:<br/>require_admin /<br/>require_owner_or_admin<br/>runs before any state read/write"]
      BankKeys["🔑 <b>Auth PUBLIC key</b> (verify JWTs — cannot mint)<br/>🔑 <b>Ed25519 TX PRIVATE</b> (signs transfers)<br/>🔑 <b>AES-256-GCM 32-byte field key</b>"]
    end

    subgraph PG["<b>Postgres 16</b> — custom image with baked dev CA + server cert"]
      PGSec["<b>Server-side lockdown</b><br/>pg_hba.conf: <b>hostssl-only</b><br/>(plaintext connections rejected<br/>before password auth)"]
      DBA[("<b>DB: auth</b><br/>users (bcrypt hash, role ∈ {customer, admin})<br/>refresh_tokens (SHA-256 of token, never raw)<br/>audit_log (JSONB + prev_hash + hash)")]
      DBB[("<b>DB: banking</b><br/>accounts — id, owner_id plaintext;<br/>account_number, balance_minor, card_number = <b>AES-256-GCM BYTEA</b><br/>transactions (BYTEA Ed25519 signature)<br/>audit_log (JSONB + prev_hash + hash)")]
    end

    subgraph BKUP["<b>backup sidecar</b>"]
      BK["Loop every BACKUP_INTERVAL_SECONDS:<br/>pg_dump piped through age -r &lt;pubkey&gt;<br/>writes /backups/*.sql.age<br/>Retention: keep newest N per DB, prune older.<br/>Plaintext SQL never touches disk."]
      BV[("named volume<br/><b>backup_data</b><br/>*.sql.age ciphertext")]
    end
  end

  subgraph HOST["<b>Host</b> (outside Docker)"]
    F2B["<b>fail2ban</b> jail<br/>tails auth container stdout for:<br/>LOGIN_FAILED ip=… · REFRESH_FAILED ip=…<br/>ban decision via iptables"]
  end

  Browser  == "HTTPS · TLS 1.3" ==> Caddy
  Curl -. "HTTPS · TLS 1.3" .-> Caddy
  Caddy == "HTTPS · self-signed" ==> AuthRoutes
  Caddy == "HTTPS · self-signed" ==> BankRoutes

  AuthRoutes --> AuthCore
  AuthCore -.- AuthKeys
  AuthCore == "psycopg3 pool · TLS 1.3 · sslmode=verify-ca" ==> DBA

  BankRoutes --> BankVerify --> BankCore
  BankCore -.- BankKeys
  BankVerify -.- BankKeys
  BankCore == "psycopg3 pool · TLS 1.3 · sslmode=verify-ca" ==> DBB

  BankVerify -. "auth pubkey injected at config load<br/>(BANKING_AUTH_PUBLIC_KEY_PEM / _PATH)" .-> AuthKeys

  BK == "TLS · verify-ca" ==> DBA
  BK == "TLS · verify-ca" ==> DBB
  BK --> BV

  F2B -. "tails stdout" .-> AuthRoutes

  classDef net fill:#eef,stroke:#33a,stroke-width:2px,color:#000
  classDef svc fill:#efe,stroke:#3a3,stroke-width:1.5px,color:#000
  classDef db  fill:#fee,stroke:#a33,stroke-width:1.5px,color:#000
  classDef key fill:#ffd,stroke:#a80,stroke-width:1.5px,color:#000
  classDef ids fill:#fdf,stroke:#a3a,stroke-width:1.5px,color:#000

  class EDGE,INT net
  class AUTH,BANK,BKUP svc
  class PG db
  class HOST ids
  class AuthKeys,BankKeys key
```

**What this picture proves.** Every arrow crossing a network boundary is encrypted. Only Caddy has a published port. Postgres refuses plaintext at the pg_hba layer, so a mis-configured container cannot accidentally connect insecurely. Backups leave the DB via TLS, become ciphertext before hitting disk. Auth is the only container with the JWT signing key; every other service can only verify.

---

## 2. Trust boundaries — who holds what key, who can do what

The interesting cryptographic property is *asymmetric trust*. Banking cannot forge tokens. Postgres cannot forge signed transfers. A stolen DB dump cannot read account numbers.

```mermaid
flowchart LR
  subgraph AUTH2["<b>auth_service</b>"]
    K1[["🔑 Ed25519 signing PRIVATE"]]
    K2[["🔑 Ed25519 signing PUBLIC"]]
  end
  subgraph BANK2["<b>banking_service</b>"]
    K3[["🔑 Auth PUBLIC (copy)"]]
    K4[["🔑 TX signing PRIVATE"]]
    K5[["🔑 TX signing PUBLIC"]]
    K6[["🔑 AES-256-GCM field key (32 B)"]]
  end
  subgraph PG2["<b>Postgres</b>"]
    D1["Sees only:<br/>• bcrypt hashes<br/>• SHA-256 refresh-token hashes<br/>• AES-256-GCM ciphertext for<br/>&nbsp;&nbsp;3 account columns<br/>• Ed25519 signature bytes<br/>• audit-chain hashes"]
  end
  subgraph BK2["<b>backup</b>"]
    KB[["🔑 age recipient (public)"]]
    KBP[["🔑 age identity (PRIVATE)<br/>kept off-box for restore"]]
  end

  K1 -. "sign JWT" .-> K3
  K3 -. "verify JWT" .-> K5
  K4 -. "sign transfer" .-> K5
  K5 -. "verify transfer at read time" .-> D1
  K6 -. "encrypt/decrypt<br/>3 account columns" .-> D1
  KB -. "encrypt backup" .-> KBP

  classDef svc fill:#efe,stroke:#3a3
  classDef key fill:#ffd,stroke:#a80
  classDef db  fill:#fee,stroke:#a33
  class AUTH2,BANK2,BK2 svc
  class PG2 db
  class K1,K2,K3,K4,K5,K6,KB,KBP key
```

Table form for the same picture — the "who can do what" matrix:

| Actor | Can mint JWTs | Can verify JWTs | Can sign transfers | Can verify transfers | Can decrypt account fields | Can decrypt a backup |
|-------|---------------|-----------------|--------------------|----------------------|----------------------------|----------------------|
| auth_service | ✅ has private key | ✅ | ❌ | ❌ | ❌ | ❌ |
| banking_service | ❌ | ✅ has public key only | ✅ has private key | ✅ | ✅ has field key | ❌ |
| Postgres | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Attacker with DB dump | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Attacker with backup file | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ (needs age identity) |

**Consequence:** compromising Postgres alone doesn't get you cleartext accounts, valid tokens, or valid transactions. You need the running banking container's memory to get the field key and the TX private key.

---

## 3. What a request actually does — login (the auth path)

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant C as Caddy<br/>(TLS 1.3, WAF, rate-limit)
    participant A as auth_service<br/>FastAPI + uvicorn TLS
    participant DA as auth DB
    participant Aud as audit_log<br/>(autocommit conn)

    B->>C: POST /login (JSON body) — TLS 1.3
    Note right of C: Coraza CRS runs<br/>SQLi/XSS rules on body<br/>rate_limit check
    C->>A: HTTPS (self-signed)
    A->>A: Pydantic validates<br/>(extra="forbid")
    A->>DA: SELECT user WHERE username=...
    DA-->>A: user + bcrypt hash
    A->>A: shared_security.passwords.verify_password(pw, hash)<br/>(constant-time compare inside bcrypt)
    alt Wrong password
      A->>Aud: emit("login_failed", username, at)<br/>(own txn on autocommit conn: LOCK + chain + INSERT + COMMIT)
      A-->>B: 401 "invalid credentials"
      Note over B: LOGIN_FAILED ip=... logged.<br/>fail2ban tails this line.
    else Correct password
      A->>A: shared_security.tokens.sign_token(claims, PRIVATE)<br/>+ secrets.token_urlsafe(32)<br/>+ SHA-256(refresh)
      A->>DA: INSERT refresh_tokens (hash, user_id, expires_at)
      A->>Aud: emit("login_success", user_id, at)
      A-->>B: 200 { access_token, refresh_token }
    end
```

**Security payload of this diagram, top to bottom:**

- **Step 1**: TLS 1.3 in the browser lock icon — no plaintext at any point.
- **Step 2**: OWASP CRS inspects the body before FastAPI sees it.
- **Step 3**: uvicorn on the service listens on HTTPS with its own cert; Caddy dials it over TLS.
- **Step 4**: Pydantic's `extra="forbid"` means a client cannot smuggle `{"role":"admin"}` into `/register`. See [../03-auth-service/input-validation.md](../03-auth-service/input-validation.md).
- **Step 6**: bcrypt at cost factor 12; even a DB dump doesn't yield cleartext passwords.
- **Failure branch**: the audit event lands on a **separate autocommit connection** so it survives the request rollback. This is the "two-connection audit durability" pattern. See [../03-auth-service/audit-log-durability.md](../03-auth-service/audit-log-durability.md).
- **Success branch**: raw refresh token leaves once; the DB sees only SHA-256(token). A refresh-token DB leak yields nothing usable.

---

## 4. What a request actually does — transfer (the banking path)

The most crypto-dense flow. Signature, field encryption, RBAC, audit — all in one call.

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant C as Caddy<br/>(TLS 1.3, WAF, rate-limit)
    participant K as banking_service<br/>FastAPI + uvicorn TLS
    participant V as bearer_caller<br/>(FastAPI dep)
    participant U as transfer use case
    participant DB as banking DB
    participant Aud as audit_log<br/>(autocommit conn)

    B->>C: POST /banking/transfers (Bearer JWT) — TLS 1.3
    Note right of C: WAF inspects body<br/>rate_limit check
    C->>K: HTTPS (self-signed), path rewritten to /transfers
    K->>V: extract Authorization header
    V->>V: shared_security.tokens.verify_token(jwt, auth_pubkey)<br/>bad sig / expired / missing → 401
    V->>V: assert role ∈ {customer, admin}, sub is str
    V-->>K: Caller(user_id, role)
    K->>K: Pydantic TransferRequest<br/>(from_account_id, to_account_number, amount_minor)<br/>extra="forbid"
    K->>U: transfer(from_id, to_number, amount, caller, deps)

    U->>DB: SELECT source WHERE id = from_id<br/>(psycopg catches InvalidTextRepresentation → None → 404)
    DB-->>U: encrypted row → decrypt_field × 3 → Account plaintext
    U->>DB: SELECT * FROM accounts (scan)
    DB-->>U: rows → decrypt each → filter by account_number
    U->>U: assert amount positive · assert source.id ≠ destination.id<br/>assert admin OR source.owner_id == caller.user_id<br/>assert both accounts active

    alt Insufficient funds
      U->>Aud: emit("transfer_rejected", actor, from, reason)<br/>(own txn on autocommit conn)
      U-->>B: 409 "insufficient funds"
      Note over B: Audit event lands even though<br/>main txn rolls back.
    else Accepted
      U->>U: sign_transaction(payload, TX_PRIVATE)<br/>Ed25519 over canonical JSON
      U->>DB: UPDATE source (encrypt_field × 3, new balance)
      U->>DB: UPDATE destination (encrypt_field × 3, new balance)
      U->>DB: INSERT transaction (signature BYTEA)
      U->>Aud: emit("transfer", actor, tx_id, from, to, amount)
      U-->>B: 201 TransactionResponse(signature_valid=true)
    end
```

**On a later read** (`GET /transactions/{account_id}`) every row is re-verified with `verify_transaction(payload, signature, TX_PUBLIC)` and returned with `signature_valid: bool`. If the DB was tampered directly (`UPDATE transactions SET amount_minor=999`), the flag flips to `false` on the very next read — the tamper is *visible*, not hidden.

Full flow with rules-in-order: [../07-banking-service/flow-transfer.md](../07-banking-service/flow-transfer.md).

---

## 5. Storage layout — what's plaintext, what's ciphertext, what's hashed

The single most-asked reviewer question is "what would an attacker with the DB see". This diagram answers it.

```mermaid
flowchart TB
  subgraph AUTHDB["<b>DB: auth</b>"]
    U["<b>users</b><br/>id UUID (plaintext)<br/>username TEXT (plaintext)<br/>password_hash TEXT — <b>bcrypt</b> (irreversible)<br/>role TEXT ∈ {customer, admin}"]
    R["<b>refresh_tokens</b><br/>token_hash TEXT — <b>SHA-256 of raw token</b><br/>user_id UUID · expires_at BIGINT<br/>raw token <b>never stored</b>"]
    LA["<b>audit_log</b><br/>event JSONB (plaintext)<br/>prev_hash BYTEA · hash BYTEA — <b>SHA-256 chain</b>"]
  end
  subgraph BANKDB["<b>DB: banking</b>"]
    AC["<b>accounts</b><br/>id UUID (plaintext) · owner_id UUID (plaintext, indexed)<br/>account_number BYTEA — <b>AES-256-GCM ciphertext</b><br/>balance_minor BYTEA — <b>AES-256-GCM ciphertext</b><br/>card_number BYTEA — <b>AES-256-GCM ciphertext</b><br/>status TEXT ∈ {active, frozen}"]
    T["<b>transactions</b><br/>id UUID · from/to UUID · amount_minor BIGINT<br/>signed_at BIGINT · signature BYTEA — <b>Ed25519</b>"]
    LB["<b>audit_log</b><br/>event JSONB (plaintext)<br/>prev_hash BYTEA · hash BYTEA — <b>SHA-256 chain</b>"]
  end

  classDef db fill:#fee,stroke:#a33,color:#000
  class AUTHDB,BANKDB db
```

**What the DB dump gives an attacker, per column:**

| Column | Format | What the attacker gets |
|--------|--------|------------------------|
| `users.password_hash` | bcrypt (cost 12) | Nothing usable — must brute-force per user |
| `refresh_tokens.token_hash` | SHA-256 | Nothing — raw token never stored |
| `accounts.account_number` | AES-256-GCM ciphertext | Nothing — needs the field key |
| `accounts.balance_minor` | AES-256-GCM ciphertext of `str(int)` | Nothing — same key |
| `accounts.card_number` | AES-256-GCM ciphertext | Nothing — same key |
| `accounts.owner_id` | UUID plaintext | Which auth user owns which internal account id (opaque UUID pair). Documented trade-off — foreign-key filtering vs full opacity. |
| `transactions.amount_minor` | Plaintext | Visible, but tampering flips `signature_valid` to `false` on next read. |
| `transactions.signature` | 64 bytes | Nothing without the TX private key. |
| `audit_log.event` | Plaintext JSONB | Timeline of who did what. Tampering breaks the SHA-256 chain. |
| `audit_log.hash` | 32 bytes | The chain tip. Verifiable with `verify_chain`. |

**Encryption at rest is column-level, not disk-level.** A `docker exec postgres cat /var/lib/postgresql/data/base/…` would still yield ciphertext for the encrypted columns. Disk-level encryption is a separate concern (host FS, not app-layer).

---

## 6. The audit chain — why tampering is visible

Both `auth.audit_log` and `banking.audit_log` are hash-chained. Same primitive, two independent tables.

```mermaid
flowchart LR
  G[["<b>GENESIS_HASH</b><br/>constant 32 bytes"]]
  E1["event_1<br/>{register, at, ...}"]
  E2["event_2<br/>{login_success, at, ...}"]
  E3["event_3<br/>{transfer_rejected, at, ...}"]
  E4["event_n<br/>..."]

  H1["hash_1 = SHA-256(GENESIS ‖ canonical(event_1))"]
  H2["hash_2 = SHA-256(hash_1 ‖ canonical(event_2))"]
  H3["hash_3 = SHA-256(hash_2 ‖ canonical(event_3))"]
  H4["hash_n = SHA-256(hash_{n-1} ‖ canonical(event_n))"]

  G --> H1
  E1 --> H1
  H1 --> H2
  E2 --> H2
  H2 --> H3
  E3 --> H3
  H3 --> H4
  E4 --> H4

  classDef box fill:#eef,stroke:#33a,color:#000
  classDef hash fill:#ffd,stroke:#a80,color:#000
  classDef genesis fill:#fdf,stroke:#a3a,color:#000
  class E1,E2,E3,E4 box
  class H1,H2,H3,H4 hash
  class G genesis
```

**Two subtle mechanics protect this against races and rollbacks:**

- **Writes go through a separate autocommit connection.** The main request transaction can roll back (failed login, insufficient funds); the audit event is already committed. See [../03-auth-service/audit-log-durability.md](../03-auth-service/audit-log-durability.md).
- **`LOCK TABLE audit_log IN SHARE ROW EXCLUSIVE MODE`** at the start of every write. Two concurrent writers cannot interleave `SELECT last hash → compute → INSERT` and fork the chain.

**Detection.** `shared_security.audit_chain.verify_chain(rows)` recomputes every hash from the first event forward. Any mismatch → `False`. Demonstrable live by editing a random row's `event` column and running the check.

---

## 7. What each assignment security point maps to on these diagrams

The lazy-reviewer cheat sheet. Every graded control, where it appears, tested by what.

| # | Control | Where on the diagrams | Code | Test |
|---|---------|-----------------------|------|------|
| 1 | TLS 1.3 client→proxy | §1 · Browser ⇒ Caddy | {{ src("proxy/caddy/Caddyfile") }} | manual browser lock icon |
| 2 | Network isolation | §1 · <code>internal: true</code> label | {{ src("deploy/compose/docker-compose.yml") }} | `docker network inspect` |
| 3 | WAF | §1 · Caddy box | {{ src("proxy/coraza/coraza.conf") }} | SQLi curl → CRS log |
| 4 | HTTPS proxy→services | §1 · Caddy == HTTPS ==> auth/banking | {{ src("auth_service/Dockerfile") }} + Caddy `tls_insecure_skip_verify` | smoke |
| 5 | Password hashing | §5 · users.password_hash column | {{ src("shared_security/src/shared_security/passwords.py") }} | {{ src("auth_service/tests/test_login.py") }} |
| 5 | Token signing | §2 · Ed25519 private key in auth only | {{ src("shared_security/src/shared_security/tokens.py") }} | {{ src("shared_security/tests/test_tokens.py") }} |
| 6 | RBAC customer vs admin | §1 · BankCore box · authz choke point | {{ src("banking_service/src/banking_service/application/authz.py") }} | {{ src("banking_service/tests/test_freeze_account.py") }} etc. |
| 7 | Token verify + field enc + tx sign | §4 · full transfer sequence | {{ src("banking_service/src/banking_service/application/transfer.py") }} | {{ src("banking_service/tests/test_transfer.py") }} |
| 8 | TLS services→DB | §1 · psycopg pool ==> Postgres | pg_hba + service `sslmode=verify-ca` | `SELECT * FROM pg_stat_ssl` |
| 9 | Encryption at rest for sensitive fields | §5 · accounts BYTEA columns | {{ src("banking_service/src/banking_service/infrastructure/repositories/accounts_repo.py") }} | {{ src("banking_service/tests/test_integration_postgres.py", text="test_sensitive_fields_are_ciphertext_on_disk") }} |
| 10 | Hash-chained audit log | §6 · SHA-256 chain diagram | {{ src("shared_security/src/shared_security/audit_chain.py") }} | {{ src("banking_service/tests/test_integration_postgres.py", text="test_audit_chain_valid_end_to_end") }} |
| 11 | Encrypted backups | §1 · backup sidecar | {{ src("deploy/backup/") }} | manual restore drill |
| 12 | fail2ban IDS | §1 · Host box | {{ src("deploy/fail2ban/") }} | log-line format locked in auth `_client_ip` |

---

## 8. Quick tour for a five-minute skim

If you only have five minutes:

1. Look at diagram §1 — see that only Caddy talks to the outside, and every crossing arrow is encrypted.
2. Look at the trust matrix in §2 — no single container holds every key. Compromising any one gets you a bounded blast radius.
3. Look at the storage layout in §5 — the DB alone reveals nothing sensitive that isn't hashed, encrypted, or signature-protected.
4. Look at the transfer sequence in §4 — see the RBAC check, field-encryption boundary, signature, and audit event all appear in a single call.
5. Look at the audit chain in §6 — every state change is retrospective-evidence-preserving.

If you have another minute, click any {{ src("shared_security/src/shared_security/") }} link — that's the crypto boundary the two services share, tested first (per CLAUDE.md's "test-first on security-critical code").
