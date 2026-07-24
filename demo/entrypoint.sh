#!/bin/sh
# Docker Desktop / Linux docker-run entrypoint.
#
# Caddy's TLS certificate is for the hostname "localhost" only. When the
# demo runs inside a container we must keep the SNI = "localhost" so that
# the handshake succeeds. But the actual server lives on the host, reached
# through host.docker.internal:8443 (with --add-host=host.docker.internal:host-gateway).
#
# Trick: write a global ~/.curlrc that tells every curl call to keep the
# URL host as "localhost" but connect the socket to host.docker.internal
# via --connect-to. This preserves SNI while pointing traffic at the host.
# Alpine's musl resolver ignores /etc/hosts for "localhost", so /etc/hosts
# rewriting does not work — --connect-to does.
set -eu

if getent hosts host.docker.internal >/dev/null 2>&1; then
    cat > /root/.curlrc <<'EOF'
--connect-to localhost:8443:host.docker.internal:8443
--connect-to localhost:80:host.docker.internal:80
EOF
    export HOME=/root
fi

exec /usr/local/bin/attack-demo "$@"
