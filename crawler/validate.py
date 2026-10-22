"""Validate the cleaned dataset against the grading requirements.

This is deliberately independent of the build code: it re-reads the submitted
CSVs and GraphML and re-computes the numbers. Run it before every submission.

Usage: python -m crawler.cli validate
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import networkx as nx

from crawler.config import CLEANED_DIR, GRAPHML_DIR, RESULTS_DIR


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def validate() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})

    authors = read_rows(CLEANED_DIR / "authors.csv")
    papers = read_rows(CLEANED_DIR / "papers.csv")
    institutions = read_rows(CLEANED_DIR / "institutions.csv")
    topics = read_rows(CLEANED_DIR / "topics.csv")
    wrote = read_rows(CLEANED_DIR / "wrote.csv")
    about = read_rows(CLEANED_DIR / "about.csv")
    cites = read_rows(CLEANED_DIR / "cites.csv")
    affiliated = read_rows(CLEANED_DIR / "affiliated_with.csv")
    nodes = read_rows(CLEANED_DIR / "author_nodes.csv")
    edges = read_rows(CLEANED_DIR / "author_edges.csv")

    author_ids = {row["author_id"] for row in authors}
    paper_ids = {row["paper_id"] for row in papers}
    institution_ids = {row["institution_id"] for row in institutions}
    topic_ids = {row["topic_id"] for row in topics}

    # --- primary keys --------------------------------------------------------
    check("author ids unique", len(author_ids) == len(authors), f"{len(author_ids)} unique / {len(authors)} rows")
    check("paper ids unique", len(paper_ids) == len(papers), f"{len(paper_ids)} unique / {len(papers)} rows")
    check(
        "institution ids unique",
        len(institution_ids) == len(institutions),
        f"{len(institution_ids)} unique / {len(institutions)} rows",
    )
    check("topic ids unique", len(topic_ids) == len(topics), f"{len(topic_ids)} unique / {len(topics)} rows")

    # --- required author fields ---------------------------------------------
    missing_name = sum(1 for row in authors if not row["name"].strip())
    bad_year = sum(
        1
        for row in authors
        if not (row["first_year"].isdigit() and row["last_year"].isdigit())
        or not (2015 <= int(row["first_year"]) <= int(row["last_year"]) <= 2025)
    )
    zero_works = sum(1 for row in authors if int(row["works_count"]) < 1)
    check("every author has a name", missing_name == 0, f"{missing_name} missing")
    check("every author has valid years", bad_year == 0, f"{bad_year} invalid")
    check("every author has at least one paper", zero_works == 0, f"{zero_works} with 0 works")
    no_context = sum(
        1 for row in authors if not row["primary_institution"].strip() and not row["topics"].strip()
    )
    check("every author has an institution or topic", no_context == 0, f"{no_context} with neither")

    # --- foreign keys --------------------------------------------------------
    wrote_missing = sum(1 for row in wrote if row["author_id"] not in author_ids or row["paper_id"] not in paper_ids)
    dup_wrote = len(wrote) - len({(row["author_id"], row["paper_id"]) for row in wrote})
    check("WROTE endpoints exist", wrote_missing == 0, f"{wrote_missing} broken")
    check("WROTE has no duplicate pairs", dup_wrote == 0, f"{dup_wrote} duplicates")

    about_missing = sum(1 for row in about if row["paper_id"] not in paper_ids or row["topic_id"] not in topic_ids)
    check("ABOUT endpoints exist", about_missing == 0, f"{about_missing} broken")

    cites_missing = sum(1 for row in cites if row["citing_id"] not in paper_ids or row["cited_id"] not in paper_ids)
    cites_self = sum(1 for row in cites if row["citing_id"] == row["cited_id"])
    check("CITES endpoints exist", cites_missing == 0, f"{cites_missing} broken")
    check("CITES has no self-loops", cites_self == 0, f"{cites_self} self-loops")

    aff_missing = sum(
        1 for row in affiliated
        if row["author_id"] not in author_ids or row["institution_id"] not in institution_ids
    )
    check("AFFILIATED_WITH endpoints exist", aff_missing == 0, f"{aff_missing} broken")

    # --- co-authorship graph -------------------------------------------------
    edge_missing = sum(1 for row in edges if row["source"] not in author_ids or row["target"] not in author_ids)
    edge_self = sum(1 for row in edges if row["source"] == row["target"])
    edge_dup = len(edges) - len({frozenset((row["source"], row["target"])) for row in edges})
    bad_weight = sum(1 for row in edges if int(row["weight"]) < 1)
    check("co-author edges endpoints exist", edge_missing == 0, f"{edge_missing} broken")
    check("co-author graph has no self-loops", edge_self == 0, f"{edge_self} self-loops")
    check("co-author edges are unique", edge_dup == 0, f"{edge_dup} duplicate pairs")
    check("co-author weights positive", bad_weight == 0, f"{bad_weight} invalid")

    # --- GraphML -------------------------------------------------------------
    graph = nx.read_graphml(GRAPHML_DIR / "author_graph.graphml")
    check(
        "GraphML matches node CSV",
        graph.number_of_nodes() == len(nodes),
        f"{graph.number_of_nodes()} GraphML / {len(nodes)} CSV",
    )
    check(
        "GraphML matches edge CSV",
        graph.number_of_edges() == len(edges),
        f"{graph.number_of_edges()} GraphML / {len(edges)} CSV",
    )
    check("GraphML has no self-loops", nx.number_of_selfloops(graph) == 0, f"{nx.number_of_selfloops(graph)} self-loops")

    # --- scale and connectivity ---------------------------------------------
    collaborating = graph.subgraph([node for node, data in graph.nodes(data=True) if data.get("degree", 0) > 0])
    components = sorted(nx.connected_components(collaborating), key=len, reverse=True)
    lcc = len(components[0]) if components else 0
    lcc_pct = round(100 * lcc / collaborating.number_of_nodes(), 1) if collaborating.number_of_nodes() else 0

    check("minimum nodes (100)", graph.number_of_nodes() >= 100, f"{graph.number_of_nodes()} nodes")
    check("minimum edges (300)", graph.number_of_edges() >= 300, f"{graph.number_of_edges()} edges")
    check("minimum LCC (50%)", lcc_pct >= 50.0, f"{lcc_pct}%")
    check("target nodes (500)", graph.number_of_nodes() >= 500, f"{graph.number_of_nodes()} nodes")
    check("target edges (1500)", graph.number_of_edges() >= 1500, f"{graph.number_of_edges()} edges")

    # The target LCC is evaluated on the core analysis network, as documented.
    core = nx.read_graphml(GRAPHML_DIR / "author_graph_core.graphml")
    core_components = sorted(nx.connected_components(core), key=len, reverse=True)
    core_lcc = len(core_components[0]) if core_components else 0
    core_pct = round(100 * core_lcc / core.number_of_nodes(), 1) if core.number_of_nodes() else 0
    check("target LCC (80%) on core network", core_pct >= 80.0, f"{core_pct}% (full network {lcc_pct}%)")

    summary = {
        "passed": all(item["passed"] for item in checks),
        "counts": {
            "authors": len(authors),
            "papers": len(papers),
            "institutions": len(institutions),
            "topics": len(topics),
            "wrote": len(wrote),
            "about": len(about),
            "cites": len(cites),
            "affiliated_with": len(affiliated),
            "coauthor_edges": len(edges),
        },
        "connectivity": {
            "collaborating_nodes": collaborating.number_of_nodes(),
            "components": len(components),
            "largest_component": lcc,
            "lcc_pct": lcc_pct,
            "core_nodes": core.number_of_nodes(),
            "core_edges": core.number_of_edges(),
            "core_lcc_pct": core_pct,
        },
        "checks": checks,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "stage1_validation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def print_validation(summary: dict[str, Any]) -> None:
    print(f"{'CHECK':<45} RESULT  DETAIL")
    for item in summary["checks"]:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"{item['check']:<45} {status:<6}  {item['detail']}")
    print()
    print("ALL CHECKS PASSED" if summary["passed"] else "SOME CHECKS FAILED")
