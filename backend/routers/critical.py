"""Ranked critical researchers (Problem 1)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["fragility"])

SortKey = Literal["betweenness", "pagerank", "degree", "kcore", "strength"]


@router.get("/critical", summary="Ranked critical researchers from Problem 1")
def critical(
    limit: int = Query(20, ge=1, le=500, description="How many authors to return."),
    sort: SortKey = Query("betweenness", description="Ranking metric."),
    articulation_only: bool = Query(
        False, description="Keep only articulation points (network cut vertices)."
    ),
    store: ResultStore = Depends(get_store),
) -> dict[str, Any]:
    """Authors ranked by the chosen centrality, with articulation flags.

    The CSV is produced by `analysis/p1_fragility.py` and contains the top 100
    authors by betweenness (not all 14,574). Sorting by another metric reorders
    that exported subset; the UI and docs say so explicitly.
    """
    rows = store.critical_authors()
    if articulation_only:
        rows = [row for row in rows if row["is_articulation"]]
    rows.sort(key=lambda row: (-row[sort], row["name"]))
    context = store.json("p1_fragility")
    return {
        "sort": sort,
        "articulation_only": articulation_only,
        "total_available": len(rows),
        "items": rows[:limit],
        "context": {
            "articulation_points": context["articulation"],
            "bridges": context["bridges"]["count"],
            "max_kcore": context["kcore"]["max"],
            "max_flow": context["maxflow"]["max_flow"],
            "max_flow_between": {
                "source": context["maxflow"]["source"],
                "target": context["maxflow"]["target"],
            },
        },
    }
