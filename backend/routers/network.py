"""Network explorer endpoint: a degree-ranked induced subgraph from Neo4j."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.deps import get_graph
from backend.services.graph import Neo4jGraph

router = APIRouter(tags=["graph"])


@router.get("/network", summary="Induced subgraph of the core co-authorship network")
async def network(
    limit: int = Query(
        300,
        ge=10,
        le=1500,
        description="Number of top authors by degree to return (10-1500).",
    ),
    graph: Neo4jGraph = Depends(get_graph),
) -> dict[str, Any]:
    """Nodes (authors) and edges (co-authorships) for the graph explorer.

    The full core network has 14,574 authors, so the explorer always works on a
    degree-ranked induced subgraph. Edge weights are the number of shared papers.
    """
    return await graph.network(limit)
