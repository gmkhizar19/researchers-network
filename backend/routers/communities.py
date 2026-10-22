"""Problem 2 (silos): Louvain communities and their internal cohesion."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["silos"])


@router.get("/communities", summary="Problem 2: communities, modularity and silos")
def communities(store: ResultStore = Depends(get_store)) -> dict[str, Any]:
    """Louvain summary, detected silos and the 20 largest communities."""
    result = store.json("p2_silos_linkprediction")
    return {
        "louvain": result["louvain"],
        "silos": result["silos"],
        "communities_top20": result["communities_top20"],
        "source": "data/results/p2_silos_linkprediction.json",
    }
