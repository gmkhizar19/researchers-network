"""Problem 1 (fragility): centrality, bridges, k-core, cascades and the null model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["fragility"])


@router.get("/fragility", summary="Problem 1: fragility metrics and cascade curves")
def fragility(store: ResultStore = Depends(get_store)) -> dict[str, Any]:
    """Serve the Stage 3 fragility results.

    `cascade.curves` holds the LCC fraction after removing 0-10% of nodes by
    betweenness, degree, PageRank and at random (20 replicates). The ranked
    author list has its own endpoint: `/api/critical`.
    """
    result = store.json("p1_fragility")
    keep = (
        "graph",
        "graph_note",
        "cascade",
        "damage_summary",
        "distances",
        "articulation",
        "bridges",
        "kcore",
        "clustering",
        "null_model",
        "maxflow",
    )
    return {**{key: result[key] for key in keep}, "source": "data/results/p1_fragility.json"}
