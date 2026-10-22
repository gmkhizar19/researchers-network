"""API contract tests: endpoints, schemas, filters, CORS and failure modes.

These tests use the fake store/graph from conftest.py and therefore pass with
Neo4j stopped and without touching the real analysis outputs.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from tests.conftest import FakeGraph, FakeStore

REQUIRED_PATHS = {
    "/api/health",
    "/api/stats",
    "/api/network",
    "/api/authors/{author_id}",
    "/api/fragility",
    "/api/critical",
    "/api/communities",
    "/api/link-predictions",
    "/api/reviewers/assignments",
    "/api/reviewers/metrics",
}


def test_health_reports_results_and_neo4j(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["assignments_loaded"] == 3
    assert body["neo4j"]["available"] is True
    assert body["results"]["p1_fragility"] is True


def test_openapi_lists_every_endpoint(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert REQUIRED_PATHS <= set(schema["paths"])
    # Every endpoint must carry a summary for the /docs page.
    for path in REQUIRED_PATHS:
        for operation in schema["paths"][path].values():
            assert operation["summary"]


def test_docs_page_is_served(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_root_redirects_to_docs(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 302)
    assert response.headers["location"] == "/docs"


def test_stats_serves_real_sections(client: TestClient) -> None:
    body = client.get("/api/stats").json()
    assert body["source"]["licence"] == "CC0 1.0 Universal"
    assert body["dataset"]["core_graph"]["nodes"] == 6
    assert body["neo4j_load"]["passed"] is True
    assert body["top_by_degree"][0]["name"] == "A One"


def test_network_returns_induced_subgraph(client: TestClient) -> None:
    response = client.get("/api/network", params={"limit": 25})
    assert response.status_code == 200
    body = response.json()
    assert body["node_count"] == 3
    assert body["induced_subgraph"] is True
    assert body["edges"][0]["weight"] == 2


def test_network_limit_validation(client: TestClient) -> None:
    assert client.get("/api/network", params={"limit": 5}).status_code == 422
    assert client.get("/api/network", params={"limit": 5000}).status_code == 422


def test_author_profile_and_404_and_invalid_id(client: TestClient) -> None:
    ok = client.get("/api/authors/A123456789")
    assert ok.status_code == 200
    assert ok.json()["author"]["name"] == "Test Author"
    assert client.get("/api/authors/A000000000").status_code == 404
    # Ids must look like OpenAlex author ids.
    assert client.get("/api/authors/not-an-id").status_code == 422


def test_fragility_sections(client: TestClient) -> None:
    body = client.get("/api/fragility").json()
    assert body["articulation"]["count"] == 1
    assert body["maxflow"]["max_flow"] == 2
    assert "cascade" in body
    assert body["source"].endswith("p1_fragility.json")


def test_critical_sorting_filtering_and_limit(client: TestClient) -> None:
    by_betweenness = client.get("/api/critical").json()
    assert [row["author_id"] for row in by_betweenness["items"]] == ["A1", "A2"]

    by_pagerank = client.get("/api/critical", params={"sort": "pagerank"}).json()
    assert by_pagerank["items"][0]["author_id"] == "A2"

    only_articulation = client.get(
        "/api/critical", params={"articulation_only": True}
    ).json()
    assert only_articulation["total_available"] == 1
    assert only_articulation["items"][0]["is_articulation"] is True

    limited = client.get("/api/critical", params={"limit": 1}).json()
    assert len(limited["items"]) == 1


def test_communities_and_link_predictions(client: TestClient) -> None:
    communities = client.get("/api/communities").json()
    assert communities["louvain"]["community_count_gds"] == 3
    assert "silos" in communities

    predictions = client.get("/api/link-predictions").json()
    assert predictions["time_split"]["split_year"] == 2020
    assert predictions["static_benchmark"]["adamic_adar"]["auc"] == 0.68


def test_reviewer_metrics(client: TestClient) -> None:
    body = client.get("/api/reviewers/metrics").json()
    assert body["scope"]["reviewer_capacity"] == 3
    assert body["min_cost_flow"]["verification"]["conflict_violations"] == 0
    assert body["comparison"]["flow_vs_random_score_lift"] == 20.0


def test_reviewer_assignments_pagination_and_filters(client: TestClient) -> None:
    page = client.get("/api/reviewers/assignments", params={"limit": 2}).json()
    assert page["total"] == 3
    assert page["papers"] == 2
    assert page["returned"] == 2
    assert page["items"][0]["paper_id"] == "P1"

    second = client.get(
        "/api/reviewers/assignments", params={"limit": 2, "offset": 2}
    ).json()
    assert second["returned"] == 1
    assert second["items"][0]["paper_id"] == "P2"

    one_paper = client.get(
        "/api/reviewers/assignments", params={"paper_id": "P1"}
    ).json()
    assert one_paper["total"] == 2

    one_reviewer = client.get(
        "/api/reviewers/assignments", params={"reviewer_id": "A1"}
    ).json()
    assert one_reviewer["total"] == 2


def test_cors_allows_the_vite_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_neo4j_down_gives_503_but_health_and_results_still_work(tmp_path) -> None:
    settings = Settings(_env_file=None, results_dir=tmp_path)
    app = create_app(settings=settings, store=FakeStore(), graph=FakeGraph(available=False))
    with TestClient(app) as failing:
        assert failing.get("/api/network").status_code == 503
        assert failing.get("/api/authors/A123456789").status_code == 503

        health = failing.get("/api/health")
        assert health.status_code == 200
        assert health.json()["neo4j"]["available"] is False
        # Analytical endpoints keep working from the result files.
        assert failing.get("/api/fragility").status_code == 200


def test_missing_result_file_gives_clear_503(tmp_path) -> None:
    settings = Settings(_env_file=None, results_dir=tmp_path)
    app = create_app(
        settings=settings, store=FakeStore(missing="p1_fragility"), graph=FakeGraph()
    )
    with TestClient(app) as broken:
        response = broken.get("/api/fragility")
    assert response.status_code == 503
    assert "p1_fragility.json" in response.json()["detail"]


def test_settings_come_from_environment(monkeypatch) -> None:
    """No credentials hard-coded: the environment wins."""
    monkeypatch.setenv("NEO4J_PASSWORD", "environment-only-secret")
    settings = Settings(_env_file=None)
    assert settings.neo4j_password == "environment-only-secret"
