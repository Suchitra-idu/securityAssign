FROM alpine:3.20

RUN apk add --no-cache postgresql16-client age tini

COPY deploy/backup/backup.sh /usr/local/bin/backup
COPY deploy/backup/restore.sh /usr/local/bin/restore
COPY deploy/backup/entrypoint.sh /entrypoint.sh
COPY deploy/compose/tls/ca.crt /tls/pg-ca.crt

RUN chmod 755 /usr/local/bin/backup /usr/local/bin/restore /entrypoint.sh \
 && chmod 444 /tls/pg-ca.crt \
 && mkdir -p /backups

VOLUME /backups

ENTRYPOINT ["/sbin/tini", "--", "/entrypoint.sh"]
