# DEV_GUIDE

Working reference for the secure banking application. This exists to make development easy, not for submission. Everything here is flexible and expected to change as we learn. If something below stops making sense mid build, we change it and update this doc.

---

## What we are building

A secure banking application. Customers log in, view their own accounts and balances, and make transfers. Admins manage accounts. The point of the project is to demonstrate real security mechanisms at algorithm, protocol, and system level, so the security controls matter more than feature breadth.

Keep the feature set small on purpose. Every extra feature is time taken away from doing the security parts properly.

---

## Current stack (flexible)

- Backend services in FastAPI
- PostgreSQL for data and the audit log
- Caddy as reverse proxy with automatic TLS, Coraza as the WAF
- Docker Compose to run everything and to give us network isolation
- fail2ban as the host level IDS
- Password hashing with bcrypt (chosen because it is what we learned, well understood, adaptive work factor, built in salt. We note in the report that Argon2id is the newer OWASP first choice and that bcrypt was a deliberate pick.)

Any of this can change if it fights us. If we swap something, update this section so the other person is not surprised.

---

## Architecture approach, light clean architecture

We follow clean architecture in spirit, not dogma. The goal is code that is easy to read, easy to test, and where the security logic does not get tangled into web framework details. We are not wrapping everything in ports and adapters. We are keeping three clear layers inside each service and pointing dependencies inward.

### The three layers

**Domain layer**
The core of the service. Business rules and the concepts the system is about, for example what a user is, what an account is, what makes a transaction valid. This layer knows nothing about FastAPI, nothing about Postgres, nothing about HTTP. If you deleted the web framework tomorrow, this layer would not change. Pure logic and pure data shapes live here.

**Application layer**
The use cases. This is where the actual operations live, for example register a user, log a user in, make a transfer, read an account. The application layer orchestrates the domain and calls out to whatever it needs (the database, the crypto helpers) through simple interfaces. It decides the sequence of steps for each operation. It does not know how the database is implemented and it does not know it is being called from a web request.

**Infrastructure layer**
The outside world. FastAPI routes, the Postgres access code, config loading, and the glue that wires everything together. This layer depends on the two inner layers, never the reverse. When a request comes in, the route handler in this layer translates it into a call to an application use case and translates the result back into a response.

### The dependency rule

Dependencies point inward only. Infrastructure can depend on application, application can depend on domain, domain depends on nothing. Crypto helpers are called from the application layer through a thin boundary so the use cases stay readable and testable without spinning up real keys.

Practically, this means the interesting logic can be unit tested with no web server and no real database, which is also useful evidence for the report and the viva.

### Why light and not strict

Strict clean architecture would have us wrap every external dependency in a formal port and adapter. For a 14 day build that is a lot of indirection for little gain. The light version gives us the readability and testability benefits without slowing the build. If a specific spot genuinely benefits from a formal interface, for example swapping the crypto backend, we add one there, not everywhere.

---

## Testing approach, TDD on the core

We use test driven development where it earns its place, which is the security critical logic, and lighter testing on the plumbing.

Test first, for the code where a wrong answer is a vulnerability:
- The shared security module. Every primitive gets a test written before the implementation. A forged token fails verification, tampered ciphertext fails to decrypt, a wrong password does not verify, a broken hash chain is detectable, a round trip returns the original.
- The authorization checks. A customer cannot reach another customer's account, a customer cannot perform an admin only action, a request with no valid token is rejected.

These tests are worth writing first because they force us to state the security property before building it, and they double as evidence for the report and viva. Showing the test that proves a forged token is rejected is stronger than claiming it.

Lighter testing, not test first, for the plumbing:
- FastAPI route wiring, Postgres access code, Docker and Caddy config. Writing tests first here mostly tests the framework rather than our own logic, and on a 14 day timeline that time is better spent on integration. We cover these with a few integration checks once wired, not test first.

The honest tradeoff. TDD is slower up front and pays back in fewer bugs and safer refactors. On a no buffer deadline we spend that up front cost only where the payback is real, the security logic, and not everywhere.

---

## The four codebases

