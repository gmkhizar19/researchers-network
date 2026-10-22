"""Problem 3 (reviewer assignment): metrics and the assignment table."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.deps import get_store
from backend.store import ResultStore

router = APIRouter(tags=["reviewers"])


@router.get(
    "/reviewers/metrics",
    summary="Problem 3: assignment quality, constraints and baselines",
)
def reviewer_metrics(store: ResultStore = Depends(get_store)) -> dict[str, Any]:
    """Scope, COI eligibility, optimal/flow/Hungarian/random comparison."""
    result = store.json("p3_reviewers")
    return {
        "scope": result["scope"],
        "eligibility": result["eligibility"],
        "min_cost_flow": result["min_cost_flow"],
        "hungarian_uncapacitated": result["hungarian_uncapacitated"],
        "random_baseline": result["random_baseline"],
        "comparison": result["comparison"],
        "infeasible_papers": result["infeasible_papers"],
        "runtime_seconds": result["runtime_seconds"],
        "source": "data/results/p3_reviewers.json",
    }


@router.get(
    "/reviewers/assignments",
    summary="Problem 3: paper -> reviewer assignments (filterable, paginated)",
)
def reviewer_assignments(
    paper_id: str | None = Query(None, description="Filter by OpenAlex paper id."),
    reviewer_id: str | None = Query(None, description="Filter by OpenAlex author id."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    store: ResultStore = Depends(get_store),
) -> dict[str, Any]:
    """Rows of `p3_reviewer_assignments.csv` (1,200 papers x 3 reviewers).

    `total` is the number of matching rows before pagination, so the frontend
    can show "showing 50 of 3,600".
    """
    rows = store.assignments()
    if paper_id:
        rows = [row for row in rows if row["paper_id"] == paper_id]
    if reviewer_id:
        rows = [row for row in rows if row["reviewer_id"] == reviewer_id]
    page = rows[offset : offset + limit]
    return {
        "total": len(rows),
        "papers": len({row["paper_id"] for row in rows}),
        "limit": limit,
        "offset": offset,
        "returned": len(page),
        "filters": {"paper_id": paper_id, "reviewer_id": reviewer_id},
        "items": page,
    }
