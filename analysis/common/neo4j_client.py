"""Shared Neo4j connection helpers.

All settings come from .env; nothing is hard-coded. The driver is created once
and reused, which is the recommended pattern for the official Python driver.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "researchers")
DATABASE = "neo4j"


def get_driver() -> Driver:
    """Open a driver and fail fast if the database is not reachable."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    return driver


def run(driver: Driver, query: str, **params: Any) -> list[dict[str, Any]]:
    """Run a Cypher query and return the records as plain dictionaries.

    This uses an auto-commit transaction (session.run without an explicit
    transaction function) because `LOAD CSV ... CALL { ... } IN TRANSACTIONS`
    is only allowed in an implicit transaction.
    """
    with driver.session(database=DATABASE) as session:
        result = session.run(query, params)
        return [record.data() for record in result]


def scalar(driver: Driver, query: str, **params: Any) -> Any:
    """Return the first column of the first row (useful for COUNT queries)."""
    rows = run(driver, query, **params)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def graph_exists(driver: Driver, name: str) -> bool:
    rows = run(driver, "CALL gds.graph.exists($name) YIELD exists RETURN exists", name=name)
    return bool(rows and rows[0]["exists"])
