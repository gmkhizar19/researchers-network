"""FastAPI application factory.

Design choices:
  * `create_app(...)` takes the settings, result store and graph gateway as
    arguments, so tests can inject fakes and run without Neo4j.
  * The Neo4j driver is created in the lifespan and closed on shutdown; a
    missing database never prevents the API from starting (health reports it).
  * All analytical endpoints read `data/results/*.json`; only `/api/network`
    and `/api/authors/{id}` query Neo4j.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from neo4j import AsyncGraphDatabase

from backend import __version__
from backend.config import Settings
from backend.routers import (
    authors,
    communities,
    critical,
    fragility,
    health,
    link_prediction,
    network,
    reviewers,
    stats,
)
from backend.services.graph import GraphUnavailable, Neo4jGraph
from backend.store import ResultStore

DESCRIPTION = """
Read-only API for **Pakistan's Researchers Network**, a co-authorship knowledge
graph built from real OpenAlex data (CC0 1.0) and stored in Neo4j + GDS.

* `dataset` — what was crawled, cleaned and loaded
* `graph` — live network explorer and author profiles (Neo4j)
* `fragility` — Problem 1: critical researchers, cuts, cascades
* `silos` / `link-prediction` — Problem 2: communities and future collaborations
* `reviewers` — Problem 3: capacity- and COI-constrained reviewer assignment

Numbers are produced once by the scripts in `analysis/` and served verbatim
from `data/results/`; nothing is calculated or fabricated by the API.
""".strip()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open one Neo4j driver per application, close it on shutdown.

    The driver connects lazily, so the API still starts when Neo4j is down.
    """
    driver = None
    if app.state.graph is None:
        settings: Settings = app.state.settings
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        app.state.graph = Neo4jGraph(driver, settings.neo4j_database)
    try:
        yield
    finally:
        if driver is not None:
            await driver.close()


async def _graph_unavailable(request: Request, exc: GraphUnavailable) -> JSONResponse:
    """Turn a Neo4j failure into an actionable 503 instead of a 500."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Neo4j is not available. Start it with `docker compose up -d`, "
                "then retry. Analysis endpoints that read data/results still work."
            ),
            "error": str(exc)[:300],
        },
    )


async def _result_missing(request: Request, exc: FileNotFoundError) -> JSONResponse:
    """A missing analysis output is a service problem, not a client error."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                f"Analysis result missing: {exc}. Run the analysis stage that "
                "produces it (see docs/PLAN.md)."
            )
        },
    )


def create_app(
    settings: Settings | None = None,
    store: ResultStore | None = None,
    graph: Neo4jGraph | None = None,
) -> FastAPI:
    """Build the application (dependency injection friendly)."""
    settings = settings or Settings()
    app = FastAPI(
        title="Pakistan's Researchers Network API",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store or ResultStore(settings.results_dir)
    # None means "create the real driver in the lifespan"; tests pass a fake.
    app.state.graph = graph

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (
        health.router,
        stats.router,
        network.router,
        authors.router,
        fragility.router,
        critical.router,
        communities.router,
        link_prediction.router,
        reviewers.router,
    ):
        app.include_router(router, prefix="/api")

    app.add_exception_handler(GraphUnavailable, _graph_unavailable)
    app.add_exception_handler(FileNotFoundError, _result_missing)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        """Send curious visitors straight to the interactive docs."""
        return RedirectResponse(url="/docs")

    return app


app = create_app()
