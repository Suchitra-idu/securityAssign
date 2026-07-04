#!/usr/bin/env bash
set -euo pipefail

# One-off dev CA + Postgres server cert. Run once from this directory
# (or from anywhere; script resolves its own dir). Outputs:
#   ca.crt         — self-signed dev CA, shipped to auth + banking as sslrootcert
#   ca.key         — CA private key, only needed to reissue server certs
#   server.crt     — Postgres server cert, CN=postgres, SAN DNS:postgres,localhost
#   server.key     — Postgres server key, chmod 600 (Postgres refuses looser)
#
# These files are gitignored. Regenerate on rotation.

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [[ -f server.crt && -f server.key && -f ca.crt ]]; then
    echo "certs already present in $here — delete them to regenerate" >&2
    exit 0
fi

openssl req -x509 -newkey rsa:2048 -sha256 -days 3650 -nodes \
    -keyout ca.key -out ca.crt \
    -subj '/CN=securebank-dev-ca' >/dev/null 2>&1

openssl req -new -newkey rsa:2048 -nodes \
    -keyout server.key -out server.csr \
    -subj '/CN=postgres' >/dev/null 2>&1

cat > server.ext <<'EOF'
subjectAltName=DNS:postgres,DNS:localhost
extendedKeyUsage=serverAuth
EOF

openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days 3650 -sha256 -extfile server.ext >/dev/null 2>&1

rm -f server.csr server.ext ca.srl
chmod 600 server.key ca.key
chmod 644 server.crt ca.crt

echo "generated: ca.crt server.crt server.key (+ ca.key kept for reissue)"
