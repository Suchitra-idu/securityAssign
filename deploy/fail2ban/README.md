# fail2ban integration

Host-side IDS for the auth service. Watches the `LOGIN_FAILED` and `REFRESH_FAILED` lines the auth service emits, bans offending IPs at the firewall.

fail2ban runs on the **host**, not in a container. This directory ships the filter + jail configs it needs; installing fail2ban itself is your platform's job.

## Files

- `filter.d/auth-login.conf` — regex that matches `LOGIN_FAILED ip=<HOST>` and `REFRESH_FAILED ip=<HOST>` lines. `<HOST>` is fail2ban's placeholder for the extracted IPv4/IPv6 address.
- `jail.d/auth.conf` — jail definition: 5 failures in 5 min → 1-hour ban via `iptables-multiport`. Update `logpath` for your log-capture setup.

## Making auth logs visible to host fail2ban

The auth container writes to stdout. There are three common paths:

1. **Docker json-file driver (default)**. The container's log file is at `/var/lib/docker/containers/<id>/<id>-json.log`. Point `logpath` there. Wildcards work: `/var/lib/docker/containers/*/*-json.log`. The regex still matches because the JSON wrapper doesn't hide our log text.
2. **Bind-mounted log directory**. Add a volume to the auth service in [../compose/docker-compose.yml](../compose/docker-compose.yml) and configure Python's logger to write to a file inside it. `logpath = /var/log/auth-service/*.log`. Cleaner but requires code changes in `main.py` to add a `FileHandler`.
3. **Journald log driver**. Change compose to `logging.driver: journald`. Use fail2ban's `journalmatch` in the jail instead of `logpath`. Best for systems already using systemd.

For a demo, option 1 is zero-setup. For a real deployment, option 2 gives cleaner rotation control.

## Install (Ubuntu / Debian example)

```
sudo apt install fail2ban
sudo cp deploy/fail2ban/filter.d/auth-login.conf /etc/fail2ban/filter.d/
sudo cp deploy/fail2ban/jail.d/auth.conf         /etc/fail2ban/jail.d/
sudo systemctl reload fail2ban
sudo fail2ban-client status auth-login   # should show the jail as active
```

## Testing

```
# Trigger 5 failures from a single IP:
for i in 1 2 3 4 5; do
    curl -sk -X POST https://localhost:8443/login \
        -H 'Content-Type: application/json' \
        -d '{"username":"alice","password":"wrong-wrong-wrong"}'
done

sudo fail2ban-client status auth-login
# → currently banned: 1
# → banned IP list: 172.17.0.1 (or whatever)
```

The ban applies at the host firewall; auth and Caddy do not know it happened. Unban with:

```
sudo fail2ban-client set auth-login unbanip <IP>
```

## What this does *not* protect against

- Distributed bruteforce from many IPs — fail2ban is per-IP.
- Attackers behind CGNAT sharing an IP with legitimate users — one attacker gets everyone banned.
- WAF-visible attacks — those are Coraza's job (see [../../proxy/coraza/coraza.conf](../../proxy/coraza/coraza.conf)).
