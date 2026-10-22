<#
.SYNOPSIS
    Start the local Researchers Network stack (Neo4j + FastAPI + React).

.DESCRIPTION
    A day-to-day launcher, not the reproducible pipeline. It:
      1. starts Docker Desktop if the engine is not running,
      2. starts the Neo4j container and waits for its healthcheck,
      3. starts the FastAPI backend on port 8000 if it is not already running,
      4. starts the Vite dev server on port 5173 if it is not already running,
      5. opens http://localhost:5173 in the default browser.

    Data and analysis results already live on this machine, so no crawl or
    recomputation is needed. Use -RebuildGds only when you want to rerun the
    GDS analyses after a Neo4j restart (projections are in-memory).

.PARAMETER NoBrowser
    Start the servers but do not open the browser.

.PARAMETER Stop
    Stop the API, the Vite dev server and the Neo4j container, then exit.

.PARAMETER RebuildGds
    Recreate the in-memory GDS projections before starting the API. Needed only
    when rerunning analysis scripts, not for normal viewing.

.EXAMPLE
    .\start.ps1

.EXAMPLE
    .\start.ps1 -NoBrowser
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$Stop,
    [switch]$RebuildGds
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Container = "researchers-network-neo4j"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Frontend = Join-Path $Root "frontend"
$ApiUrl = "http://127.0.0.1:8000"
$WebUrl = "http://127.0.0.1:5173"
$ApiLog = Join-Path $env:TEMP "researchers-network-api.log"
$ApiErr = Join-Path $env:TEMP "researchers-network-api.err.log"
$WebLog = Join-Path $env:TEMP "researchers-network-web.log"
$WebErr = Join-Path $env:TEMP "researchers-network-web.err.log"

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Resolve-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Http([string]$Url, [int]$TimeoutSeconds = 90) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) { return $true }
        } catch {
            # Server not ready yet; keep waiting.
        }
        Start-Sleep -Seconds 2
    }
    return $false
}

# --- Preconditions ----------------------------------------------------------
if (-not (Test-Path $Python)) {
    throw "Python environment missing. Follow the Setup section of README.md first (python -m venv .venv; pip install -e `".[dev]`")."
}
if (-not (Test-Path (Join-Path $Frontend "node_modules\vite"))) {
    throw "Frontend dependencies missing. Run: cd frontend; npm.cmd install"
}
$docker = Resolve-Docker
if (-not $docker) {
    throw "Docker CLI not found. Install Docker Desktop, then run this script again."
}

# --- Stop mode --------------------------------------------------------------
if ($Stop) {
    Write-Step "Stopping the local servers"
    foreach ($port in @(8000, 5173)) {
        $connections = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
        foreach ($connection in $connections) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped process on port $port."
        }
    }
    & $docker compose stop
    Write-Host "Neo4j stopped (data is kept in the Docker volume)." -ForegroundColor Green
    return
}

# --- Docker Desktop ---------------------------------------------------------
Write-Step "Checking Docker Desktop"
& $docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $desktopCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    $desktop = $desktopCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $desktop) {
        throw "Docker Desktop is installed but its engine is not running, and the app could not be found. Start Docker Desktop manually."
    }
    Write-Host "Starting Docker Desktop (this can take a minute)..."
    Start-Process $desktop | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        & $docker info *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 3
    }
    if (-not $ready) { throw "Docker engine did not start within 3 minutes. Open Docker Desktop and check for errors." }
}

# --- Neo4j ------------------------------------------------------------------
Write-Step "Starting Neo4j"
& $docker compose up -d
if ($LASTEXITCODE -ne 0) { throw "docker compose up -d failed. Run it manually in $Root to see the error." }

Write-Host "Waiting for the Neo4j healthcheck (first boot also downloads GDS)..."
$healthy = $false
for ($i = 0; $i -lt 200; $i++) {
    $status = (& $docker inspect --format "{{.State.Health.Status}}" $Container 2>$null)
    if ($LASTEXITCODE -eq 0 -and $status.Trim() -eq "healthy") { $healthy = $true; break }
    Start-Sleep -Seconds 3
}
if (-not $healthy) {
    throw "Neo4j did not become healthy within 10 minutes. Check: docker compose logs neo4j"
}
Write-Host "Neo4j is healthy." -ForegroundColor Green

if ($RebuildGds) {
    Write-Step "Rebuilding in-memory GDS projections"
    & $Python -m analysis.load_neo4j --gds-only
    if ($LASTEXITCODE -ne 0) { throw "GDS projection rebuild failed." }
}

# --- FastAPI ----------------------------------------------------------------
Write-Step "Starting the FastAPI backend"
if (Test-Port 8000) {
    Write-Host "Port 8000 is already in use; assuming the API is running."
} else {
    Start-Process -FilePath $Python `
        -ArgumentList "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000" `
        -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput $ApiLog -RedirectStandardError $ApiErr
}
if (-not (Wait-Http "$ApiUrl/api/health" 90)) {
    if (Test-Path $ApiErr) { Get-Content $ApiErr -Tail 20 }
    throw "The API did not become ready at $ApiUrl. See $ApiErr"
}
Write-Host "API ready: $ApiUrl/docs" -ForegroundColor Green

# --- React frontend ---------------------------------------------------------
Write-Step "Starting the React frontend"
if (Test-Port 5173) {
    Write-Host "Port 5173 is already in use; assuming the dev server is running."
} else {
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173" `
        -WorkingDirectory $Frontend -WindowStyle Hidden `
        -RedirectStandardOutput $WebLog -RedirectStandardError $WebErr
}
if (-not (Wait-Http $WebUrl 90)) {
    if (Test-Path $WebErr) { Get-Content $WebErr -Tail 20 }
    throw "The frontend did not become ready at $WebUrl. See $WebErr"
}
Write-Host "UI ready: $WebUrl" -ForegroundColor Green

if (-not $NoBrowser) { Start-Process $WebUrl | Out-Null }

Write-Host ""
Write-Host "Everything is running." -ForegroundColor Green
Write-Host "  UI:      $WebUrl"
Write-Host "  API:     $ApiUrl/docs"
Write-Host "  Neo4j:   http://localhost:7474"
Write-Host ""
Write-Host "To stop everything: .\start.ps1 -Stop"
