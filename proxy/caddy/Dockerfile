FROM caddy:2.11-builder AS builder

RUN xcaddy build \
    --with github.com/corazawaf/coraza-caddy/v2 \
    --with github.com/mholt/caddy-ratelimit

FROM caddy:2.11

# OWASP Core Rule Set v4 — pinned tag for reproducible builds.
ARG CRS_VERSION=4.16.0

RUN apk add --no-cache curl \
 && mkdir -p /etc/coraza/rules \
 && curl -fsSL "https://github.com/coreruleset/coreruleset/archive/refs/tags/v${CRS_VERSION}.tar.gz" \
    | tar -xz -C /tmp \
 && cp /tmp/coreruleset-${CRS_VERSION}/rules/*.conf /etc/coraza/rules/ \
 && cp /tmp/coreruleset-${CRS_VERSION}/rules/*.data /etc/coraza/rules/ \
 && cp /tmp/coreruleset-${CRS_VERSION}/crs-setup.conf.example /etc/coraza/crs-setup.conf \
 && rm -rf /tmp/coreruleset-${CRS_VERSION} \
 && apk del curl

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY proxy/coraza/coraza.conf /etc/coraza/coraza.conf
COPY proxy/caddy/Caddyfile /etc/caddy/Caddyfile

# Static UI. Vanilla HTML/JS/CSS — no build step. Served by Caddy on
# the root path; every non-API request falls through to file_server.
COPY ui /srv/ui

# CRS rules reference their .data files by relative path (e.g.
# "scanners-user-agents.data"). Coraza resolves those relative to the
# process working directory, so the WAF loads clean only if we start
# Caddy from the rules dir.
WORKDIR /etc/coraza/rules

EXPOSE 80 443

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
