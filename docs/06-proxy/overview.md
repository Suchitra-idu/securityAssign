# Proxy + WAF + TLS

Caddy sits in front of auth and banking. It terminates TLS, filters requests through a WAF, rate-limits per client IP, and reverse-proxies to the internal services. **Only Caddy has published ports.** Auth, banking, and Postgres live on an `internal: true` Docker network with no way to reach the internet or be reached from outside the compose stack.

## What runs

```
                   ┌─────────────────────────┐
                   │      HTTP client        │
                   └───┬───────────────────┬─┘
                       │ :8080 (HTTP)      │ :8443 (HTTPS, TLS 1.3)
                       ▼                    ▼
        ┌────────────────────────────────────────────┐
        │                Caddy 2.11                   │
        │  ────────────────────────────────────────  │
        │  • tls internal   → Caddy Local Authority  │
        │  • coraza_waf     → OWASP CRS v4 (DetectionOnly)
        │  • rate_limit     → 60 events / 1 min per IP
        │  • :80 → 301 → :443                        │
        │                                             │
        │  handle_path /banking/*  → https://banking:8000
        │  handle @auth_paths      → https://auth:8000
        │  handle          /*      → file_server /srv/ui (baked UI)
        └────────┬─────────────────┬────────────────┘
                 │ HTTPS           │ HTTPS
                 │ (self-signed)   │ (self-signed)
                 ▼                 ▼
        ┌───────────────┐  ┌────────────────┐
        │ auth service  │  │ banking service│
        └───────┬───────┘  └────────┬───────┘
                │                   │
                └─────────┬─────────┘
                          ▼
                 ┌─────────────────┐
                 │   PostgreSQL    │  auth DB + banking DB
                 └─────────────────┘
```

## Files

- {{ src("proxy/caddy/Dockerfile") }} — multi-stage build. Stage 1 uses `caddy:2.11-builder` + `xcaddy` to compile a custom Caddy binary with the Coraza WAF and rate-limit plugins. Stage 2 is the runtime image with the plugins baked in plus the OWASP CRS v4 rule set copied into `/etc/coraza/rules/`.
- {{ src("proxy/caddy/Caddyfile") }} — Caddy config: TLS on `localhost`, WAF, rate-limit, `handle_path /banking/*` → `https://banking:8000`, `handle @auth_paths` → `https://auth:8000` on the five explicit API paths, root `handle` → `file_server` on `/srv/ui/` for the static UI.
- {{ src("ui/") }} — vanilla HTML / JS / CSS UI, no build step. Copied into the Caddy image at `/srv/ui/` at build time. Same-origin with both backends, so no CORS.
- {{ src("proxy/coraza/coraza.conf") }} — Coraza engine config. Sets `SecRuleEngine DetectionOnly`, JSON request-body parsing, audit log to stdout.

## Security controls this delivers

Cross-reference with the {{ src("docs/01-architecture/security-controls.md", text="security controls map") }}:

- **Point 1: TLS 1.3, client → proxy** ✅ Caddy uses `tls internal` — an on-the-fly local CA that issues an EC cert for `localhost`. `curl -k` because the CA isn't in the system trust store. Confirmed with `openssl s_client`: `Protocol: TLSv1.3`, cipher `TLS_AES_128_GCM_SHA256`.
- **Point 2: no published database port** ✅ Postgres has no `ports:` block and is on the `internal: true` network. `nc localhost 5432` refuses.
- **Point 3: WAF, Coraza on OWASP CRS** 🟡 Runs, matches SQL injection / XSS / RCE / path traversal from CRS. **Currently in `DetectionOnly` mode** so rule mis-tuning cannot lock out legitimate traffic during the demo. Flip to `SecRuleEngine On` in {{ src("proxy/coraza/coraza.conf", text="coraza.conf") }} after tuning is complete.
- **Point 4: HTTPS, proxy → services** ✅ Both auth and banking bake a self-signed RSA cert at image build ({{ src("auth_service/Dockerfile") }}, {{ src("banking_service/Dockerfile") }}) and serve on `https://<service>:8000`. Caddy proxies with `tls_insecure_skip_verify` because the internal certs aren't signed by Caddy's CA. mTLS is documented as production future work in DEV_GUIDE.

