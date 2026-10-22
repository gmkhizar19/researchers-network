"""Neo4j access for the live graph endpoints.

Only three things are queried live: the explorer subgraph, one author profile,
and a connectivity ping. Everything analytical is served from the result files,
so the API keeps working (with a clear warning) when Neo4j is down.

All queries are parameterised; no string is built from user input.
"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncDriver
from neo4j.exceptions import DriverError, Neo4jError


class GraphUnavailable(RuntimeError):
    """Raised when Neo4j cannot be reached or the graph is not loaded."""


# The core analysis network: authors on which k-core was computed (14,574).
# Author.core also includes 61 isolated authors, so kcore IS NOT NULL is the
# exact node set used by Problems 1 and 2.
NETWORK_NODES = """
MATCH (a:Author)
WHERE a.kcore IS NOT NULL
RETURN a.author_id AS id,
       a.name AS name,
       a.primary_institution AS institution,
       a.degree AS degree,
       a.strength AS strength,
       a.pk_affiliated AS pk_affiliated,
       a.community AS community,
       a.pagerank AS pagerank,
       a.betweenness AS betweenness,
       a.kcore AS kcore
ORDER BY a.degree DESC, a.author_id
LIMIT $limit
"""

NETWORK_EDGES = """
MATCH (a:Author)-[r:CO_AUTHORED]-(b:Author)
WHERE a.author_id IN $ids
  AND b.author_id IN $ids
  AND a.author_id < b.author_id
RETURN a.author_id AS source,
       b.author_id AS target,
       r.weight AS weight,
       r.first_year AS first_year,
       r.last_year AS last_year
ORDER BY r.weight DESC
"""

AUTHOR = """
MATCH (a:Author {author_id: $author_id})
RETURN a.author_id AS id,
       a.name AS name,
       a.orcid AS orcid,
       a.works_count AS works_count,
       a.cited_by_count AS cited_by_count,
       a.first_year AS first_year,
       a.last_year AS last_year,
       a.pk_affiliated AS pk_affiliated,
       a.primary_institution AS primary_institution,
       a.primary_institution_id AS primary_institution_id,
       a.degree AS degree,
       a.strength AS strength,
       a.kcore AS kcore,
       a.pagerank AS pagerank,
       a.betweenness AS betweenness,
       a.community AS community,
       a.topics AS topics
"""

AUTHOR_COUNTS = """
MATCH (a:Author {author_id: $author_id})
OPTIONAL MATCH (a)-[:WROTE]->(p:Paper)
WITH a, count(DISTINCT p) AS papers
OPTIONAL MATCH (a)-[r:CO_AUTHORED]-(:Author)
RETURN papers, count(DISTINCT r) AS coauthors
"""

TOP_COLLABORATORS = """
MATCH (a:Author {author_id: $author_id})-[r:CO_AUTHORED]-(b:Author)
RETURN b.author_id AS id,
       b.name AS name,
       b.primary_institution AS institution,
       r.weight AS weight,
       r.first_year AS first_year,
       r.last_year AS last_year
ORDER BY r.weight DESC, b.name
LIMIT $limit
"""

RECENT_PAPERS = """
MATCH (a:Author {author_id: $author_id})-[:WROTE]->(p:Paper)
OPTIONAL MATCH (p)-[:ABOUT]->(t:Topic)
WITH p, collect(DISTINCT t.name)[0..3] AS topics
RETURN p.paper_id AS id,
       p.title AS title,
       p.year AS year,
       p.type AS type,
       p.cited_by_count AS cited_by_count,
       topics
ORDER BY p.year DESC, p.cited_by_count DESC
LIMIT $limit
"""


class Neo4jGraph:
    """Small wrapper around the official async driver."""

    def __init__(self, driver: AsyncDriver, database: str = "neo4j") -> None:
        self._driver = driver
        self._database = database

    async def _query(self, query: str, **params: Any) -> list[dict[str, Any]]:
        """Run a parameterised read query and return plain dictionaries."""
        try:
            result = await self._driver.execute_query(
                query, parameters_=params, database_=self._database
            )
        except (DriverError, Neo4jError) as exc:
            raise GraphUnavailable(str(exc)) from exc
        return [dict(record) for record in result.records]

    async def ping(self) -> dict[str, Any]:
        """Never raises: reports whether Neo4j is reachable."""
        try:
            await self._driver.verify_connectivity()
            rows = await self._query(
                "CALL dbms.components() YIELD name, versions "
                "RETURN name, versions[0] AS version LIMIT 1"
            )
            return {
                "available": True,
                "component": rows[0]["name"] if rows else None,
                "version": rows[0]["version"] if rows else None,
            }
        except Exception as exc:  # noqa: BLE001 - health must not crash the API
            return {"available": False, "error": str(exc)[:200]}

    async def network(self, limit: int) -> dict[str, Any]:
        """Top-`limit` authors by degree plus the edges between them."""
        nodes = await self._query(NETWORK_NODES, limit=limit)
        ids = [node["id"] for node in nodes]
        edges = await self._query(NETWORK_EDGES, ids=ids) if ids else []
        return {
            "limit": limit,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": nodes,
            "edges": edges,
            "layer": "core analysis network (authors with k-core computed, 14,574 nodes)",
            "induced_subgraph": True,
            "note": (
                "Nodes are the top authors by degree; edges are only those "
                "between the selected nodes, so this is an induced subgraph, "
                "not the full core network."
            ),
        }

    async def author(self, author_id: str) -> dict[str, Any] | None:
        """One author profile with collaborator and paper highlights."""
        rows = await self._query(AUTHOR, author_id=author_id)
        if not rows:
            return None
        counts = await self._query(AUTHOR_COUNTS, author_id=author_id)
        collaborators = await self._query(
            TOP_COLLABORATORS, author_id=author_id, limit=10
        )
        papers = await self._query(RECENT_PAPERS, author_id=author_id, limit=5)
        return {
            "author": rows[0],
            "papers_in_dataset": counts[0]["papers"] if counts else 0,
            "coauthors": counts[0]["coauthors"] if counts else 0,
            "top_collaborators": collaborators,
            "recent_papers": papers,
        }
