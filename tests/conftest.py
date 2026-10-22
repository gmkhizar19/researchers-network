"""Shared fixtures: a fake result store and a fake graph gateway.

The API tests must pass without Neo4j and without depending on the real data
files, so both dependencies are replaced with small, clearly fake objects.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allow `pytest` without `python -m`
    sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.services.graph import GraphUnavailable  # noqa: E402

# ---------------------------------------------------------------------------
# Fake analysis outputs: same shape as the real files, tiny values.
# ---------------------------------------------------------------------------

FAKE_JSON: dict[str, dict[str, Any]] = {
    "stage1_stats": {
        "nodes": {"authors_total": 10, "authors_collaborating": 9, "papers": 4},
        "edges": {"coauthor_edges": 12},
        "connectivity": {"components": 2, "largest_component_nodes": 8},
        "core_graph": {"nodes": 6, "edges": 7, "lcc_pct": 90.0},
        "degree": {"mean": 2.4, "median": 2, "max": 5, "p90": 4},
        "edge_weight": {"mean": 1.1, "max": 3},
        "top_by_degree": [
            {
                "author_id": "A1",
                "name": "A One",
                "institution": "Institute One",
                "degree": 5,
                "strength": 9,
                "works_count": 3,
                "cited_by_count": 10,
            }
        ],
    },
    "neo4j_verification": {
        "neo4j_version": "5.26.32",
        "passed": True,
        "counts": {"Author": 10, "Paper": 4},
        "gds": {"gds_version": "2.13.14", "graphs": []},
    },
    "p1_fragility": {
        "graph": {"nodes": 6, "edges": 7},
        "graph_note": "core analysis network",
        "cascade": {
            "curves": {"betweenness": [1.0, 0.9], "random_curves": [[1.0, 0.95]]}
        },
        "damage_summary": {"lcc_fraction_before": 0.9},
        "distances": {"sampled_mean_distance_before": 2.1},
        "articulation": {"count": 1, "networkx_crosscheck": 1, "pct_of_nodes": 16.7},
        "bridges": {"count": 1, "pairs": []},
        "kcore": {"max": 3, "distribution": {"3": 2}, "top": []},
        "clustering": {"real_network": 0.5, "null_model": 0.01},
        "null_model": {"lcc_pct": 95.0, "avg_clustering": 0.01},
        "maxflow": {
            "max_flow": 2,
            "min_cut_size": 2,
            "source": "A1",
            "target": "A2",
        },
    },
    "p2_silos_linkprediction": {
        "louvain": {"community_count_gds": 3, "modularity_gds": 0.5},
        "silos": {"silos": [], "participation": {"mean": 0.2}},
        "communities_top20": [{"community_id": 1, "size": 4}],
        "time_split": {"split_year": 2020, "train_edges": 10},
        "link_prediction_static": {"adamic_adar": {"auc": 0.68}},
        "link_prediction_gds_nodesim": {"evaluation": {"total_new_pairs_found": 3}},
        "recommendations_top20": [{"rank": 1, "name_1": "A", "name_2": "B"}],
    },
    "p3_reviewers": {
        "scope": {"papers_sampled": 2, "reviewer_pool": 3, "reviewer_capacity": 3},
        "eligibility": {"mean_eligible_reviewers": 2.5},
        "min_cost_flow": {
            "candidate_limit_used": 100,
            "metrics": {"coverage": 1.0, "mean_score": 0.4, "loads": {"max": 1}},
            "verification": {"conflict_violations": 0},
        },
        "hungarian_uncapacitated": {
            "metrics": {"mean_score": 0.42},
            "verification": {"conflict_violations": 0},
            "top1_agreement_with_flow": 0.5,
        },
        "random_baseline": {"runs": 100, "mean_score_mean": 0.02},
        "comparison": {"flow_vs_random_score_lift": 20.0},
        "infeasible_papers": [],
        "runtime_seconds": 1.0,
    },
}

FAKE_CRITICAL: list[dict[str, Any]] = [
    {
        "author_id": "A1",
        "name": "A One",
        "institution": "Institute One",
        "betweenness": 10.0,
        "pagerank": 2.0,
        "degree": 5,
        "strength": 9,
        "kcore": 3,
        "is_articulation": True,
    },
    {
        "author_id": "A2",
        "name": "B Two",
        "institution": "Institute Two",
        "betweenness": 5.0,
        "pagerank": 3.0,
        "degree": 4,
        "strength": 7,
        "kcore": 2,
        "is_articulation": False,
    },
]

FAKE_ASSIGNMENTS: list[dict[str, Any]] = [
    {
        "paper_id": "P1",
        "paper_title": "Paper One",
        "paper_year": 2023,
        "reviewer_rank": 1,
        "reviewer_id": "A1",
        "reviewer_name": "A One",
        "reviewer_institution": "Institute One",
        "combined_score": 0.5,
    },
    {
        "paper_id": "P1",
        "paper_title": "Paper One",
        "paper_year": 2023,
        "reviewer_rank": 2,
        "reviewer_id": "A2",
        "reviewer_name": "B Two",
        "reviewer_institution": "Institute Two",
        "combined_score": 0.4,
    },
    {
        "paper_id": "P2",
        "paper_title": "Paper Two",
        "paper_year": 2024,
        "reviewer_rank": 1,
        "reviewer_id": "A1",
        "reviewer_name": "A One",
        "reviewer_institution": "Institute One",
        "combined_score": 0.3,
    },
]


class FakeStore:
    """In-memory stand-in for `backend.store.ResultStore`."""

    def __init__(self, missing: str | None = None) -> None:
        self.missing = missing

    def json(self, name: str) -> dict[str, Any]:
        if name == self.missing or name not in FAKE_JSON:
            raise FileNotFoundError(f"{name}.json")
        return FAKE_JSON[name]

    def assignments(self) -> list[dict[str, Any]]:
        return [dict(row) for row in FAKE_ASSIGNMENTS]

    def critical_authors(self) -> list[dict[str, Any]]:
        return [dict(row) for row in FAKE_CRITICAL]

    def status(self) -> dict[str, bool]:
        status = {name: name != self.missing for name in FAKE_JSON}
        status.update({"p3_reviewer_assignments": True})
        return status

    def assignment_count(self) -> int:
        return len(FAKE_ASSIGNMENTS)


class FakeGraph:
    """In-memory stand-in for `backend.services.graph.Neo4jGraph`."""

    def __init__(self, available: bool = True) -> None:
        self.available = available

    async def ping(self) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "error": "connection refused (fake)"}
        return {"available": True, "component": "Neo4j Kernel", "version": "fake"}

    async def network(self, limit: int) -> dict[str, Any]:
        if not self.available:
            raise GraphUnavailable("connection refused (fake)")
        nodes = [
            {"id": f"A{i}", "name": f"Node {i}", "degree": 10 - i}
            for i in range(min(limit, 3))
        ]
        return {
            "limit": limit,
            "node_count": len(nodes),
            "edge_count": 1,
            "nodes": nodes,
            "edges": [{"source": "A0", "target": "A1", "weight": 2}],
            "layer": "fake core network",
            "induced_subgraph": True,
            "note": "fake",
        }

    async def author(self, author_id: str) -> dict[str, Any] | None:
        if not self.available:
            raise GraphUnavailable("connection refused (fake)")
        if author_id != "A123456789":
            return None
        return {
            "author": {"id": author_id, "name": "Test Author"},
            "papers_in_dataset": 3,
            "coauthors": 2,
            "top_collaborators": [],
            "recent_papers": [],
        }


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """API client wired to the fakes; no Neo4j and no real data needed."""
    settings = Settings(_env_file=None, results_dir=tmp_path)
    app = create_app(settings=settings, store=FakeStore(), graph=FakeGraph())
    with TestClient(app) as test_client:
        yield test_client
