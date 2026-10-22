"""Health endpoint: API, result files and Neo4j status in one call."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from backend import __version__
from backend.deps import get_graph, get_store
from backend.services.graph import Neo4jGraph
from backend.store import ResultStore

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    summary="API health, available result files and Neo4j status",
)
async def health(
    store: ResultStore = Depends(get_store),
    graph: Neo4jGraph = Depends(get_graph),
) -> dict[str, Any]:
    """Always returns 200 when the API itself is alive.

    Neo4j being down is reported in `neo4j.available`, not as an HTTP error:
    the analytical endpoints keep working from the result files.
    """
    return {
        "status": "ok",
        "service": "Pakistan's Researchers Network API",
        "version": __version__,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "results": store.status(),
        "assignments_loaded": store.assignment_count(),
        "neo4j": await graph.ping(),
    }
