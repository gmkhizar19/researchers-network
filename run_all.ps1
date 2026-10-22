<#
.SYNOPSIS
    Run the Pakistan's Researchers Network pipeline stage by stage.

.DESCRIPTION
    Stages (run in this order for a full rebuild):
      data      crawl OpenAlex (unless -SkipFetch), clean, build CSV/GraphML, validate
      neo4j     start Neo4j + GDS, load the CSVs, verify counts, build projections
      analysis  Problem 1 (fragility), Problem 2 (silos/link prediction), Problem 3 (reviewers)
      test      pytest suite (the live-Neo4j test skips if the container is down)
      frontend  npm install if needed, then npm run build
      backend   start the FastAPI server on http://127.0.0.1:8000 (blocking)
      all       data -> neo4j -> analysis -> test -> frontend -> backend import check

    The 'all' stage does NOT leave servers running. Start them separately with
    -Stage backend and `npm run dev`.

.PARAMETER Stage
    Which stage to run. Default: all.

.PARAMETER SkipFetch
    Reuse the submitted data/raw cache; only run clean + build + validate.
    This is the reproducible path for the submitted dataset (no network needed).

.PARAMETER ResetNeo4j
    Pass --reset to analysis/load_neo4j.py (deletes existing nodes and projections).

.PARAMETER SkipNull
    Skip the Problem 1 configuration-model null model (faster, but the null
    comparison is then missing from the output).

.PARAMETER ForceFrontendInstall
    Run npm install even when frontend/node_modules already exists.

.EXAMPLE
    .\run_all.ps1 -Stage all -SkipFetch
    Full reproducibility run from the submitted raw data.

.EXAMPLE
    .\run_all.ps1 -Stage analysis
    Recompute the three analyses (requires Neo4j + GDS).

.EXAMPLE
    .\run_all.ps1 -Stage frontend
    Build the React app only.
