# Windows PowerShell wrapper for the attack demo.
#
# Prerequisite: the banking stack is already running.
#   cd deploy\compose
#   docker compose up -d --build
#
# Then, from the repository root:
#   .\demo\run.ps1                 # auto-paced (~40 s)
#   .\demo\run.ps1 -Step            # wait for [Enter] between attacks
#   .\demo\run.ps1 -Pause 5         # 5-second pause between attacks

param(
    [switch]$Step,
    [int]$Pause = 2
)

$ErrorActionPreference = 'Stop'

# Locate the repo root (one level up from this script)
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)

Write-Host "Building demo-attacker image..." -ForegroundColor Cyan
docker build -q -t demo-attacker -f "$RepoRoot\demo\Dockerfile" "$RepoRoot\demo" | Out-Null

$EnvArgs = @('-e', "PAUSE_SECS=$Pause")
if ($Step) { $EnvArgs += @('-e', 'DEMO_STEP=1') }

Write-Host "Running attacks..." -ForegroundColor Cyan
docker run --rm -it `
    -v /var/run/docker.sock:/var/run/docker.sock `
    -v "${RepoRoot}:/repo" `
    --add-host=host.docker.internal:host-gateway `
    @EnvArgs `
    demo-attacker
