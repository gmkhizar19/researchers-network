"""FastAPI dependencies.

Both objects live on `app.state`, which makes it trivial to swap in fakes for
the tests (see tests/conftest.py) without touching the routers.
"""

from __future__ import annotations

from fastapi import Request

from backend.services.graph import Neo4jGraph
from backend.store import ResultStore


def get_store(request: Request) -> ResultStore:
    """The result store attached to this application."""
    return request.app.state.store


def get_graph(request: Request) -> Neo4jGraph:
    """The Neo4j gateway attached to this application."""
    return request.app.state.graph