## Why DetectionOnly by default

OWASP CRS v4 is deliberately noisy — at paranoia level 1 (the default), it still flags a wide variety of patterns, including some legitimate JSON payloads with strings that look like SQL keywords. If we shipped `SecRuleEngine On` without tuning, a login with the password `"select the correct answer"` might get blocked.

The proper tuning workflow:

1. Start in **DetectionOnly** — audit log captures rule hits without blocking.
2. Run a representative traffic sample (integration tests + a manual walkthrough of every endpoint).
3. For each false-positive rule, add an exclusion in a rules file that loads *after* CRS (e.g. `999-exclusions.conf`) so the exclusion tags survive rule reloads.
4. Switch to **On**.

For the demo we ship step 1 and document the workflow. The audit-log evidence of rule matches is a stronger demonstration than a black-box "requests get 403" behaviour.

## How the WAF is exercised in the smoke test

```
$ curl -sk "https://localhost:8443/health?id=1'%20UNION%20SELECT%201,2,3--"
{"status":"ok"}                    # DetectionOnly: request is allowed through

$ docker compose logs caddy | grep OWASP_CRS
... "rule_id":"942100", "msg":"SQL Injection Attack Detected via libinjection", ...
... "rule_id":"942130", ...
... "tag":"OWASP_CRS", "tag":"paranoia-level/1", ...
```

The request goes through (DetectionOnly), but the WAF logs a rule hit with the exact CRS rule ID, message, and tags. In `SecRuleEngine On` mode the same request would be blocked with a 403.

## Rate limit

Configured in the {{ src("proxy/caddy/Caddyfile") }}:

```
rate_limit {
    zone per_ip {
        key {remote_host}
        events 60
        window 1m
    }
}
```

- **Key**: client IP (the direct TCP peer of Caddy, so behind a real load balancer this would be `{header.X-Forwarded-For}` — safe here because Caddy IS the edge).
- **Threshold**: 60 requests per minute per IP.
- **Overflow**: HTTP 429.

Verified in the smoke test: 70 rapid requests → 55 succeed, 15 return 429.

This defends against credential-stuffing (60 login attempts/minute/IP is more than enough for a human user and useless for a bruteforce) and low-effort scraping. Distributed attacks require a bigger defence layer (upstream WAF or CDN) that this project does not include.

## What the proxy layer does *not* do

- **No auth check**. Caddy just proxies; it doesn't inspect JWTs. Auth (and later banking) verify tokens on their side.
- **No response inspection**. `SecResponseBodyAccess Off` in {{ src("proxy/coraza/coraza.conf", text="coraza.conf") }} — we don't scan responses for leaks. If banking ever returns sensitive fields that should be redacted at the edge, this changes.
- **No mTLS between Caddy and services**. Documented as production future work in {{ src("DEV_GUIDE.md") }}. Caddy trusts the self-signed certs on auth and banking via `tls_insecure_skip_verify`; the transport is TLS 1.3 but there's no client-cert step in either direction.
- **No connection tracking / DDoS protection**. Rate limit is per-IP with a naive sliding window. A distributed attacker can outrun it.

## Trade-offs made explicit

| Decision | Trade-off |
|----------|-----------|
| `tls internal` instead of Let's Encrypt | Browsers warn; `curl -k` needed. Trades production UX for zero-setup demo. Production would swap the site block for a real hostname. |
| DetectionOnly for CRS | Can't demonstrate 403 blocks without config change. Trades demo drama for zero-risk-of-lockout. |
| Self-signed certs on auth + banking | Caddy has to skip verification. Trades a proper internal CA for simpler build. mTLS is the production upgrade. |
| No mTLS | Documented in DEV_GUIDE as a release valve. Trades assessment point mTLS-would-hit for build-time. |
| Rate limit at 60/min | Enough for a human, tight against automation. Trades UX for security. |

## Running the stack

See [../04-deployment/running-locally.md](../04-deployment/running-locally.md). The short version:

```bash
cd deploy/compose
docker compose up -d --build
curl -k https://localhost:8443/health
```