One git repo, folders per service, plus a shared module and the proxy config. This keeps ownership clean while letting us share the security code so it does not drift into two versions.

### 1. Shared security module

The foundation. Both services use it. This is where all the cryptography and security primitives live so there is exactly one implementation of each.

Responsibilities:
- Password hashing and verification (bcrypt)
- Token signing and verification. Signing is asymmetric, the auth service holds the private key, the banking service holds only the public key and can verify but never mint tokens. When verifying, the algorithm is pinned explicitly and the token header is never trusted to choose it.
- Field encryption and decryption with AES 256 GCM, authenticated encryption so tampered data fails to decrypt, fresh random nonce every time
- Digital signatures for transactions, signing over the transaction details so a transaction cannot be denied later or altered undetected
- The hash chain helper for the audit log, each record carries the SHA 256 of the previous one so any tampering breaks the chain

This module is built test first, and Person A owns both the code and the tests. Round trips work, forged tokens fail, tampered ciphertext fails, a broken chain is detectable. Build and test this before the services depend on it.

The tests here do double duty. They are also the readable specification of the crypto boundary that Person B builds against. Person B reads these tests to understand exactly how each function behaves, but does not write them. This keeps the split clean, one owner for the module, while giving Person B a precise contract rather than guessing at behavior.

### 2. Auth service

FastAPI service. Owns identity and tokens. Holds the private signing key.

Responsibilities:
- Register, storing users with hashed passwords
- Login, verifying the password and issuing a signed short lived access token plus a refresh token
- Refresh, rotating the refresh token and checking the stored hash of it
- Exposing the public key so the banking service can verify tokens
- Putting role information into the token so the banking service can enforce access control
- Validating all input at the edge
- Writing every auth event to the audit log

Follows the three layers above. The login rule and token rules live in domain and application, FastAPI and Postgres live in infrastructure.

### 3. Banking service

FastAPI service. Owns account data and transactions. Holds only the public key, never the private one.

Responsibilities:
- Verifying the token signature with the public key on every request and enforcing the role before doing anything
- Enforcing access control between two roles, customer and admin. A customer reaches only their own account, an admin can view any account and can freeze or flag an account. This is a real deliverable, not a label. It is the access control the brief marks explicitly, and it is meaningless with a single role, so the two roles exist to make least privilege enforceable and demonstrable.
- Reading and writing account records, with the sensitive fields (account number, balance, card details) encrypted with AES 256 GCM as the default path, not bolted on later
- Processing transfers, which produces a digital signature over the transaction details stored with the record
- Appending to the audit log on data changes

On the admin and access control. The role check earns marks because the brief lists access control points as an assessed item, and because a signed token the service cannot forge is what makes the role trustworthy. The realistic admin powers are viewing any account and freezing or flagging an account as a fraud response, which matches how real banks behave, a freeze is a bank initiated action a customer cannot perform on their own account. Transfers themselves clear automatically and are not admin approved, since a human approving every payment would be neither realistic nor secure. In the report we can note that in a real bank a freeze is usually triggered by an automated detection system and actioned by a dedicated fraud or compliance role rather than a generic admin, which shows the model is understood even though the prototype simplifies it. The enforcement is a tested behavior, a customer must be blocked from an admin only action such as freezing an account or viewing another account.

Same three layers. The encrypt on write and decrypt on read path is built first, before the endpoints, so encryption is the normal path and not a retrofit.

### 4. Proxy and WAF

Caddy config plus Coraza WAF rules. Not Python.

