# Portable attacker image. Includes the docker CLI + compose plugin so the
# script can shell into the postgres / banking / backup containers over the
# mounted docker.sock. Alpine keeps the image ~50 MB.

FROM alpine:3.20
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    docker-cli \
    docker-cli-compose

WORKDIR /repo
COPY attack-demo.sh /usr/local/bin/attack-demo
COPY entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/attack-demo /usr/local/bin/entrypoint

# Defaults assume the container is launched with
#   --add-host=host.docker.internal:host-gateway
# so the entrypoint can point localhost at the host and TLS SNI stays
# "localhost" (Caddy's dev-cert hostname). /repo is a bind-mount of the
# repository root.
ENV BASE_URL=https://localhost:8443 \
    COMPOSE_DIR=/repo/deploy/compose \
    ADMIN_USER=admin \
    ADMIN_PASS=admin-demo-do-not-ship \
    PAUSE_SECS=2

ENTRYPOINT ["/usr/local/bin/entrypoint"]
