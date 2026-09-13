<#
.SYNOPSIS
  Share the running app over a temporary Cloudflare quick tunnel.

.DESCRIPTION
  Starts Docker Desktop if needed, brings up the whole stack from the current
  code, waits until the app answers, then opens a quick tunnel and prints a
  public https://....trycloudflare.com link.

  THE LINK HAS NO LOGIN. The app trusts whatever pseudonym the browser sends,
  so anyone holding the link can use it as any teacher or student. Send it
  directly to one person, and press Ctrl+C to close the tunnel when you are
  done. The data is the fictional seed lesson; nothing real should be in it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\share.ps1
  powershell -ExecutionPolicy Bypass -File scripts\share.ps1 -Stop
#>
param(
    # Stop the app containers instead of sharing.
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if ($Stop) {
    docker compose stop
    Write-Host "App stopped."
    exit 0
}

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "cloudflared is not installed. Install it once with:" -ForegroundColor Yellow
    Write-Host "  winget install --id Cloudflare.cloudflared"
    Write-Host "then open a new terminal and run this script again."
    exit 1
}

# Docker Desktop is not always running after a restart.
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $deadline = (Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 3
        docker info *> $null
    } until ($LASTEXITCODE -eq 0 -or (Get-Date) -gt $deadline)
    if ($LASTEXITCODE -ne 0) { throw "Docker Desktop did not start within 3 minutes." }
}

# --build so the shared app is always the current code, not an old image.
Write-Host "Building and starting the app (first time takes a few minutes)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw "docker compose failed." }

Write-Host "Waiting for the app to answer on port 3000..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
do {
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 5
        $ready = $r.StatusCode -eq 200
    } catch { Start-Sleep -Seconds 3 }
} until ($ready -or (Get-Date) -gt $deadline)
if (-not $ready) { throw "The app did not come up on http://127.0.0.1:3000." }

Write-Host ""
Write-Host "==================================================================" -ForegroundColor Yellow
Write-Host " Opening a PUBLIC tunnel. The link has NO LOGIN." -ForegroundColor Yellow
Write-Host " Send it only to the person you are showing. Ctrl+C closes it."    -ForegroundColor Yellow
Write-Host " Look for the https://....trycloudflare.com line below."           -ForegroundColor Yellow
Write-Host " Afterwards, stop the app with: scripts\share.ps1 -Stop"            -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Yellow
Write-Host ""

# 127.0.0.1, not localhost: localhost resolves to IPv6 first on Windows.
cloudflared tunnel --url http://127.0.0.1:3000
