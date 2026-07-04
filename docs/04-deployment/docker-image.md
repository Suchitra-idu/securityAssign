# Docker image

The auth_service image. One Dockerfile at {{ src("auth_service/Dockerfile", text="../../auth_service/Dockerfile") }}.

## Contents

```dockerfile
FROM python:3.12-slim

RUN adduser --system --group --home /app app
WORKDIR /app

COPY shared_security /app/shared_security
COPY auth_service /app/auth_service

RUN pip install --no-cache-dir /app/shared_security /app/auth_service

USER app

EXPOSE 8000

CMD ["uvicorn", "auth_service.infrastructure.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Design points

### Base image

`python:3.12-slim`. Debian-slim variant. Small enough for a demo, has enough runtime for psycopg's binary wheels. Alpine would be smaller but breaks psycopg-binary — musl vs glibc mismatch.

### Two source copies

Both `shared_security/` and `auth_service/` are copied because auth_service depends on shared_security. In a real workflow with published PyPI packages, only auth_service would be copied. For this monorepo, the local path install is the pragmatic choice.

The pip install line installs both packages. Order matters — shared_security first so its pyproject can satisfy auth_service's `shared-security` dependency.

### Non-root user

`RUN adduser --system --group --home /app app` creates an unprivileged user. `USER app` switches to it before `CMD`. Even if uvicorn or the app has a container-escape vulnerability, the attacker is inside a shell that cannot write to `/`, cannot install packages, cannot chown things.

### Build context

The Dockerfile references `/app/shared_security` and `/app/auth_service`. That means the Docker build context must be the **repo root**, not `auth_service/`. The compose file does this correctly:

```yaml
auth:
  build:
    context: ../..
    dockerfile: auth_service/Dockerfile
```

Building from `auth_service/` directly (`docker build -t auth .`) would fail — `COPY shared_security ...` cannot see files outside its context.

### No `.dockerignore` yet

Missing — a `.dockerignore` should exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, `tests/`, and `*.md` to keep the image slim and rebuild-fast. Not shipped in this build. Small follow-up.

### `--no-cache-dir` on pip install

Avoids caching wheels inside the image — pip's cache directory would otherwise be ~50 MB of noise.

### Entry point

```
uvicorn auth_service.infrastructure.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` — required to accept connections from other Docker containers. Not "exposes to the internet" — Docker's network isolation still applies.
- Port 8000 inside the container. `EXPOSE 8000` is documentation for downstream operators; it does not publish anything.

## What is not in this image

- **No health-check** — Docker `HEALTHCHECK` is not declared. The `/health` endpoint exists in the app but no container-level check calls it. Compose currently relies on `depends_on: service_healthy` for Postgres only. Adding an auth healthcheck would let Caddy wait for auth to be ready.
- **No multi-stage build** — everything is done in one layer. A wheel-building stage that discards build-time-only artifacts would trim the image. Not done because the image is already small.
- **No pinned base image digest** — `python:3.12-slim` moves. For deployment we would pin to `python:3.12-slim@sha256:…`.
- **No non-obvious labels** — `LABEL org.opencontainers.image.…` is useful in production for image scanning. Not needed for the demo.
- **No secrets baked in** — the private key is passed at runtime via env var, not embedded. This is correct. See {{ src("flags.md", text="flag 8") }} for the hardening notes.

## Rebuilding

The image is cached until `COPY` sees changed files. Since the whole source tree is `COPY`ed, any code change invalidates the cache from that layer onward.

For faster iteration during development, use the bare-metal venv workflow described in [running-locally.md](running-locally.md). Rebuild the image only when testing the Docker environment specifically.

## What runs when the container boots

1. uvicorn starts.
2. Imports `auth_service.infrastructure.main`, which runs `Config()`. If any required env var is missing, pydantic-settings raises and uvicorn exits with a stack trace. The container will restart-loop if it doesn't have valid config.
3. `create_app(Config())` — builds the psycopg pool via `build_pool`, calls `apply_schema` on it (which reads the `schema.sql` package resource and executes it), returns the FastAPI app.
4. uvicorn binds `0.0.0.0:8000` and accepts requests.

If Postgres is unreachable during startup, the pool's connect will hang and time out; uvicorn will exit and Docker will restart. Compose is configured to wait for Postgres's healthcheck first, so this only bites if Postgres becomes unavailable mid-run.
