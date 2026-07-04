#!/bin/sh
# Runs an immediate backup on start, then loops on BACKUP_INTERVAL_SECONDS.
# Failures in a single iteration are logged and the loop continues so a
# transient DB blip doesn't kill the sidecar.
set -eu

: "${BACKUP_INTERVAL_SECONDS:=3600}"

echo "[backup] service starting, interval=${BACKUP_INTERVAL_SECONDS}s recipient=${BACKUP_AGE_RECIPIENT:-unset}"

/usr/local/bin/backup || echo "[backup] initial backup failed"

while true; do
    sleep "$BACKUP_INTERVAL_SECONDS"
    /usr/local/bin/backup \
        || echo "[backup] iteration failed at $(date -u +%FT%TZ) — continuing"
done