Responsibilities:
- Terminating TLS (self signed for the prototype, we note Let's Encrypt for production)
- Running Coraza with the OWASP core rule set to inspect and block malicious requests
- Rate limiting
- Reverse proxying to the two services over HTTPS (we decided against mTLS for the build and note it as production future work)

Coraza as a Caddy plugin is the fiddly part. Whoever owns this starts it as an early spike to find out fast if the plugin fights back. Fallback if it eats too much time is Caddy rate limiting plus filtering, with Coraza described fully in the report.

### Deployment glue

Docker Compose ties it together. Caddy is the only thing exposed. The services sit on an internal network. Postgres sits on that internal network with no published port, which is our real, demonstrable firewall (we can show it is unreachable from the host). fail2ban watches the auth logs as the IDS. A scheduled job dumps the database and encrypts the dump before storing it.

---

## Shared contracts, agree these early and do not change them quietly

These are the two places the two services meet. If one person changes these without telling the other, things break silently. Lock them in the first few days and treat any change as something both people sign off on.

- **The crypto function boundary.** The names and inputs of the shared security functions. Once both services build against them, changing a signature breaks the other side.
- **The token payload.** What claims the token carries, for example role, user identity, expiry. Auth decides it, the banking service reads exactly it. A rename on one side silently breaks verification on the other.

Keep both written down somewhere both people see, and keep them in sync with reality.

---

## Security points map (so nobody loses track of what counts)

1. TLS 1.3, client to proxy
2. Firewall, network isolation and no published database port
3. WAF, Coraza on the OWASP rule set
4. HTTPS, proxy to services (mTLS noted as production work)
5. Password hashing and token signing, auth service
6. Access control, customer versus admin role enforcement on every banking request, the assessed access control points
7. Token verification, field encryption, transaction signing, banking service
8. TLS, services to database
9. Encryption at rest, sensitive fields
10. Hash chained audit log, tamper evident
11. Encrypted backups

Plus the IDS, fail2ban on auth logs.

Depth on each of these beats adding more. If time runs short the agreed release valves are: WAF drops to rate limiting plus report writeup, mTLS stays documented only, audit log stays a single table.

---

## Rough build order

1. Person A builds the shared security module first and locks the crypto boundary and token payload. Person B starts in parallel on the banking domain and application logic, the pure layers that do not need crypto yet.
2. Once the shared module is stable, Person A builds the auth service on it. Person B wires crypto into the banking infrastructure layer.
3. Person A, being lighter overall, then owns the proxy, WAF, and deployment glue. Person B finishes the banking service.
4. Back together for integration, firing test attacks at the WAF, checking the audit chain detects tampering, testing a backup restore.
5. Split the writeup along the same lines each person built.

This is tight with no buffer, so keep the release valves above in mind rather than discovering them late.

---

## Who does what

Work is cleanly separated, no shared codebases between the two people. Person A carries more, which is accepted in exchange for clean ownership. Both have similar backend skill.

### Person A owns

The shared security module. All crypto and security primitives, password hashing, token sign and verify, AES field encryption, transaction signatures, the hash chain helper, plus its standalone tests. This is the foundation the whole system rests on, so it gets built and tested first.

The auth service. Register, login, refresh with rotation, the public key endpoint, role claims in the token, input validation, audit logging of auth events. Built on the shared module that Person A already owns, so no cross person dependency.

The proxy, WAF, and deployment glue. Caddy, Coraza, Docker Compose, network isolation, fail2ban, the encrypted backup job. Person A picks this up after auth because auth is the lighter service and this keeps infra with a clear single owner.

### Person B owns

The banking service, end to end. The domain and application logic, token verification and role enforcement, AES field encryption as the default read and write path, transaction signing, audit logging of data changes, and all the account data access. The banking service is the heavier single service, which balances against Person A carrying shared plus auth plus infra.

Person B consumes the shared module as a fixed dependency but does not modify it. If a crypto change is needed, it is requested from Person A rather than edited directly, which keeps the module single owned and avoids both people touching it.

### The dependency that needs managing

Person B needs the shared module before wiring crypto into the banking service. So Person B starts on the banking domain and application layers, the pure logic that does not touch crypto, while Person A gets the shared module stable. By the time Person B needs to encrypt fields and verify tokens, the module exists. This keeps Person B productive from day one without touching Person A's code.

The two contracts still have to be agreed up front even though one person owns each side. Person A defines the crypto boundary and the token payload, writes them down, and Person B builds against them. A change to either is a conversation, not a silent edit.

### Writeup, split along the same lines

Person A documents the shared crypto, auth, access control, WAF, and infra. Person B documents the banking service, field encryption, transaction signing, audit log, and database security. Each documents what they built so each can defend it.
