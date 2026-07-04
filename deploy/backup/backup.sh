#!/bin/sh
# Encrypt-then-write backup of the auth and banking databases.
# pg_dump streams over TLS 1.3 to the Postgres server; the plain SQL never
# hits the filesystem — it is piped straight into `age` and only the
# ciphertext (.sql.age) is written to /backups.
set -eu

: "${POSTGRES_HOST:=postgres}"
: "${POSTGRES_USER:?required}"
: "${POSTGRES_PASSWORD:?required}"
: "${BACKUP_AGE_RECIPIENT:?required}"
: "${BACKUP_DIR:=/backups}"
: "${BACKUP_RETENTION:=7}"

ts="$(date -u +%Y%m%dT%H%M%SZ)"

for db in auth banking; do
    out="${BACKUP_DIR}/${db}-${ts}.sql.age"
    tmp="${out}.partial"
    # Use custom format (-Fc) so restore is `pg_restore` (parallel, selective).
    # Connection string forces TLS with CA verification against the CA baked
    # into this image at build time.
    PGPASSWORD="$POSTGRES_PASSWORD" pg_dump \
        --format=custom \
        "postgresql://${POSTGRES_USER}@${POSTGRES_HOST}:5432/${db}?sslmode=verify-ca&sslrootcert=/tls/pg-ca.crt" \
      | age -r "$BACKUP_AGE_RECIPIENT" > "$tmp"
    mv "$tmp" "$out"
    chmod 400 "$out"
    printf '[backup] %s wrote %s (%s bytes)\n' \
        "$(date -u +%FT%TZ)" "$out" "$(stat -c %s "$out")"
done

# Retention: keep the newest N per database, delete the rest.
for db in auth banking; do
    ls -1t "${BACKUP_DIR}"/"${db}"-*.sql.age 2>/dev/null \
        | tail -n +"$((BACKUP_RETENTION + 1))" \
        | xargs -r rm -f
done
