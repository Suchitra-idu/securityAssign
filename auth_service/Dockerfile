FROM python:3.12-slim

# openssl for the self-signed cert we serve to Caddy.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN adduser --system --group --home /app app
WORKDIR /app

COPY shared_security /app/shared_security
COPY auth_service /app/auth_service

RUN pip install --no-cache-dir /app/shared_security /app/auth_service

# Self-signed TLS cert baked at build time. Caddy trusts it via
# `tls_insecure_skip_verify` in the Caddyfile. This gives us a real
# HTTPS hop between Caddy and auth — the mTLS upgrade is production
# future work per DEV_GUIDE.
RUN mkdir -p /app/tls \
 && openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
     -keyout /app/tls/key.pem \
     -out   /app/tls/cert.pem \
     -subj  '/CN=auth' \
 && chown -R app:app /app/tls \
 && chmod 400 /app/tls/key.pem \
 && chmod 444 /app/tls/cert.pem

USER app

EXPOSE 8000

CMD ["uvicorn", "auth_service.infrastructure.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile",  "/app/tls/key.pem", \
     "--ssl-certfile", "/app/tls/cert.pem"]
