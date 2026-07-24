#!/usr/bin/env bash
# Cross-platform wrapper for the attack demo. Works on Linux, macOS, and WSL.
#
# Prerequisite: the banking stack is already running.
#   cd deploy/compose && docker compose up -d --build
#
# Then, from the repository root:
#   ./demo/run.sh              # auto-paced (~40 s)
#   ./demo/run.sh --step       # wait for [Enter] between attacks
#   PAUSE_SECS=5 ./demo/run.sh # 5-second pause between attacks
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

STEP_ARGS=()
if [ "${1:-}" = "--step" ]; then STEP_ARGS+=(-e "DEMO_STEP=1"); fi
if [ -n "${PAUSE_SECS:-}" ]; then STEP_ARGS+=(-e "PAUSE_SECS=$PAUSE_SECS"); fi

echo "Building demo-attacker image..."
docker build -q -t demo-attacker -f "$REPO_ROOT/demo/Dockerfile" "$REPO_ROOT/demo" >/dev/null

echo "Running attacks..."
TTY_ARGS=()
if [ -t 0 ] && [ -t 1 ]; then TTY_ARGS+=(-it); fi
docker run --rm "${TTY_ARGS[@]}" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$REPO_ROOT:/repo" \
    --add-host=host.docker.internal:host-gateway \
    "${STEP_ARGS[@]}" \
    demo-attacker
