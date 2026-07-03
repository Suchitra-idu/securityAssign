# Running locally

Two ways to run auth_service on your machine: Docker Compose (closest to production shape) and a bare-metal venv (fastest iteration during development).

## Option 1: Docker Compose

Runs Postgres + auth on an internal Docker network. Postgres is **not published** to the host — this is the same network isolation the assignment security points call for.

### One-time setup

```
cd deploy/compose
cp .env.example .env
```

Fill in `.env`. The signing keypair is the fiddly bit — generate it with:

```
/path/to/.venv/bin/python -c "from shared_security.tokens import generate_signing_keypair; priv, pub = generate_signing_keypair(); print('PRIV=' + repr(priv)); print('PUB=' + repr(pub))"
```

Copy the two strings into `.env` as `AUTH_SIGNING_PRIVATE_KEY_PEM` and `AUTH_SIGNING_PUBLIC_KEY_PEM`. Watch out for shell-quoting — the values contain literal `\n`; wrap in double quotes.

### Bring it up

```
docker compose up --build
```

This builds the auth_service image from [../../auth_service/Dockerfile](../../auth_service/Dockerfile), starts Postgres, waits for its healthcheck, and boots auth_service. Auth applies the schema on startup ([apply_schema](../../auth_service/src/auth_service/infrastructure/db.py)) so the tables exist even on first boot.

Auth is currently not front-fronted by Caddy, so if you want to hit it from your host, add a `ports:` block to the `auth` service in [../../deploy/compose/docker-compose.yml](../../deploy/compose/docker-compose.yml) *temporarily* while developing:

```yaml
  auth:
    ports:
      - "8000:8000"
```

Then:

```
curl http://localhost:8000/health
curl -X POST http://localhost:8000/register \
     -H 'Content-Type: application/json' \
     -d '{"username":"alice","password":"correct-horse-battery"}'
```

Remove the `ports:` block before committing anything — production shape is "Caddy is the only exposed service".

### Confirming Postgres is not reachable from the host

```
nc -vz localhost 5432       # should fail: no route to host
docker compose exec postgres psql -U auth -d auth   # works: same internal network
```

This is the "no published database port" security point in practice.

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

See [../05-testing/running-tests.md](../05-testing/running-tests.md).

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
