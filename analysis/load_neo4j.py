"""Load the cleaned CSV files into Neo4j and build the GDS projections.

This stage is intentionally boring and repeatable:
  1. copy the CSV files into data/import (mounted at /import in the container),
  2. create constraints and indexes,
  3. load nodes, then relationships, with batched transactions,
  4. compare Neo4j counts with the CSV counts,
  5. project the author graph in GDS (full and core).

All loading and verification is Cypher. Python only orchestrates it.

Usage:
  python -m analysis.load_neo4j            # idempotent MERGE load
  python -m analysis.load_neo4j --reset    # delete the graph first
  python -m analysis.load_neo4j --skip-gds # load and verify only
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from pathlib import Path
from typing import Any

from analysis.common.neo4j_client import get_driver, graph_exists, run, scalar
from crawler.config import CLEANED_DIR, IMPORT_DIR, RESULTS_DIR

# --- Cypher -----------------------------------------------------------------

SCHEMA = [
    "CREATE CONSTRAINT author_id_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.author_id IS UNIQUE",
    "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE",
    "CREATE CONSTRAINT institution_id_unique IF NOT EXISTS FOR (i:Institution) REQUIRE i.institution_id IS UNIQUE",
    "CREATE CONSTRAINT topic_id_unique IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE",
    "CREATE INDEX author_name IF NOT EXISTS FOR (a:Author) ON (a.name)",
    "CREATE INDEX author_core IF NOT EXISTS FOR (a:Author) ON (a.core)",
    "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
    "CREATE INDEX institution_country IF NOT EXISTS FOR (i:Institution) ON (i.country_code)",
]

LOAD_NODES = {
    "Author": """
        LOAD CSV WITH HEADERS FROM 'file:///author_nodes.csv' AS row
        CALL (row) {
          MERGE (a:Author {author_id: row.author_id})
          SET a.name = row.name,
              a.orcid = CASE WHEN row.orcid = '' THEN null ELSE row.orcid END,
              a.works_count = toInteger(row.works_count),
              a.cited_by_count = toInteger(row.cited_by_count),
              a.first_year = toInteger(row.first_year),
              a.last_year = toInteger(row.last_year),
              a.pk_affiliated = toInteger(row.pk_affiliated) = 1,
              a.primary_institution_id = CASE WHEN row.primary_institution_id = '' THEN null ELSE row.primary_institution_id END,
              a.primary_institution = CASE WHEN row.primary_institution = '' THEN null ELSE row.primary_institution END,
              a.topics = CASE WHEN row.topics = '' THEN [] ELSE split(row.topics, ';') END,
              a.degree = toInteger(row.degree),
              a.strength = toInteger(row.strength),
              // Integer rather than Boolean: GDS cannot load Boolean node properties.
              a.core = CASE WHEN toInteger(row.works_count) >= 2 THEN 1 ELSE 0 END
        } IN TRANSACTIONS OF 5000 ROWS
    """,
    "Paper": """
        LOAD CSV WITH HEADERS FROM 'file:///papers.csv' AS row
        CALL (row) {
          MERGE (p:Paper {paper_id: row.paper_id})
          SET p.doi = CASE WHEN row.doi = '' THEN null ELSE row.doi END,
              p.title = row.title,
              p.year = toInteger(row.year),
              p.type = row.type,
              p.cited_by_count = toInteger(row.cited_by_count),
              p.is_pk = toInteger(row.is_pk) = 1,
              p.author_count = toInteger(row.author_count),
              p.topic_count = toInteger(row.topic_count)
        } IN TRANSACTIONS OF 5000 ROWS
    """,
    "Institution": """
        LOAD CSV WITH HEADERS FROM 'file:///institutions.csv' AS row
        CALL (row) {
          MERGE (i:Institution {institution_id: row.institution_id})
          SET i.name = row.name,
              i.country_code = CASE WHEN row.country_code = '' THEN null ELSE row.country_code END,
              i.type = CASE WHEN row.type = '' THEN null ELSE row.type END
        } IN TRANSACTIONS OF 5000 ROWS
    """,
    "Topic": """
        LOAD CSV WITH HEADERS FROM 'file:///topics.csv' AS row
        CALL (row) {
          MERGE (t:Topic {topic_id: row.topic_id})
          SET t.name = row.name,
              t.subfield_id = row.subfield_id,
              t.subfield = row.subfield,
              t.field_id = row.field_id,
              t.field = row.field,
              t.domain_id = row.domain_id,
              t.domain = row.domain
        } IN TRANSACTIONS OF 5000 ROWS
    """,
}

LOAD_RELATIONSHIPS: list[tuple[str, str]] = [
    (
        "WROTE",
        """
        LOAD CSV WITH HEADERS FROM 'file:///wrote.csv' AS row
        CALL (row) {
          MATCH (a:Author {author_id: row.author_id})
          MATCH (p:Paper {paper_id: row.paper_id})
          MERGE (a)-[r:WROTE]->(p)
          SET r.position = row.position,
              r.is_corresponding = toInteger(row.is_corresponding) = 1
        } IN TRANSACTIONS OF 5000 ROWS
        """,
    ),
    (
        "AFFILIATED_WITH",
        """
        LOAD CSV WITH HEADERS FROM 'file:///affiliated_with.csv' AS row
        CALL (row) {
          MATCH (a:Author {author_id: row.author_id})
          MATCH (i:Institution {institution_id: row.institution_id})
          MERGE (a)-[r:AFFILIATED_WITH]->(i)
          SET r.years = [y IN split(row.years, ';') | toInteger(y)]
        } IN TRANSACTIONS OF 5000 ROWS
        """,
    ),
    (
        "ABOUT",
        """
        LOAD CSV WITH HEADERS FROM 'file:///about.csv' AS row
        CALL (row) {
          MATCH (p:Paper {paper_id: row.paper_id})
          MATCH (t:Topic {topic_id: row.topic_id})
          MERGE (p)-[r:ABOUT]->(t)
          SET r.score = toFloat(row.score)
        } IN TRANSACTIONS OF 5000 ROWS
        """,
    ),
    (
        "CITES",
        """
        LOAD CSV WITH HEADERS FROM 'file:///cites.csv' AS row
        CALL (row) {
          MATCH (citing:Paper {paper_id: row.citing_id})
          MATCH (cited:Paper {paper_id: row.cited_id})
          MERGE (citing)-[:CITES]->(cited)
        } IN TRANSACTIONS OF 5000 ROWS
        """,
    ),
    (
        "CO_AUTHORED",
        """
        LOAD CSV WITH HEADERS FROM 'file:///author_edges.csv' AS row
        CALL (row) {
          MATCH (a:Author {author_id: row.source})
          MATCH (b:Author {author_id: row.target})
          MERGE (a)-[r:CO_AUTHORED]->(b)
          SET r.weight = toInteger(row.weight),
              r.first_year = toInteger(row.first_year),
              r.last_year = toInteger(row.last_year),
              r.papers = CASE WHEN row.papers = '' THEN [] ELSE split(row.papers, ';') END
        } IN TRANSACTIONS OF 5000 ROWS
        """,
    ),
]

CSV_FILES = [
    "author_nodes.csv",
    "papers.csv",
    "institutions.csv",
    "topics.csv",
    "wrote.csv",
    "affiliated_with.csv",
    "about.csv",
    "cites.csv",
    "author_edges.csv",
]


# --- Helpers ----------------------------------------------------------------


def csv_count(filename: str) -> int:
    """Count data rows (excluding the header) in a cleaned CSV."""
    with (CLEANED_DIR / filename).open(encoding="utf-8", newline="") as handle:
        return sum(1 for _ in handle) - 1


def copy_imports() -> None:
    """Neo4j can only read LOAD CSV files from its /import directory."""
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    for name in CSV_FILES:
        shutil.copy2(CLEANED_DIR / name, IMPORT_DIR / name)
    print(f"Copied {len(CSV_FILES)} CSV files to data/import.")


def wait_for_neo4j(driver, timeout: int = 180) -> None:
    """The container needs a few seconds after `docker compose up`."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            scalar(driver, "RETURN 1")
            return
        except Exception:  # noqa: BLE001 - any connection error means "not ready yet"
            time.sleep(2)
    raise SystemExit("Neo4j did not become ready in time. Check `docker compose logs neo4j`.")


