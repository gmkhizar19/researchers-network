"""Build the author-to-author collaboration graph from the cleaned CSVs.

Projection rule: two authors are connected when they appear on the same paper.
The edge weight is the number of shared papers. This is the standard
co-authorship projection of a bipartite Author-Paper graph.

Papers with more than MAX_AUTHORS_PER_PAPER authors are skipped as collaboration
papers: a 200-author consortium would otherwise add ~20,000 edges that say
nothing about who works with whom. The number skipped is reported.

Outputs:
  data/cleaned/author_edges.csv
  data/cleaned/author_nodes.csv
  data/cleaned/graphml/author_graph.graphml
  data/results/stage1_stats.json
  data/graph_report.md
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import networkx as nx

from crawler.config import CLEANED_DIR, GRAPHML_DIR, MAX_AUTHORS_PER_PAPER, RESULTS_DIR, ensure_dirs

MAX_PAPERS_PER_EDGE = 20  # keep the CSV property readable; weight keeps the true count


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def build_graph() -> dict[str, Any]:
    ensure_dirs()

    authors = read_csv(CLEANED_DIR / "authors.csv")
    papers = {row["paper_id"]: row for row in read_csv(CLEANED_DIR / "papers.csv")}
    wrote = read_csv(CLEANED_DIR / "wrote.csv")

    # Group authors by paper: the bipartite WROTE edges become cliques.
    paper_authors: dict[str, list[str]] = defaultdict(list)
    for row in wrote:
        paper_authors[row["paper_id"]].append(row["author_id"])

    # Aggregate repeated collaborations into one weighted edge.
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    skipped_large = 0
    skipped_large_edges = 0
    single_author = 0

    for paper_id, author_ids in paper_authors.items():
        unique_ids = sorted(set(author_ids))
        count = len(unique_ids)
        if count < 2:
            single_author += 1
            continue
        if count > MAX_AUTHORS_PER_PAPER:
            skipped_large += 1
            skipped_large_edges += count * (count - 1) // 2
            continue

        year = int(papers[paper_id]["year"])
        for left, right in combinations(unique_ids, 2):
            key = (left, right)  # combinations of a sorted list are already ordered
            record = edges.get(key)
            if record is None:
                record = {
                    "weight": 0,
                    "first_year": year,
                    "last_year": year,
                    "papers": [],
                }
                edges[key] = record
            record["weight"] += 1
            record["first_year"] = min(record["first_year"], year)
            record["last_year"] = max(record["last_year"], year)
            if len(record["papers"]) < MAX_PAPERS_PER_EDGE:
                record["papers"].append(paper_id)

    # Degree and strength per author (strength = sum of edge weights).
    degree: Counter[str] = Counter()
    strength: Counter[str] = Counter()
    for (left, right), record in edges.items():
        degree[left] += 1
        degree[right] += 1
        strength[left] += record["weight"]
        strength[right] += record["weight"]

    # Add derived columns to the author node table.
    node_rows: list[list[Any]] = []
    for author in authors:
        author_id = author["author_id"]
        node_rows.append(
            [
                author_id,
                author["name"],
                author["orcid"],
                author["works_count"],
                author["cited_by_count"],
                author["first_year"],
                author["last_year"],
                author["pk_affiliated"],
                author["primary_institution_id"],
                author["primary_institution"],
                author["topics"],
                degree.get(author_id, 0),
                strength.get(author_id, 0),
            ]
        )
    write_csv(
        CLEANED_DIR / "author_nodes.csv",
        [
            "author_id", "name", "orcid", "works_count", "cited_by_count",
            "first_year", "last_year", "pk_affiliated", "primary_institution_id",
            "primary_institution", "topics", "degree", "strength",
        ],
        node_rows,
    )

    edge_rows = [
        [left, right, record["weight"], record["first_year"], record["last_year"],
         ";".join(record["papers"])]
        for (left, right), record in sorted(edges.items())
    ]
    write_csv(
        CLEANED_DIR / "author_edges.csv",
        ["source", "target", "weight", "first_year", "last_year", "papers"],
        edge_rows,
    )

    # ------------------------------------------------------------------
    # Statistics. NB: the "collaboration graph" contains only authors with at
    # least one co-author; a single-author paper creates no edge. We report the
    # LCC both for that graph and for all authors (isolates included) so the
    # difference is visible rather than hidden.
    # ------------------------------------------------------------------
    graph = nx.Graph()
    for row in node_rows:
        author_id = row[0]
        if degree.get(author_id, 0) > 0:  # only collaborating authors
            graph.add_node(
                author_id,
                name=row[1],
                institution=row[9],
                topics=row[10],
                degree=int(row[11]),
                strength=int(row[12]),
                pk_affiliated=int(row[7]),
                first_year=int(row[5]),
                last_year=int(row[6]),
            )
    for (left, right), record in edges.items():
        graph.add_edge(
            left,
            right,
            weight=record["weight"],
            first_year=record["first_year"],
            last_year=record["last_year"],
            papers=";".join(record["papers"]),
        )

    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    largest = components[0] if components else set()
    all_author_count = len(node_rows)
    collaborating = graph.number_of_nodes()
    lcc_pct = round(100 * len(largest) / collaborating, 1) if collaborating else 0.0
    lcc_pct_all = round(100 * len(largest) / all_author_count, 1) if all_author_count else 0.0

    # Secondary view: authors with at least two papers (the "core").
    core_nodes = {row[0] for row in node_rows if int(row[3]) >= 2 and degree.get(row[0], 0) > 0}
    core_graph = graph.subgraph(core_nodes)
    core_components = sorted(nx.connected_components(core_graph), key=len, reverse=True)
    core_lcc = core_components[0] if core_components else set()

    degrees = [d for _, d in graph.degree()]
    weights = [data["weight"] for _, _, data in graph.edges(data=True)]

    def top_authors(key_index: int, limit: int = 15) -> list[dict[str, Any]]:
        ranked = sorted(node_rows, key=lambda row: int(row[key_index]), reverse=True)[:limit]
        return [
            {
                "author_id": row[0],
                "name": row[1],
                "institution": row[9],
                "degree": int(row[11]),
                "strength": int(row[12]),
                "works_count": int(row[3]),
                "cited_by_count": int(row[4]),
            }
            for row in ranked
        ]

    stats: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nodes": {
            "authors_total": all_author_count,
            "authors_collaborating": collaborating,
            "authors_isolated": all_author_count - collaborating,
            "papers": len(papers),
        },
        "edges": {
            "coauthor_edges": len(edges),
            "total_collaborations": sum(weights),
            "papers_used": sum(1 for ids in paper_authors.values() if 2 <= len(set(ids)) <= MAX_AUTHORS_PER_PAPER),
            "single_author_papers": single_author,
            "papers_skipped_over_30_authors": skipped_large,
            "edges_avoided_by_cap": skipped_large_edges,
        },
        "connectivity": {
            "components": len(components),
            "largest_component_nodes": len(largest),
            "lcc_pct_of_collaborating": lcc_pct,
            "lcc_pct_of_all_authors": lcc_pct_all,
            "component_sizes_top10": [len(c) for c in components[:10]],
            "isolated_collaborating_nodes": nx.number_of_isolates(graph),
        },
        "core_graph": {
            "definition": "authors with >=2 papers in the dataset and >=1 co-author",
            "nodes": core_graph.number_of_nodes(),
            "edges": core_graph.number_of_edges(),
            "components": len(core_components),
            "largest_component_nodes": len(core_lcc),
            "lcc_pct": round(100 * len(core_lcc) / core_graph.number_of_nodes(), 1)
            if core_graph.number_of_nodes()
            else 0.0,
        },
        "degree": {
            "mean": round(sum(degrees) / len(degrees), 2) if degrees else 0,
            "median": sorted(degrees)[len(degrees) // 2] if degrees else 0,
            "max": max(degrees) if degrees else 0,
            "p90": sorted(degrees)[int(0.9 * (len(degrees) - 1))] if degrees else 0,
        },
        "edge_weight": {
            "mean": round(sum(weights) / len(weights), 2) if weights else 0,
            "max": max(weights) if weights else 0,
            "single_paper_edges": sum(1 for w in weights if w == 1),
        },
        "top_by_degree": top_authors(11),
        "top_by_strength": top_authors(12),
    }

    (RESULTS_DIR / "stage1_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    # GraphML: include every author, including isolates, so it matches the node
    # CSV exactly. Analysis scripts explicitly remove isolates where needed.
    full_graph = graph.copy()
    for row in node_rows:
        if row[0] not in full_graph:
            full_graph.add_node(
                row[0],
                name=row[1],
                institution=row[9],
                topics=row[10],
                degree=0,
                strength=0,
                pk_affiliated=int(row[7]),
                first_year=int(row[5]),
                last_year=int(row[6]),
            )
    GRAPHML_DIR.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(full_graph, GRAPHML_DIR / "author_graph.graphml")

    # A second, smaller export: the core analysis network (authors with >=2
    # papers). One-off authors are kept in the full dataset but are mostly noise
    # for centrality and link prediction, so the analysis stages use this view.
    core_graph_nx = graph.subgraph(core_nodes).copy()
    nx.write_graphml(core_graph_nx, GRAPHML_DIR / "author_graph_core.graphml")

    core_node_rows = [row for row in node_rows if row[0] in core_nodes]
    write_csv(
        CLEANED_DIR / "author_nodes_core.csv",
        [
            "author_id", "name", "orcid", "works_count", "cited_by_count",
            "first_year", "last_year", "pk_affiliated", "primary_institution_id",
            "primary_institution", "topics", "degree", "strength",
        ],
        core_node_rows,
    )
    core_edge_rows = [
        [left, right, record["weight"], record["first_year"], record["last_year"],
         ";".join(record["papers"])]
        for (left, right), record in sorted(edges.items())
        if left in core_nodes and right in core_nodes
    ]
    write_csv(
        CLEANED_DIR / "author_edges_core.csv",
        ["source", "target", "weight", "first_year", "last_year", "papers"],
        core_edge_rows,
    )

    write_graph_report(stats)
    return stats


def write_graph_report(stats: dict[str, Any]) -> None:
    """Short human-readable summary of the projection and the gate numbers."""
    nodes = stats["nodes"]
    edges = stats["edges"]
    conn = stats["connectivity"]
    core = stats["core_graph"]
    degree = stats["degree"]

    top_lines = "\n".join(
        f"| {index + 1} | {a['name']} | {a['institution']} | {a['degree']} | {a['strength']} |"
        for index, a in enumerate(stats["top_by_degree"][:10])
    )

    text = f"""# Graph construction report

