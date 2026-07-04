# Environment variables

All auth_service configuration is env-driven. All vars use the `AUTH_` prefix. Sourced by {{ src("auth_service/src/auth_service/infrastructure/config.py", text="Config") }} via `pydantic-settings`.

An env template lives at {{ src("deploy/compose/.env.example", text="../../deploy/compose/.env.example") }}.

## Required vars

### `AUTH_DATABASE_URL`

Postgres connection string in libpq URL form.

Format: `postgresql://user:password@host:port/database`

Example: `postgresql://auth:s3cret@postgres:5432/auth`

In compose the hostname is the service name (`postgres`). In bare-metal dev, it's `localhost` (usually with a mapped port).

### `AUTH_SIGNING_PRIVATE_KEY_PEM`

PEM-encoded Ed25519 private key. The auth service is the only holder of this key.

Format: multi-line PKCS#8 PEM (`-----BEGIN PRIVATE KEY-----` … `-----END PRIVATE KEY-----`). In a `.env` file, wrap in double quotes so `\n` is preserved literally.

Generation (once per environment):

```
python -c "from shared_security.tokens import generate_signing_keypair; priv, pub = generate_signing_keypair(); print(priv)"
```

Guidance:
- **Never check in.** `.gitignore` excludes `.env`.
- **Not persistent across environments.** Prod, staging, and dev each get their own keypair. If you generate a new keypair, all existing tokens (both access and refresh) become unverifiable.
- **In production, prefer a Docker secret or a mounted file** over an env var. Env vars are visible to anyone who can inspect the container (`docker inspect`, `ps eww`). See {{ src("flags.md", text="../../flags.md", anchor="8-private-key-handling-in-production") }}.

### `AUTH_SIGNING_PUBLIC_KEY_PEM`

PEM-encoded Ed25519 public key. The other half of the keypair.

Format: multi-line SubjectPublicKeyInfo PEM.

Served at `GET /public-key`. See {{ src("03-auth-service/flow-public-key.md", text="../03-auth-service/flow-public-key.md") }}.

**Must be generated from the same keypair as the private key.** If they don't match, freshly-signed tokens will fail verification on the banking side (when built). No runtime check catches this — verification just fails.

## Optional vars

### `AUTH_ACCESS_TTL_SECONDS`

Access-token lifetime in seconds. Default `300` (5 minutes). Minimum `60` (enforced by Pydantic `Field(ge=60)`).

Short-ish because access tokens are stateless — the shorter the TTL, the tighter the window between "credential theft" and "attacker locked out". Refresh tokens handle "user shouldn't have to log in every 5 minutes".

### `AUTH_REFRESH_TTL_SECONDS`

Refresh-token lifetime in seconds. Default `86400` (24 hours). Minimum `3600` (1 hour).

Longer, because presenting a refresh token requires an active client with the stored opaque value. Not stateless — server-side row is required.

### `AUTH_POOL_MIN_SIZE`

Psycopg3 connection pool minimum size. Default `1`.

Pool holds at least this many connections open at all times, avoiding the setup cost on the first request.

### `AUTH_POOL_MAX_SIZE`

Psycopg3 connection pool maximum size. Default `10`.

**Important context**: each in-flight request holds **two** connections (main + audit — see {{ src("03-auth-service/audit-log-durability.md", text="../03-auth-service/audit-log-durability.md") }}). So max concurrent requests ≈ `AUTH_POOL_MAX_SIZE / 2`. Bump for higher-throughput deployments.

## Ignored vars

Pydantic-settings is configured with `extra="ignore"` — vars that don't match any declared field are silently discarded. Useful because compose passes a lot of Postgres-related vars (`POSTGRES_USER`, `POSTGRES_DB`) that the auth service doesn't itself read.

## `.env` file discovery

`Config` looks for a `.env` file in the current working directory (`env_file=".env"`). This applies when running bare-metal — Docker Compose injects env vars via `environment:` blocks instead, so the `.env` file is not read inside the container.

Precedence, highest to lowest:
1. Real environment (`export FOO=bar`).
2. `.env` file (bare-metal mode).
3. Default values in `Config`.

## Vars that will be added later

- `AUTH_INITIAL_ADMIN_USERNAME` / `AUTH_INITIAL_ADMIN_PASSWORD` — for the admin bootstrap ({{ src("flags.md", text="flag 2") }}).
- Anything Caddy / Coraza / fail2ban configuration needs when those land.
