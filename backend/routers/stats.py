"""Dataset statistics: what was crawled, cleaned and loaded into Neo4j."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["dataset"])


@router.get("/stats", summary="Dataset scale, connectivity and Neo4j load check")
def stats(store: ResultStore = Depends(get_store)) -> dict[str, Any]:
    """Serve the Stage 1 counts and the Stage 2 load verification.

    Every number is read from `data/results/stage1_stats.json` and
    `data/results/neo4j_verification.json`; nothing is recomputed here.
    """
    stage1 = store.json("stage1_stats")
    load = store.json("neo4j_verification")
    return {
        "source": {
            "name": "OpenAlex",
            "url": "https://api.openalex.org",
            "licence": "CC0 1.0 Universal",
        },
        "dataset": {
            "nodes": stage1["nodes"],
            "edges": stage1["edges"],
            "connectivity": stage1["connectivity"],
            "core_graph": stage1["core_graph"],
            "degree": stage1["degree"],
            "edge_weight": stage1["edge_weight"],
        },
        "top_by_degree": stage1["top_by_degree"],
        "neo4j_load": {
            "neo4j_version": load["neo4j_version"],
            "passed": load["passed"],
            "counts": load["counts"],
            "gds": {
                "gds_version": load["gds"]["gds_version"],
                "graphs": load["gds"]["graphs"],
            },
        },
    }
