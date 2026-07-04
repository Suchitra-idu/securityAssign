# Flags

Follow-up items surfaced during build. Not blockers for what's landed, but worth doing before the next milestone or the report.

## Closed since last sweep

- **1. ~~Timing-safe unknown-user login~~** ✅ Dummy bcrypt hash now consulted on the unknown-user branch. Locked by [test_login_unknown_user_still_calls_bcrypt](auth_service/tests/test_login.py). Response time for unknown-user matches wrong-password.
- **2. ~~Admin bootstrap mechanism~~** ✅ Env-driven seed via `AUTH_INITIAL_ADMIN_USERNAME` + `AUTH_INITIAL_ADMIN_PASSWORD`. Idempotent (no-op if the named user exists). Implementation: [auth_service/src/auth_service/application/bootstrap.py](auth_service/src/auth_service/application/bootstrap.py). Tests in [auth_service/tests/test_bootstrap.py](auth_service/tests/test_bootstrap.py).
- **3. ~~fail2ban filter not shipped~~** ✅ Filter, jail, and README under [deploy/fail2ban/](deploy/fail2ban/). Auth log lines now include `ip=<host>` extracted from Caddy's `X-Real-IP` header.
- **4. ~~Token payload contract doc~~** ✅ Pinned at [contracts/token_payload.md](contracts/token_payload.md).
- **5. ~~Crypto function boundary doc~~** ✅ Pinned at [contracts/crypto_boundary.md](contracts/crypto_boundary.md).
- **6. ~~Real-Postgres integration test~~** ✅ 4 tests using `testcontainers-python` in [auth_service/tests/test_integration_postgres.py](auth_service/tests/test_integration_postgres.py). Cover full flow, failed-login audit persistence across rollback, end-to-end audit chain verification, and unique-constraint → `UsernameTaken` translation.
- **7. ~~Flip compose network to `internal: true`~~** ✅ Done with the Caddy landing.
- **8. ~~Private key handling in production~~** ✅ Config now accepts `AUTH_SIGNING_PRIVATE_KEY_PATH` (file) as an alternative to the inline PEM env var. Compose file has a commented `secrets:` block showing how to mount PEMs from disk. Same for the public key.
- **9. ~~Vestigial empty directories~~** ✅ Removed.
- **11. ~~HTTPS between Caddy and auth~~** ✅ Auth image now bakes a self-signed RSA cert and runs uvicorn with `--ssl-keyfile`/`--ssl-certfile`. Caddy reverse-proxies to `https://auth:8000` with `tls_insecure_skip_verify`. Verified end-to-end in the smoke test.
- **14. ~~Banking service not built~~** ✅ Full banking service landed with clean-architecture layout. Domain / application / infrastructure under [banking_service/](banking_service/). 43 tests including 5 real-Postgres integration tests via testcontainers. Delivers assessment points 6 (RBAC customer vs admin), 7 (token verification, field encryption, transaction signing), 9 (encryption at rest for `account_number` / `balance_minor` / `card_number`). Wired into Caddy at `/banking/*` with HTTPS both hops.
- **15. ~~Multi-DB support in compose~~** ✅ Postgres init script at [deploy/compose/postgres-init/](deploy/compose/postgres-init/) creates a separate `banking` database on first boot so auth and banking do not collide on the `audit_log` table.
- **16. ~~TLS between services and Postgres~~** ✅ Custom Postgres image ([deploy/compose/postgres/Dockerfile](deploy/compose/postgres/Dockerfile)) bakes a dev CA + server cert. `pg_hba.conf` is `hostssl`-only (no plain-text `host` line) so `psql "sslmode=disable"` is rejected before auth: `FATAL: no pg_hba.conf entry for host ..., no encryption`. `AUTH_DATABASE_URL` / `BANKING_DATABASE_URL` include `sslmode=verify-ca&sslrootcert=/app/tls/pg-ca.crt`, so services verify the server against the CA. Verified in-container: `SELECT ssl, version, cipher FROM pg_stat_ssl JOIN pg_stat_activity USING (pid)` shows all 4 pool connections on TLS 1.3 / `TLS_AES_256_GCM_SHA384`. Cert generation script: [deploy/compose/tls/generate.sh](deploy/compose/tls/generate.sh).
- **17. ~~Encrypted backup job~~** ✅ Backup sidecar under [deploy/backup/](deploy/backup/) runs a `pg_dump | age` loop on `BACKUP_INTERVAL_SECONDS` (default hourly), writing `.sql.age` ciphertext to a named `backup_data` volume. The `pg_dump` stream never touches the filesystem in plaintext. Uses the same TLS-to-Postgres path as the services (`sslmode=verify-ca`). Retention keeps the newest N per database (default 7) and prunes older. **Restore drill verified**: `docker compose exec -e BACKUP_AGE_IDENTITY=... backup restore /backups/auth-…sql.age auth_restored` decrypts + `pg_restore`s into a fresh DB — data (`users`, `audit_log`) matched pre-backup state. Ciphertext confirmed: `head -c 100 file.sql.age` shows `age-encryption.org/v1` header, not SQL. Attempting `age -d` without the private identity fails with `no identity matched any of the recipients`.

## Still open

### 10. Coraza CRS still in DetectionOnly mode
The WAF is deployed and matches real attack patterns, but rules run in `SecRuleEngine DetectionOnly` so a mis-tuned rule cannot lock legitimate traffic out during the demo. To close: run a representative traffic sample, add exclusions for false positives in a rules file that loads after CRS (e.g. `999-exclusions.conf`), then set `SecRuleEngine On` in [proxy/coraza/coraza.conf](proxy/coraza/coraza.conf).
- Effort: ~1-2 hours of tuning against the integration test suite.

### 12. mTLS between Caddy and services
Called out as production-future-work by DEV_GUIDE. Not implemented, not in scope for this build. Document in the report.

### 13. Client IP preservation through Docker bridge NAT
When traffic enters Caddy from the host via Docker's default bridge network, the source IP Caddy sees is the Docker gateway (e.g. `172.19.0.1`), not the real client's IP. The value ends up in the fail2ban log line, so bans would apply to the gateway rather than the actual attacker. Fine for a demo; production would either:
- run Caddy with `network_mode: host`, or
- deploy behind a real load balancer that forwards a trusted `X-Forwarded-For` chain (auth's `_client_ip` helper already prefers `X-Real-IP` set by Caddy).
- File: [auth_service/src/auth_service/infrastructure/app.py](auth_service/src/auth_service/infrastructure/app.py) `_client_ip`

### 18. Banking service documentation
mkdocs has a placeholder Banking Service section but only carries an overview. Domain / application / infrastructure walkthroughs, flow docs (open account, transfer, freeze), and threat-model notes to match the depth of the auth service docs.
- Effort: ~2-4 hours.

### 19. Admin token in the demo `.env`
Auth service supports admin bootstrap but [deploy/compose/.env](deploy/compose/.env) does not seed one. Without a bootstrapped admin the demo can only exercise customer-role banking routes. Set `AUTH_INITIAL_ADMIN_USERNAME` / `AUTH_INITIAL_ADMIN_PASSWORD` in `.env` to give the smoke test an admin-role path (freeze, list all).
- Effort: 5 minutes.