Generated: {stats['generated_at']}

## Projection

- Bipartite `Author -[WROTE]-> Paper` edges are projected into an undirected
  author-author graph: every pair of authors on the same paper is one collaboration.
- Edge `weight` = number of shared papers; `first_year` / `last_year` bound the
  collaboration; `papers` lists up to {MAX_PAPERS_PER_EDGE} example paper ids.
- Papers with more than {MAX_AUTHORS_PER_PAPER} authors are skipped
  ({edges['papers_skipped_over_30_authors']} papers, avoiding
  {edges['edges_avoided_by_cap']} clique edges). These are consortium papers,
  not personal collaborations.

## Numbers

| Measure | Value |
|---|---:|
| Authors (all) | {nodes['authors_total']} |
| Authors with at least one co-author | {nodes['authors_collaborating']} |
| Authors with no collaboration (isolates) | {nodes['authors_isolated']} |
| Papers in the cleaned dataset | {nodes['papers']} |
| Co-authorship edges | {edges['coauthor_edges']} |
| Sum of edge weights (collaboration instances) | {edges['total_collaborations']} |
| Connected components (collaboration graph) | {conn['components']} |
| Largest component (nodes) | {conn['largest_component_nodes']} |
| **LCC % of collaborating authors** | **{conn['lcc_pct_of_collaborating']}%** |
| LCC % of all authors (isolates included) | {conn['lcc_pct_of_all_authors']}% |
| Core graph (authors with 2+ papers): nodes | {core['nodes']} |
| Core graph: edges | {core['edges']} |
| Core graph: LCC % | {core['lcc_pct']}% |

The **core analysis network** (`author_nodes_core.csv`, `author_edges_core.csv`,
`graphml/author_graph_core.graphml`) keeps authors with at least two papers. This
removes one-off authors, who cannot have a recurring collaboration pattern. It is
the network used by the problem analyses; the full network above is kept for
transparency and for the Neo4j knowledge graph.

Mean degree: {degree['mean']} · median: {degree['median']} · max: {degree['max']}.

## Top 10 authors by degree

| # | Author | Primary institution | Degree | Strength (shared papers) |
|---:|---|---|---:|---:|
{top_lines}
"""
    (Path(CLEANED_DIR).parent / "graph_report.md").write_text(text, encoding="utf-8")
    print("  wrote graph_report.md")
