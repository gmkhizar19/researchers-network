"""Problem 2 (collaboration prediction): time-split scores and recommendations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["link-prediction"])


@router.get(
    "/link-predictions",
    summary="Problem 2: link-prediction benchmark and top recommendations",
)
def link_predictions(store: ResultStore = Depends(get_store)) -> dict[str, Any]:
    """AUC / precision@k for Adamic-Adar, common neighbours and Jaccard.

    The split is temporal: features from pairs whose first shared paper is
    <= 2020, evaluation on real 2021+ collaborations.
    """
    result = store.json("p2_silos_linkprediction")
    return {
        "time_split": result["time_split"],
        "static_benchmark": result["link_prediction_static"],
        "gds_nodesimilarity": result["link_prediction_gds_nodesim"],
        "recommendations_top20": result["recommendations_top20"],
        "source": "data/results/p2_silos_linkprediction.json",
    }
