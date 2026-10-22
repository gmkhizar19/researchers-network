#!/usr/bin/env bash
#
# Run the Pakistan's Researchers Network pipeline stage by stage.
#
# Stages:
#   data      crawl OpenAlex (unless --skip-fetch), clean, build CSV/GraphML, validate
#   neo4j     start Neo4j + GDS, load the CSVs, verify counts, build projections
#   analysis  Problem 1, Problem 2, Problem 3
#   test      pytest suite (live-Neo4j test skips when the container is down)
#   frontend  npm install if needed, then npm run build
#   backend   start FastAPI on http://127.0.0.1:8000 (blocking)
#   all       data -> neo4j -> analysis -> test -> frontend -> backend import check
#
# Examples:
#   ./run_all.sh --stage all --skip-fetch
#   ./run_all.sh --stage analysis
#   ./run_all.sh --stage frontend
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

STAGE="all"
SKIP_FETCH=0
RESET_NEO4J=0
SKIP_NULL=0
FORCE_INSTALL=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --stage)
      STAGE="${2:-}"
      shift 2
      ;;
    --stage=*)
      STAGE="${1#*=}"
      shift
      ;;
    --skip-fetch)
      SKIP_FETCH=1
      shift
      ;;
    --reset-neo4j)
      RESET_NEO4J=1
      shift
      ;;
    --skip-null)
      SKIP_NULL=1
      shift
      ;;
    --force-frontend-install)
      FORCE_INSTALL=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

case "$STAGE" in
  all|data|neo4j|analysis|test|frontend|backend) ;;
  *)
    echo "Invalid stage: $STAGE (choose all, data, neo4j, analysis, test, frontend, backend)" >&2
    exit 2
    ;;
esac

CONTAINER="researchers-network-neo4j"
FRONTEND="$ROOT/frontend"
STARTED_AT=$(date +%s)

# The venv is bin/python on Linux/macOS and Scripts/python.exe on Git Bash.
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
else
  PY=""
fi

NPM_BIN="$(command -v npm || true)"
DOCKER_BIN="${DOCKER_BIN:-$(command -v docker || true)}"
if [ -z "$DOCKER_BIN" ] && [ -x "/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]; then
  DOCKER_BIN="/c/Program Files/Docker/Docker/resources/bin/docker.exe"
fi

banner() {
  echo
  echo "=========================================================================="
  echo "$1"
  echo "=========================================================================="
}

fail() {
  echo "FAILED: $1" >&2
  exit 1
}

run_py() {
  local label="$1"
  shift
  banner "$label"
  "$PY" "$@" || fail "$label"
}

assert_python() {
  [ -n "$PY" ] && [ -x "$PY" ] || fail "Python venv missing (.venv/bin/python or .venv/Scripts/python.exe). See README 'Setup'."
}

assert_env() {
  [ -f "$ROOT/.env" ] || fail "Missing .env. Copy .env.example to .env and set OPENALEX_EMAIL."
}

assert_neo4j_reachable() {
  banner "Checking Neo4j connection"
  "$PY" -c "from analysis.common.neo4j_client import get_driver; d = get_driver(); d.close(); print('Neo4j reachable')" \
    || fail "Cannot reach Neo4j. Start it with 'docker compose up -d' (or --stage neo4j)."
}

wait_for_neo4j() {
  echo "Waiting for the container healthcheck..."
  local deadline=$((SECONDS + 180))
  while [ $SECONDS -lt $deadline ]; do
    status="$("$DOCKER_BIN" inspect --format '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      echo "Neo4j is healthy."
      return 0
    fi
    sleep 3
  done
  echo "Neo4j did not become healthy within 180 seconds. Run: docker compose logs neo4j" >&2
  return 1
}

run_data() {
  if [ "$SKIP_FETCH" -eq 1 ]; then
    echo "SkipFetch: reusing the submitted data/raw cache."
    run_py "Stage 1b: clean raw data" -m crawler.cli clean
    run_py "Stage 1c: build the collaboration graph" -m crawler.cli build
  else
    run_py "Stage 1: fetch + clean + build" -m crawler.cli all
  fi
  run_py "Stage 1d: validate the grading requirements" -m crawler.cli validate
}

run_neo4j() {
  [ -n "$DOCKER_BIN" ] || fail "Docker CLI not found. Install Docker Desktop and make sure 'docker' is on PATH."
  banner "Stage 2a: start Neo4j 5.26 + GDS"
  "$DOCKER_BIN" compose up -d || fail "docker compose up failed. Is Docker Desktop running?"
  wait_for_neo4j || exit 1

  load_args=(-m analysis.load_neo4j)
  if [ "$RESET_NEO4J" -eq 1 ]; then
    load_args+=(--reset)
  fi
  run_py "Stage 2b: load CSVs, verify counts, create GDS projections" "${load_args[@]}"
}

run_analysis() {
  assert_neo4j_reachable

  p1_args=(-m analysis.p1_fragility)
  if [ "$SKIP_NULL" -eq 1 ]; then
    p1_args+=(--skip-null)
  fi
  run_py "Stage 3: Problem 1 - fragility" "${p1_args[@]}"
  run_py "Stage 4: Problem 2 - silos and link prediction" -m analysis.p2_silos_linkpred
  run_py "Stage 5: Problem 3 - reviewer assignment" -m analysis.p3_reviewers
}

run_tests() {
  run_py "Stage 6 check: pytest suite" -m pytest
}

run_frontend() {
  [ -n "$NPM_BIN" ] || fail "npm not found. Install Node.js 18+ and reopen the terminal."

  if [ ! -d "$FRONTEND/node_modules" ] || [ "$FORCE_INSTALL" -eq 1 ]; then
    banner "Stage 7a: install frontend dependencies"
    if ! (cd "$FRONTEND" && "$NPM_BIN" install --no-audit --no-fund); then
      if [ -d "$FRONTEND/node_modules/vite" ]; then
        echo "npm reported an install-script warning, but node_modules/vite exists; continuing." >&2
      else
        fail "npm install failed."
      fi
    fi
  else
    echo "frontend/node_modules already present (use --force-frontend-install to reinstall)."
  fi

  banner "Stage 7b: production build"
  (cd "$FRONTEND" && "$NPM_BIN" run build) || fail "npm run build failed."
}

check_backend() {
  run_py "Stage 6 check: import the FastAPI app" -c \
    "from backend.main import create_app; app = create_app(); print(f'API ready: {len(app.routes)} routes')"
}

start_backend() {
  banner "Starting FastAPI on http://127.0.0.1:8000 (Ctrl+C to stop)"
  "$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
}

# --- dispatch ---------------------------------------------------------------

case "$STAGE" in
  data)
    assert_python
    assert_env
    run_data
    ;;
  neo4j)
    assert_python
    assert_env
    run_neo4j
    ;;
  analysis)
    assert_python
    assert_env
    run_analysis
    ;;
  test)
    assert_python
    run_tests
    ;;
  frontend)
    run_frontend
    ;;
  backend)
    assert_python
    assert_env
    start_backend
    exit 0
    ;;
  all)
    assert_python
    assert_env
    run_data
    run_neo4j
    run_analysis
    run_tests
    run_frontend
    check_backend
    ;;
esac

FINISHED_AT=$(date +%s)
echo
banner "Done: stage '$STAGE' finished in $(( (FINISHED_AT - STARTED_AT) / 60 )) min"
echo "Start the API:  .venv/bin/python -m uvicorn backend.main:app --reload"
echo "Start the UI:   cd frontend && npm run dev    (http://localhost:5173)"
echo "Screenshots:    cd frontend && npm run screenshots  (API + dev server must be running)"