def reset_database(driver) -> None:
    """Remove existing data and GDS projections (only used with --reset)."""
    for graph_name in ("authorGraph", "authorGraphFull"):
        if graph_exists(driver, graph_name):
            run(driver, f"CALL gds.graph.drop('{graph_name}')")
    run(
        driver,
        "MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS",
    )
    print("Existing graph deleted.")


def create_schema(driver) -> None:
    for statement in SCHEMA:
        run(driver, statement)
    print(f"Schema ready ({len(SCHEMA)} constraints/indexes).")


def load_data(driver) -> None:
    for label, query in LOAD_NODES.items():
        print(f"Loading {label} nodes...", flush=True)
        run(driver, query)
    for rel_type, query in LOAD_RELATIONSHIPS:
        print(f"Loading {rel_type} relationships...", flush=True)
        run(driver, query)


def verify(driver) -> dict[str, Any]:
    """Compare Neo4j against the CSVs and run structural sanity checks."""
    checks: list[dict[str, Any]] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        checks.append(
            {
                "check": name,
                "expected": expected,
                "actual": actual,
                "passed": expected == actual,
            }
        )

    expected = {
        "Author": csv_count("author_nodes.csv"),
        "Paper": csv_count("papers.csv"),
        "Institution": csv_count("institutions.csv"),
        "Topic": csv_count("topics.csv"),
        "WROTE": csv_count("wrote.csv"),
        "AFFILIATED_WITH": csv_count("affiliated_with.csv"),
        "ABOUT": csv_count("about.csv"),
        "CITES": csv_count("cites.csv"),
        "CO_AUTHORED": csv_count("author_edges.csv"),
    }

    actual: dict[str, int] = {}
    for label in ("Author", "Paper", "Institution", "Topic"):
        actual[label] = scalar(driver, f"MATCH (n:{label}) RETURN count(n)")
    for rel in ("WROTE", "AFFILIATED_WITH", "ABOUT", "CITES", "CO_AUTHORED"):
        actual[rel] = scalar(driver, f"MATCH ()-[r:{rel}]->() RETURN count(r)")

    for key, value in expected.items():
        check(f"{key} count matches CSV", value, actual[key])

    # Structural checks beyond simple counts.
    check(
        "authors without a name",
        0,
        scalar(driver, "MATCH (a:Author) WHERE a.name IS NULL OR trim(a.name) = '' RETURN count(a)"),
    )
    check(
        "papers without an author",
        0,
        scalar(driver, "MATCH (p:Paper) WHERE NOT (p)<-[:WROTE]-() RETURN count(p)"),
    )
    check(
        "papers without a topic",
        0,
        scalar(driver, "MATCH (p:Paper) WHERE NOT (p)-[:ABOUT]->() RETURN count(p)"),
    )
    check(
        "co-author edges with a missing weight",
        0,
        scalar(driver, "MATCH ()-[r:CO_AUTHORED]->() WHERE r.weight IS NULL RETURN count(r)"),
    )

    info = {
        "authors_without_institution": scalar(
            driver, "MATCH (a:Author) WHERE NOT (a)-[:AFFILIATED_WITH]->() RETURN count(a)"
        ),
        "institutions_without_authors": scalar(
            driver, "MATCH (i:Institution) WHERE NOT (i)<-[:AFFILIATED_WITH]-() RETURN count(i)"
        ),
        "topics_without_papers": scalar(
            driver, "MATCH (t:Topic) WHERE NOT (t)<-[:ABOUT]-() RETURN count(t)"
        ),
        "authors_core": scalar(driver, "MATCH (a:Author) WHERE a.core = 1 RETURN count(a)"),
    }

    version = scalar(driver, "CALL dbms.components() YIELD versions RETURN versions[0]")
    constraints = run(driver, "SHOW CONSTRAINTS YIELD name, type RETURN name, type ORDER BY name")
    indexes = run(driver, "SHOW INDEXES YIELD name, type RETURN name, type ORDER BY name")

    return {
        "neo4j_version": version,
        "counts": actual,
        "expected": expected,
        "info": info,
        "constraints": constraints,
        "indexes": indexes,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }


