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
