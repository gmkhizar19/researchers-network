"""Load the submitted GraphML files in a consistent, typed way.

Analysis scripts must work from the submitted dataset (not from hidden state),
so every script starts here. GraphML stores every attribute as text, which is a
classic source of bugs; this module converts the numeric fields once.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx

from crawler.config import GRAPHML_DIR

INT_NODE_FIELDS = ("degree", "strength", "pk_affiliated", "first_year", "last_year")
INT_EDGE_FIELDS = ("weight", "first_year", "last_year")


def _convert(graph: nx.Graph) -> nx.Graph:
    """Force numeric attributes to int and drop self-loops (there should be none)."""
    for _, data in graph.nodes(data=True):
        for field in INT_NODE_FIELDS:
            if field in data and data[field] not in (None, ""):
                data[field] = int(float(data[field]))
    for _, _, data in graph.edges(data=True):
        for field in INT_EDGE_FIELDS:
            if field in data and data[field] not in (None, ""):
                data[field] = int(float(data[field]))
    graph.remove_edges_from(list(nx.selfloop_edges(graph)))
    return graph


def load_full_graph() -> nx.Graph:
    """All authors, including the 1,527 with no co-author (degree 0)."""
    graph = nx.read_graphml(GRAPHML_DIR / "author_graph.graphml")
    return _convert(nx.Graph(graph))


def load_core_graph() -> nx.Graph:
    """Authors with at least two papers: the analysis network used in Stages 3-5."""
    graph = nx.read_graphml(GRAPHML_DIR / "author_graph_core.graphml")
    return _convert(nx.Graph(graph))


def largest_component(graph: nx.Graph) -> nx.Graph:
    """Return the largest connected component as a copy (never a view)."""
    if graph.number_of_nodes() == 0:
        return graph.copy()
    nodes = max(nx.connected_components(graph), key=len)
    return graph.subgraph(nodes).copy()


def graph_summary(graph: nx.Graph) -> dict[str, float | int]:
    """Small reusable summary used in the result JSON files."""
    components = list(nx.connected_components(graph))
    largest = max((len(c) for c in components), default=0)
    n = graph.number_of_nodes()
    m = graph.number_of_edges()
    return {
        "nodes": n,
        "edges": m,
        "components": len(components),
        "largest_component": largest,
        "lcc_pct": round(100 * largest / n, 2) if n else 0.0,
        "density": round(2 * m / (n * (n - 1)), 6) if n > 1 else 0.0,
        "mean_degree": round(2 * m / n, 2) if n else 0.0,
    }


def edge_weight(graph: nx.Graph, u: str, v: str) -> int:
    """Weight of an existing edge, or 0 when the pair is not connected."""
    if not graph.has_edge(u, v):
        return 0
    return int(graph[u][v].get("weight", 1))


def data_path(name: str) -> Path:
    """Resolve a file inside data/ (used for CSV outputs)."""
    from crawler.config import DATA_DIR

    return DATA_DIR / name
