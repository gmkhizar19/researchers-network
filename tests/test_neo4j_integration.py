"""Integration test against the real Neo4j instance (skipped when it is down).

Run only this file with:  pytest -m neo4j
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.neo4j


def test_live_network_and_author_endpoints() -> None:
    neo4j = pytest.importorskip("neo4j")
    from backend.config import Settings
    from backend.main import create_app

    settings = Settings()
    driver = neo4j.GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001 - any connection problem means skip
        pytest.skip(f"Neo4j is not running: {exc}")
    finally:
        driver.close()

    with TestClient(create_app(settings=settings)) as client:
        health = client.get("/api/health").json()
        assert health["neo4j"]["available"] is True

        response = client.get("/api/network", params={"limit": 25})
        assert response.status_code == 200
        body = response.json()
        assert 10 <= body["node_count"] <= 25
        assert body["edges"], "the core network must have edges inside the top-25"

        author_id = body["nodes"][0]["id"]
        profile = client.get(f"/api/authors/{author_id}")
        assert profile.status_code == 200
        assert profile.json()["author"]["id"] == author_id
