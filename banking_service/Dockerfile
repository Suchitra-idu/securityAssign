FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

RUN adduser --system --group --home /app app
WORKDIR /app

COPY shared_security /app/shared_security
COPY banking_service /app/banking_service

RUN pip install --no-cache-dir /app/shared_security /app/banking_service

RUN mkdir -p /app/tls \
 && openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
     -keyout /app/tls/key.pem \
     -out   /app/tls/cert.pem \
     -subj  '/CN=banking' \
 && chown -R app:app /app/tls \
 && chmod 400 /app/tls/key.pem \
 && chmod 444 /app/tls/cert.pem

COPY deploy/compose/tls/ca.crt /app/tls/pg-ca.crt
RUN chown app:app /app/tls/pg-ca.crt && chmod 444 /app/tls/pg-ca.crt

USER app

EXPOSE 8000

CMD ["uvicorn", "banking_service.infrastructure.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile",  "/app/tls/key.pem", \
     "--ssl-certfile", "/app/tls/cert.pem"]
