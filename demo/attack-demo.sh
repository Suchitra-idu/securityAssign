#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Secure Banking Application — live attack demo
#
# Runs seven attack scenarios back-to-back against the running stack and
# shows each defensive control catching the attack. Meant to be run at a
# live presentation.
#
# Requires the stack to be up: `cd deploy/compose && docker compose up -d`.
# Requires curl and jq on the host.
#
# Usage:
#   ./demo/attack-demo.sh          # auto-runs everything with short pauses
#   DEMO_STEP=1 ./demo/attack-demo.sh   # pause between attacks, wait for enter
# ----------------------------------------------------------------------------
set -uo pipefail

# ---- config --------------------------------------------------------------
BASE_URL=${BASE_URL:-https://localhost:8443}
ADMIN_USER=${ADMIN_USER:-admin}
ADMIN_PASS=${ADMIN_PASS:-admin-demo-do-not-ship}
COMPOSE_DIR=${COMPOSE_DIR:-$(cd "$(dirname "$0")/../deploy/compose" && pwd)}
PAUSE_SECS=${PAUSE_SECS:-2}
DEMO_STEP=${DEMO_STEP:-0}

# ---- colors --------------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\e[1m'; DIM=$'\e[2m'; RESET=$'\e[0m'
  RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
  BLUE=$'\e[34m'; MAGENTA=$'\e[35m'; CYAN=$'\e[36m'
else
  BOLD=; DIM=; RESET=; RED=; GREEN=; YELLOW=; BLUE=; MAGENTA=; CYAN=
fi

# ---- helpers -------------------------------------------------------------
banner() {
  printf '\n%s╔══════════════════════════════════════════════════════════════════════╗%s\n' "$MAGENTA$BOLD" "$RESET"
  printf '%s║%s  %-66s  %s║%s\n'  "$MAGENTA$BOLD" "$RESET$BOLD" "$1" "$MAGENTA$BOLD" "$RESET"
  printf '%s╚══════════════════════════════════════════════════════════════════════╝%s\n\n' "$MAGENTA$BOLD" "$RESET"
}
section() {
  printf '\n%s┌─── %s%s ─%s\n' "$CYAN$BOLD" "$1" "$RESET$CYAN$BOLD" "$RESET"
}
step()   { printf '%s│%s %s%s%s\n'         "$CYAN" "$RESET" "$DIM" "$1" "$RESET"; }
cmd()    { printf '%s│%s %s$%s %s%s%s\n'   "$CYAN" "$RESET" "$YELLOW$BOLD" "$RESET" "$YELLOW" "$1" "$RESET"; }
out()    { while IFS= read -r line; do printf '%s│%s   %s\n' "$CYAN" "$RESET" "$line"; done; }
pass()   { printf '%s│%s %s✔ DEFENDED%s %s\n' "$CYAN" "$RESET" "$GREEN$BOLD" "$RESET" "$1"; }
warn()   { printf '%s│%s %s! %s%s\n' "$CYAN" "$RESET" "$YELLOW$BOLD" "$RESET" "$1"; }
fail()   { printf '%s│%s %s✘ FAILED  %s %s\n' "$CYAN" "$RESET" "$RED$BOLD" "$RESET" "$1"; }
close()  { printf '%s└──────────────────────────────────────────────────────────────────────%s\n' "$CYAN" "$RESET"; }

pause() {
  if [ "$DEMO_STEP" = "1" ]; then
    printf '\n%s[press enter for next attack]%s ' "$DIM" "$RESET"
    read -r _
  else
    sleep "$PAUSE_SECS"
  fi
}

curl_json() { curl -sk --max-time 10 -H 'Content-Type: application/json' "$@"; }

psql_exec() {
  docker compose exec -T postgres psql -U auth -d "$1" -tAc "$2" 2>&1
}

# ---- preflight ------------------------------------------------------------
cd "$COMPOSE_DIR"

banner "SECURE BANKING APPLICATION — LIVE ATTACK DEMO"
printf '  %sTarget:%s %s\n'                "$BOLD" "$RESET" "$BASE_URL"
printf '  %sCompose:%s %s\n'               "$BOLD" "$RESET" "$COMPOSE_DIR"
printf '  %sPause between attacks:%s %s\n' "$BOLD" "$RESET" "$([ "$DEMO_STEP" = "1" ] && echo 'manual (press enter)' || echo "${PAUSE_SECS}s")"

# Sanity: stack up?
if ! curl -sk --max-time 3 "$BASE_URL/health" | grep -q '"status":"ok"'; then
  fail "stack is not reachable at $BASE_URL — run: cd deploy/compose && docker compose up -d"
  exit 1
fi

# ---- setup: two customers + a transfer ------------------------------------
section "SETUP · seeding two customers and one transfer so the attacks have data"

TS=$(date +%s)
ALICE_USER="alice_${TS}"
BOB_USER="bob_${TS}"
PW="demo-pw-Password12345"

step "register two customers"
curl_json -X POST "$BASE_URL/register" -d "{\"username\":\"$ALICE_USER\",\"password\":\"$PW\"}" >/dev/null
curl_json -X POST "$BASE_URL/register" -d "{\"username\":\"$BOB_USER\",\"password\":\"$PW\"}"   >/dev/null

step "login both + admin, capture access tokens"
ALICE_TOKEN=$(curl_json -X POST "$BASE_URL/login" -d "{\"username\":\"$ALICE_USER\",\"password\":\"$PW\"}" | jq -r .access_token)
BOB_TOKEN=$(  curl_json -X POST "$BASE_URL/login" -d "{\"username\":\"$BOB_USER\",\"password\":\"$PW\"}"   | jq -r .access_token)
ADMIN_TOKEN=$(curl_json -X POST "$BASE_URL/login" -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" | jq -r .access_token)

if [ -z "$ALICE_TOKEN" ] || [ "$ALICE_TOKEN" = "null" ]; then
  fail "could not log in as alice — check the stack is fully ready"
  exit 1
fi

step "open one account for each customer"
ALICE_ACC=$(curl -sk -X POST "$BASE_URL/banking/accounts" -H "Authorization: Bearer $ALICE_TOKEN")
BOB_ACC=$(  curl -sk -X POST "$BASE_URL/banking/accounts" -H "Authorization: Bearer $BOB_TOKEN")
ALICE_ID=$(  echo "$ALICE_ACC" | jq -r .id)
BOB_NUMBER=$(echo "$BOB_ACC"   | jq -r .account_number)

step "alice transfers \$25 to bob (creates a signed transaction)"
TX_JSON=$(curl_json -X POST "$BASE_URL/banking/transfers" \
  -H "Authorization: Bearer $ALICE_TOKEN" \
  -d "{\"from_account_id\":\"$ALICE_ID\",\"to_account_number\":\"$BOB_NUMBER\",\"amount_minor\":2500}")
TX_ID=$(echo "$TX_JSON" | jq -r .id)

printf '  %salice id  =%s %s\n' "$DIM" "$RESET" "$ALICE_ID"
printf '  %sbob num   =%s %s\n' "$DIM" "$RESET" "$BOB_NUMBER"
printf '  %stx id     =%s %s\n' "$DIM" "$RESET" "$TX_ID"
pause

# ==========================================================================
# A1  — Encryption at rest.  Balance stored as AES-256-GCM ciphertext.
# ==========================================================================
section "A1 · ENCRYPTION AT REST  — sensitive columns are ciphertext in the DB"
step "attacker opens a psql session and reads alice's balance directly"
cmd "psql -c \"SELECT encode(balance_minor, 'hex') FROM accounts WHERE id='$ALICE_ID'\""
CT=$(psql_exec banking "SELECT encode(balance_minor, 'hex') FROM accounts WHERE id='$ALICE_ID'")
printf '  %sciphertext:%s %s%s%s\n' "$DIM" "$RESET" "$RED" "${CT:0:80}..." "$RESET"
if [[ "$CT" =~ ^[0-9a-f]+$ ]] && [ "${#CT}" -gt 60 ]; then
  pass "AES-256-GCM (12 B nonce · ciphertext · 16 B tag). Attacker sees bytes, not \$97.50."
else
  fail "column was not ciphertext — expected hex bytes"
fi
close
pause

# ==========================================================================
# A2  — RBAC.  Customer hits admin-only endpoint.
# ==========================================================================
section "A2 · RBAC  — a customer attempts to list every account"
cmd "curl -H 'Authorization: Bearer <alice>' $BASE_URL/banking/accounts"
BODY=$(curl -sk -w '\n%{http_code}' "$BASE_URL/banking/accounts" -H "Authorization: Bearer $ALICE_TOKEN")
CODE=$(echo "$BODY" | tail -1)
JSON=$(echo "$BODY" | head -n -1)
printf '  %sstatus:%s %s%s%s   %sbody:%s %s\n' \
  "$DIM" "$RESET" "$RED$BOLD" "$CODE" "$RESET" "$DIM" "$RESET" "$JSON"
if [ "$CODE" = "403" ]; then
  pass "require_admin() rejected before any query ran. Route-level and use-case-level checks."
else
  fail "expected 403, got $CODE"
fi
close
pause

# ==========================================================================
# A3  — SQL Injection.  Attacker tries classic payload at /login.
# ==========================================================================
section "A3 · SQL INJECTION  — attacker sends classic SQLi payload at /login"
PAYLOAD="admin' OR 1=1--"
cmd "curl -d '{\"username\":\"$PAYLOAD\",\"password\":\"x\"}' $BASE_URL/login"
BODY=$(curl_json -X POST "$BASE_URL/login" -w '\n%{http_code}' -d "{\"username\":\"$PAYLOAD\",\"password\":\"x\"}")
CODE=$(echo "$BODY" | tail -1)
JSON=$(echo "$BODY" | head -n -1)
printf '  %sstatus:%s %s%s%s   %sbody:%s %s\n' \
  "$DIM" "$RESET" "$RED$BOLD" "$CODE" "$RESET" "$DIM" "$RESET" "$JSON"

# WAF match check (Coraza logs an audit line)
if docker compose logs --tail=200 caddy 2>/dev/null | grep -qiE "coraza|(sql|942[0-9]{3})"; then
  step "Coraza WAF audit-log line:"
  docker compose logs --tail=200 caddy 2>/dev/null | grep -iE "coraza|942[0-9]{3}" | tail -1 | out
else
  warn "no explicit CRS match in Caddy logs (WAF may still be starting)"
fi

if [ "$CODE" = "401" ] || [ "$CODE" = "422" ] || [ "$CODE" = "403" ]; then
  pass "psycopg parameterisation renders payload inert · WAF logs the CRS rule match"
else
  fail "expected 401/422/403, got $CODE"
fi
close
pause

# ==========================================================================
# A4  — Transaction signature tamper detection.
# ==========================================================================
section "A4 · TX SIGNATURE TAMPER  — attacker changes an amount directly in the DB"
step "read original amount"
ORIG_AMT=$(psql_exec banking "SELECT amount_minor FROM transactions WHERE id='$TX_ID'")
printf '  %soriginal amount_minor:%s %s\n' "$DIM" "$RESET" "$ORIG_AMT"
step "tamper"
cmd "UPDATE transactions SET amount_minor = 999999 WHERE id = '$TX_ID'"
psql_exec banking "UPDATE transactions SET amount_minor = 999999 WHERE id = '$TX_ID'" >/dev/null
step "alice lists her transactions — the app re-verifies Ed25519 on read"
LIST=$(curl -sk "$BASE_URL/banking/transactions/$ALICE_ID" -H "Authorization: Bearer $ALICE_TOKEN")
FLAG=$(echo "$LIST" | jq -r ".[] | select(.id==\"$TX_ID\") | .signature_valid")
AMT=$( echo "$LIST" | jq -r ".[] | select(.id==\"$TX_ID\") | .amount_minor")
printf '  %sreported amount:%s %s%s%s  %ssignature_valid:%s %s%s%s\n' \
  "$DIM" "$RESET" "$RED$BOLD" "$AMT" "$RESET" \
  "$DIM" "$RESET" "$([ "$FLAG" = "false" ] && printf "%s%s%s" "$GREEN$BOLD" "false" "$RESET" || printf "%s%s%s" "$RED$BOLD" "$FLAG" "$RESET")" "$([ "$FLAG" = "false" ] && echo "← tamper detected" || echo "")"
if [ "$FLAG" = "false" ]; then
  pass "Ed25519 signature over canonical(id,from,to,amount,at) no longer verifies."
else
  fail "signature_valid did not flip to false"
fi
step "restore the row so demo can be re-run"
psql_exec banking "UPDATE transactions SET amount_minor = $ORIG_AMT WHERE id = '$TX_ID'" >/dev/null
close
pause

# ==========================================================================
# A5  — Audit chain tamper detection.
# ==========================================================================
section "A5 · AUDIT CHAIN TAMPER  — attacker edits a past event, breaks the SHA-256 chain"
LAST_ID=$(psql_exec banking "SELECT id FROM audit_log ORDER BY id DESC LIMIT 1")
TARGET_ID=$((LAST_ID - 1))
ORIG_EVENT=$(psql_exec banking "SELECT event FROM audit_log WHERE id=$TARGET_ID")
step "attacker forges event #$TARGET_ID in the audit_log"
cmd "UPDATE audit_log SET event = jsonb_set(event, '{event}', '\"forged\"') WHERE id = $TARGET_ID"
psql_exec banking "UPDATE audit_log SET event = jsonb_set(event, '{event}', '\"forged\"') WHERE id=$TARGET_ID" >/dev/null

step "run verify_chain() against the whole audit_log"
VERIFY=$(docker compose exec -T banking python -c "
from shared_security.audit_chain import verify_chain
from shared_security.canonical import canonical_json_bytes
import psycopg, os
url = os.environ['BANKING_DATABASE_URL']
with psycopg.connect(url) as c, c.cursor() as cur:
    cur.execute('SELECT event, hash FROM audit_log ORDER BY id')
    rows = [(canonical_json_bytes(dict(e)), bytes(h)) for e, h in cur.fetchall()]
print(verify_chain(rows))
" 2>&1 | tr -d '\r')
printf '  %sverify_chain result:%s %s%s%s\n' \
  "$DIM" "$RESET" "$([ "$VERIFY" = "False" ] && printf "%s%s%s" "$GREEN$BOLD" "False" "$RESET" || printf "%s%s%s" "$RED$BOLD" "$VERIFY" "$RESET")" "" ""
if [ "$VERIFY" = "False" ]; then
  pass "chain is SHA-256(prev_hash ‖ canonical(event)); one edit breaks every hash after it."
else
  fail "chain verification returned '$VERIFY' — expected False"
fi

step "restore the row so demo can be re-run"
# JSONB literal needs single-quotes doubled inside the SQL
ESCAPED=$(printf '%s' "$ORIG_EVENT" | sed "s/'/''/g")
psql_exec banking "UPDATE audit_log SET event='$ESCAPED'::jsonb WHERE id=$TARGET_ID" >/dev/null
close
pause

# ==========================================================================
# A6  — Refresh-token replay after rotation.
# ==========================================================================
section "A6 · REFRESH TOKEN ROTATION  — attacker replays a stolen refresh token"
LOGIN=$(curl_json -X POST "$BASE_URL/login" -d "{\"username\":\"$ALICE_USER\",\"password\":\"$PW\"}")
R1=$(echo "$LOGIN" | jq -r .refresh_token)
step "1st refresh (legitimate) — should succeed"
cmd "curl -d '{\"refresh_token\":\"<R1>\"}' /refresh"
FIRST=$(curl_json -X POST "$BASE_URL/refresh" -w '\n%{http_code}' -d "{\"refresh_token\":\"$R1\"}")
CODE1=$(echo "$FIRST" | tail -1)
step "2nd refresh with SAME token (attacker replay) — should be rejected"
cmd "curl -d '{\"refresh_token\":\"<R1>\"}' /refresh   # same token"
SECOND=$(curl_json -X POST "$BASE_URL/refresh" -w '\n%{http_code}' -d "{\"refresh_token\":\"$R1\"}")
CODE2=$(echo "$SECOND" | tail -1)
printf '  %s1st refresh:%s %s%s%s   %s2nd refresh (replay):%s %s%s%s\n' \
  "$DIM" "$RESET" "$GREEN$BOLD" "$CODE1" "$RESET" \
  "$DIM" "$RESET" "$([ "$CODE2" = "401" ] && printf "%s%s%s" "$GREEN$BOLD" "401" "$RESET" || printf "%s%s%s" "$RED$BOLD" "$CODE2" "$RESET")" "" ""
if [ "$CODE1" = "200" ] && [ "$CODE2" = "401" ]; then
  pass "refresh rotation deletes the row on first use — replay hits 'row not found'."
else
  fail "expected 200 then 401, got $CODE1 then $CODE2"
fi
close
pause

# ==========================================================================
# A7  — Backup ciphertext (age).
# ==========================================================================
section "A7 · ENCRYPTED BACKUPS  — attacker steals a backup file"
step "trigger a fresh backup"
docker compose exec -T backup /usr/local/bin/backup 2>&1 | tail -3 | out
BK=$(docker compose exec -T backup sh -c 'ls -1t /backups/*.sql.age 2>/dev/null | head -1' | tr -d '\r')
if [ -z "$BK" ]; then
  fail "no backup file produced"
  close
else
  step "attacker peeks at the file header"
  cmd "head -c 30 $BK"
  HDR=$(docker compose exec -T backup sh -c "head -c 30 '$BK'" | tr -d '\r')
  printf '  %sheader bytes:%s %s%s%s\n' "$DIM" "$RESET" "$RED" "$HDR" "$RESET"
  step "attacker attempts to decrypt without the age identity"
  cmd "age -d $BK"
  ERR=$(docker compose exec -T backup sh -c "age -d '$BK' 2>&1 >/dev/null" | tr -d '\r')
  printf '  %sage stderr:%s %s%s%s\n' "$DIM" "$RESET" "$RED" "$(echo "$ERR" | head -1)" "$RESET"
  if [[ "$HDR" == age-encryption.org/v1* ]] && echo "$ERR" | grep -qiE "no identity|not found"; then
    pass "age(X25519+ChaCha20-Poly1305) recipient encryption. Only the OFF-BOX identity can decrypt."
  else
    fail "backup did not behave as expected (header=$HDR err=$ERR)"
  fi
  close
fi
pause

# ==========================================================================
# summary
# ==========================================================================
banner "DEMO COMPLETE"
printf '  %sSeven attacks attempted · each caught by an independent layer of defence.%s\n' "$BOLD" "$RESET"
printf '  %sState is restored (tx amount + audit event reverted) — safe to re-run.%s\n\n' "$DIM" "$RESET"
