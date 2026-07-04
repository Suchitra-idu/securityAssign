#!/bin/sh
# Restore drill. Decrypts one .sql.age file and pipes it into pg_restore
# targeting a fresh database. Used from the docs / smoke test as:
#
#   docker compose exec -e BACKUP_AGE_IDENTITY="$AGE_KEY" backup \
#       restore /backups/auth-20260704T123045Z.sql.age auth_restored
#
# The age private key stays outside the image (env var at exec time) so
# the running backup container cannot itself decrypt older dumps.
set -eu

if [ $# -ne 2 ]; then
    echo "usage: restore <path-to-.sql.age> <target-database>" >&2
    exit 2
fi

archive="$1"
target_db="$2"

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_USER:?required}"
: "${POSTGRES_PASSWORD:?required}"
: "${BACKUP_AGE_IDENTITY:?age private key must be supplied at restore time}"

if [ ! -f "$archive" ]; then
    echo "archive not found: $archive" >&2
    exit 1
fi

key_file="$(mktemp)"
trap 'rm -f "$key_file"' EXIT
printf '%s\n' "$BACKUP_AGE_IDENTITY" > "$key_file"
chmod 400 "$key_file"

conn="postgresql://${POSTGRES_USER}@${POSTGRES_HOST}:5432/postgres?sslmode=verify-ca&sslrootcert=/tls/pg-ca.crt"
target_conn="postgresql://${POSTGRES_USER}@${POSTGRES_HOST}:5432/${target_db}?sslmode=verify-ca&sslrootcert=/tls/pg-ca.crt"

PGPASSWORD="$POSTGRES_PASSWORD" psql "$conn" -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"$target_db\";" \
    -c "CREATE DATABASE \"$target_db\";"

age -d -i "$key_file" "$archive" \
    | PGPASSWORD="$POSTGRES_PASSWORD" pg_restore \
        --dbname="$target_conn" \
        --no-owner --no-privileges --exit-on-error

echo "[restore] $archive → database \"$target_db\""
