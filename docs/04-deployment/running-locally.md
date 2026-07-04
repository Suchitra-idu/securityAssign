# Running locally

Two ways to run auth_service on your machine: Docker Compose (closest to production shape) and a bare-metal venv (fastest iteration during development).

## Option 1: Docker Compose

Runs Caddy + auth + Postgres on two Docker networks: `edge` (Caddy only, published to host) and `internal` (`internal: true`, auth + postgres, no route to the outside world). **Only Caddy is reachable from the host.**

### One-time setup

```
cd deploy/compose
cp .env.example .env
```

Fill in `.env`. The signing keypair is the fiddly bit — generate it with:

```
/path/to/.venv/bin/python -c "from shared_security.tokens import generate_signing_keypair; priv, pub = generate_signing_keypair(); print('PRIV=' + repr(priv)); print('PUB=' + repr(pub))"
```

Or, with openssl (no Python venv needed):

```
openssl genpkey -algorithm ED25519 -out /tmp/priv.pem
openssl pkey -in /tmp/priv.pem -pubout -out /tmp/pub.pem
```

Copy the two PEMs into `.env` as `AUTH_SIGNING_PRIVATE_KEY_PEM` and `AUTH_SIGNING_PUBLIC_KEY_PEM`. Watch out for shell-quoting — the values contain literal `\n`; wrap in double quotes.

### Bring it up

```
docker compose up -d --build
```

Three services build/pull:
- **caddy** — custom Caddy 2.11 built by `xcaddy` with `coraza-caddy` (WAF) and `caddy-ratelimit` plugins, with OWASP CRS v4 baked in. First build takes ~2-3 minutes because Go compiles Caddy from source with the plugins. Subsequent builds are cached.
- **auth** — the FastAPI service.
- **postgres** — official `postgres:16-alpine`.

On boot, auth applies the schema ({{ src("auth_service/src/auth_service/infrastructure/db.py", text="apply_schema") }}) and Caddy generates a local CA + issues a cert for `localhost`.

Hit it:

```
# curl -k because Caddy's local CA isn't in your system trust store
curl -k https://localhost:8443/health
# HTTP redirects to HTTPS
curl -kL http://localhost:8080/health

curl -k -X POST https://localhost:8443/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"correct-horse-battery"}'
```

### Confirming isolation

- **Postgres from host**: `docker ps` shows `compose-postgres-1` with `5432/tcp` only, no host binding. A raw TCP connect to `localhost:5432` will refuse.
- **Auth from host**: same — `8000/tcp` only, no host mapping. Only Caddy publishes ports (`8080`, `8443`).
- **From inside**: `docker compose exec caddy sh` → `wget -O- http://auth:8000/health` works.

If a host process (e.g. `mkdocs serve`) already occupies port 8000 or 8080, a raw TCP connect will succeed — but that's the host process, not our stack. `docker ps` is the definitive check.

### Tearing down

```
docker compose down          # keep the data volume
docker compose down -v       # drop the data volume too — full reset
```

## Option 2: Bare-metal venv

Fastest for the inner development loop.

### Setup

From the repo root:

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e './shared_security[dev]' -e './auth_service[dev]'
```

You now have both packages installed in editable mode. Changes to source files take effect immediately (no reinstall). pytest picks up `pyproject.toml` from each package.

### Running the tests

```
cd auth_service && pytest -q
cd ../shared_security && pytest -q
```

See {{ src("05-testing/running-tests.md", text="../05-testing/running-tests.md") }}.

### Running the FastAPI server

Needs a real Postgres. Simplest path — a throwaway container:

```
docker run --rm -d --name auth-pg -p 5432:5432 -e POSTGRES_PASSWORD=dev postgres:16-alpine
```

Then set env vars in your shell:

```
export AUTH_DATABASE_URL="postgresql://postgres:dev@localhost:5432/postgres"
export AUTH_SIGNING_PRIVATE_KEY_PEM="$(python -c "from shared_security.tokens import generate_signing_keypair; print(generate_signing_keypair()[0])")"
export AUTH_SIGNING_PUBLIC_KEY_PEM="$(python -c "from shared_security.tokens import generate_signing_keypair; print(generate_signing_keypair()[1])")"
```

Wait — those two commands generate *different* keypairs. Use the two-liner from the compose section instead so both env vars come from one call to `generate_signing_keypair()`.

Then:

```
uvicorn auth_service.infrastructure.main:app --reload
```

`--reload` auto-restarts on code changes. Handy while iterating.

## OpenAPI docs

FastAPI serves interactive API docs:

- `GET /docs` — Swagger UI.
- `GET /redoc` — ReDoc.
- `GET /openapi.json` — machine-readable spec.

These are unauthenticated. Useful for exploring endpoints during development; disable or protect in production once Caddy fronts everything.

## What is not in this workflow

- **Caddy / TLS termination** — not built yet.
- **fail2ban** — not built yet.
- **Backup job** — not built yet.
- **Log aggregation** — logs go to stdout; Docker captures them. Nothing shipped anywhere.