def project_gds(driver) -> dict[str, Any]:
    """Create the full author graph and the core subgraph in GDS."""
    gds_version = scalar(driver, "RETURN gds.version()")

    for name in ("authorGraph", "authorGraphFull"):
        if graph_exists(driver, name):
            run(driver, f"CALL gds.graph.drop('{name}')")

    run(
        driver,
        """
        CALL gds.graph.project(
          'authorGraphFull',
          'Author',
          {CO_AUTHORED: {type: 'CO_AUTHORED', orientation: 'UNDIRECTED'}},
          {nodeProperties: ['core', 'degree', 'strength'], relationshipProperties: ['weight']}
        )
        """,
    )

    # Filter keeps only authors with at least two papers AND at least one
    # co-author, matching author_nodes_core.csv exactly. GDS does this inside
    # the projected graph, so no data is copied back into Neo4j.
    run(
        driver,
        "CALL gds.graph.filter('authorGraph', 'authorGraphFull', 'n.core = 1 AND n.degree > 0', '*')",
    )

    graphs = run(
        driver,
        """
        CALL gds.graph.list()
        YIELD graphName, nodeCount, relationshipCount
        RETURN graphName, nodeCount, relationshipCount
        ORDER BY graphName
        """,
    )
    # GDS stores an undirected relationship once per direction, so its
    # relationshipCount is double the number of unique co-authorship edges.
    for graph in graphs:
        graph["uniqueRelationships"] = graph["relationshipCount"] // 2

    # Smoke test: PageRank must return scores, proving the projection is usable.
    top = run(
        driver,
        """
        CALL gds.pageRank.stream('authorGraph', {maxIterations: 20, dampingFactor: 0.85})
        YIELD nodeId, score
        RETURN gds.util.asNode(nodeId).name AS name, score
        ORDER BY score DESC
        LIMIT 5
        """,
    )

    return {
        "gds_version": gds_version,
        "note": "GDS reports each undirected relationship twice; uniqueRelationships is relationshipCount / 2.",
        "graphs": graphs,
        "pagerank_smoke_test": top,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the cleaned dataset into Neo4j")
    parser.add_argument("--reset", action="store_true", help="delete existing data first")
    parser.add_argument("--skip-gds", action="store_true", help="do not create GDS projections")
    parser.add_argument("--gds-only", action="store_true", help="skip loading, only rebuild GDS")
    args = parser.parse_args()

    copy_imports()
    driver = get_driver()
    wait_for_neo4j(driver)

    if not args.gds_only:
        if args.reset:
            reset_database(driver)
        create_schema(driver)
        load_data(driver)

    result = verify(driver)

    if not args.skip_gds:
        result["gds"] = project_gds(driver)

    result["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "neo4j_verification.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )

    print()
    print(f"{'CHECK':<50} RESULT")
    for item in result["checks"]:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"{item['check']:<50} {status}")
    print()
    print("Neo4j and CSV counts match." if result["passed"] else "MISMATCH - see the JSON report.")
    if "gds" in result:
        print(f"GDS {result['gds']['gds_version']}")
        for graph in result["gds"]["graphs"]:
            print(
                f"  {graph['graphName']}: {graph['nodeCount']} nodes, "
                f"{graph['uniqueRelationships']} undirected relationships"
            )


if __name__ == "__main__":
    main()
