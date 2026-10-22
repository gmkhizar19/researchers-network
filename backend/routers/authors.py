"""Author profile endpoint for the node-details panel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path

from backend.deps import get_graph
from backend.services.graph import Neo4jGraph

router = APIRouter(tags=["graph"])


@router.get("/authors/{author_id}", summary="One author profile with collaborators")
async def author(
    author_id: str = Path(
        ...,
        pattern=r"^A\d{6,}$",
        description="OpenAlex author id, for example A5032425002.",
    ),
    graph: Neo4jGraph = Depends(get_graph),
) -> dict[str, Any]:
    """Author attributes, dataset counts, top collaborators and recent papers."""
    profile = await graph.author(author_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Author {author_id} not found")
    return profile