#>
[CmdletBinding()]
param(
    [ValidateSet("all", "data", "neo4j", "analysis", "test", "frontend", "backend")]
    [string]$Stage = "all",

    [switch]$SkipFetch,
    [switch]$ResetNeo4j,
    [switch]$SkipNull,
    [switch]$ForceFrontendInstall
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Container = "researchers-network-neo4j"
$FrontendDir = Join-Path $Root "frontend"
$StartedAt = Get-Date

# Docker Desktop often installs its CLI outside PATH on Windows. Find it.
function Resolve-Docker {
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Write-Banner([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
}

function Assert-Preconditions {
    $needsPython = $Stage -in @("all", "data", "neo4j", "analysis", "test", "backend")
    $needsEnv = $Stage -in @("all", "data", "neo4j", "analysis", "backend")

    if ($needsPython -and -not (Test-Path $Python)) {
        throw "Python venv not found at .venv\Scripts\python.exe. Create it with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e `".[dev]`""
    }
    if ($needsEnv -and -not (Test-Path (Join-Path $Root ".env"))) {
        throw "Missing .env. Copy .env.example to .env and set OPENALEX_EMAIL (never commit the real value)."
    }
}

function Invoke-Python([string]$Label, [string[]]$Arguments) {
    Write-Banner $Label
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed (exit code $LASTEXITCODE)."
    }
}

function Assert-Neo4jReachable {
    Write-Banner "Checking Neo4j connection"
    & $Python -c "from analysis.common.neo4j_client import get_driver; d = get_driver(); d.close(); print('Neo4j reachable')"
    if ($LASTEXITCODE -ne 0) {
        throw "Cannot reach Neo4j. Start it with 'docker compose up -d' (or run -Stage neo4j). Check NEO4J_* in .env."
    }
}

function Wait-ForNeo4j([int]$TimeoutSeconds = 600) {
    Write-Host "Waiting for the container healthcheck..." -ForegroundColor Yellow
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $status = (& $script:Docker inspect --format "{{.State.Health.Status}}" $Container 2>$null)
        if ($LASTEXITCODE -eq 0 -and $status.Trim() -eq "healthy") {
            Write-Host "Neo4j is healthy." -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 3
    }
    throw "Neo4j did not become healthy within $TimeoutSeconds seconds. Run: docker compose logs neo4j"
}

function Run-Data {
    if ($SkipFetch) {
        Write-Host "SkipFetch: reusing the submitted data/raw cache." -ForegroundColor Yellow
        Invoke-Python "Stage 1b: clean raw data" @("-m", "crawler.cli", "clean")
        Invoke-Python "Stage 1c: build the collaboration graph" @("-m", "crawler.cli", "build")
    }
    else {
        Invoke-Python "Stage 1: fetch + clean + build" @("-m", "crawler.cli", "all")
    }
    Invoke-Python "Stage 1d: validate the grading requirements" @("-m", "crawler.cli", "validate")
}

function Run-Neo4j {
    if (-not $script:Docker) {
        throw "Docker CLI not found. Install Docker Desktop and make sure 'docker' is on PATH (the script also checks the default install folders)."
    }
    Write-Banner "Stage 2a: start Neo4j 5.26 + GDS"
    & $script:Docker compose up -d
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed. Is Docker Desktop running?"
    }
    Wait-ForNeo4j

    $loadArguments = @("-m", "analysis.load_neo4j")
    if ($ResetNeo4j) {
        $loadArguments += "--reset"
    }
    Invoke-Python "Stage 2b: load CSVs, verify counts, create GDS projections" $loadArguments
}

function Run-Analysis {
    Assert-Neo4jReachable

    $p1Arguments = @("-m", "analysis.p1_fragility")
    if ($SkipNull) {
        $p1Arguments += "--skip-null"
    }
    Invoke-Python "Stage 3: Problem 1 - fragility" $p1Arguments
    Invoke-Python "Stage 4: Problem 2 - silos and link prediction" @("-m", "analysis.p2_silos_linkpred")
    Invoke-Python "Stage 5: Problem 3 - reviewer assignment" @("-m", "analysis.p3_reviewers")
}

function Run-Tests {
    Invoke-Python "Stage 6 check: pytest suite" @("-m", "pytest")
}

function Run-Frontend {
    if (-not $script:Npm) {
        throw "npm not found. Install Node.js 18+ and reopen the terminal."
    }
    $nodeModules = Join-Path $FrontendDir "node_modules"
    $viteMarker = Join-Path $nodeModules "vite"

    if ((-not (Test-Path $nodeModules)) -or $ForceFrontendInstall) {
        Write-Banner "Stage 7a: install frontend dependencies"
        Push-Location $FrontendDir
        try {
            & $script:Npm install --no-audit --no-fund
            if ($LASTEXITCODE -ne 0 -and -not (Test-Path $viteMarker)) {
                throw "npm install failed (exit code $LASTEXITCODE)."
            }
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "npm reported a script-policy warning, but node_modules/vite exists; continuing."
            }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "frontend/node_modules already present (use -ForceFrontendInstall to reinstall)." -ForegroundColor DarkGray
    }

    Write-Banner "Stage 7b: production build"
    Push-Location $FrontendDir
    try {
        & $script:Npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "npm run build failed (exit code $LASTEXITCODE)."
        }
    }
    finally {
        Pop-Location
    }
}

function Test-BackendImport {
    Invoke-Python "Stage 6 check: import the FastAPI app" @(
        "-c",
        "from backend.main import create_app; app = create_app(); print(f'API ready: {len(app.routes)} routes')"
    )
}

function Start-Backend {
    Write-Banner "Starting FastAPI on http://127.0.0.1:8000 (Ctrl+C to stop)"
    & $Python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
}

# --- dispatch ---------------------------------------------------------------

Assert-Preconditions

$script:Docker = Resolve-Docker
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
    $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
}
$script:Npm = if ($npmCommand) { $npmCommand.Source } else { $null }

switch ($Stage) {
    "data" { Run-Data }
    "neo4j" { Run-Neo4j }
    "analysis" { Run-Analysis }
    "test" { Run-Tests }
    "frontend" { Run-Frontend }
    "backend" { Start-Backend; break }
    "all" {
        Run-Data
        Run-Neo4j
        Run-Analysis
        Run-Tests
        Run-Frontend
        Test-BackendImport
    }
}

if ($Stage -ne "backend") {
    $minutes = [math]::Round(((Get-Date) - $StartedAt).TotalMinutes, 1)
    Write-Banner "Done: stage '$Stage' finished in $minutes min"
    Write-Host "Start the API:  .\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload"
    Write-Host "Start the UI:   cd frontend; npm run dev    (http://localhost:5173)"
    Write-Host "Screenshots:    cd frontend; npm run screenshots  (API + dev server must be running)"
}
