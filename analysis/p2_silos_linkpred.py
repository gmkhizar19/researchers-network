"""Problem 2 - silos and collaboration prediction.

Nothing invented: communities come from Neo4j GDS Louvain, predictions are scored
from the real training graph and validated against real 2021-2025 collaborations.

What runs where:
  Neo4j GDS  - Louvain communities (written back as Author.community),
               GDS modularity, nodeSimilarity candidates on a time-filtered
               train projection (authorGraphTrain, dropped after use).
  Python     - the 2020/2021 time split, exact common-neighbours / Adamic-Adar /
               Jaccard scoring (sparse matrices), precision/recall/AUC evaluation,
               silo statistics and structural-hole metrics, all figures and JSON.

Outputs:
  data/results/p2_silos_linkprediction.json
  data/results/p2_top_recommendations.csv
  report/figures/fig_p2_*.png
"""

from __future__ import annotations

import csv
import json
import random
import time
from collections import Counter, defaultdict
from typing import Any

import networkx as nx
import numpy as np
import scipy.sparse as sp

from analysis.common.dataset import graph_summary, load_core_graph
from analysis.common.neo4j_client import get_driver, graph_exists, run, scalar
from analysis.common.plotting import BLUE, GREY, ORANGE, PURPLE, RED, save
from crawler.config import RESULTS_DIR, ensure_dirs

SEED = 42
SPLIT_YEAR = 2020           # train = collaborations whose first shared paper is <= 2020
NODESIM_TOPK = 10           # GDS nodeSimilarity topK per node
TRAIN_PROJECTION = "authorGraphTrain"


# ---------------------------------------------------------------------------
# Time split
# ---------------------------------------------------------------------------


def time_split(graph: nx.Graph, split_year: int) -> tuple[nx.Graph, set[tuple[str, str]], dict[str, Any]]:
    """Build the 2020/2021 collaboration split.

    Train graph: edges whose first shared paper is <= split_year.
    Test pairs: collaborations whose first shared paper is >= split_year+1
    between two authors that BOTH already exist in the training graph. Pairs
    with a newcomer author cannot be predicted from past data - they are
    counted and excluded.
    """
    train_edges = [
        (u, v, d)
        for u, v, d in graph.edges(data=True)
        if int(d["first_year"]) <= split_year
    ]
    train = nx.Graph(train_edges)
    train_nodes = set(train.nodes())

    test_pairs: set[tuple[str, str]] = set()
    newcomer_pairs = 0
    for u, v, d in graph.edges(data=True):
        if int(d["first_year"]) >= split_year + 1:
            if u in train_nodes and v in train_nodes:
                test_pairs.add((min(u, v), max(u, v)))
            else:
                newcomer_pairs += 1

    stats = {
        "train_nodes": train.number_of_nodes(),
        "train_edges": train.number_of_edges(),
        "test_pairs_between_existing_authors": len(test_pairs),
        "test_pairs_with_newcomer_author_excluded": newcomer_pairs,
    }
    return train, test_pairs, stats


# ---------------------------------------------------------------------------
# Candidate universe + exact scores (Python, sparse matrices)
# ---------------------------------------------------------------------------


def build_matrices(train: nx.Graph) -> tuple[list[str], dict[str, int], sp.csr_matrix, np.ndarray]:
    """Number the training nodes and build the symmetric adjacency matrix."""
    nodes = list(train.nodes())
    index = {node: i for i, node in enumerate(nodes)}
    row = [index[u] for u, v in train.edges()]
    col = [index[v] for u, v in train.edges()]
    adjacency = sp.csr_matrix(
        (np.ones(len(row), dtype=np.float32), (row, col)),
        shape=(len(nodes), len(nodes)),
    )
    adjacency = adjacency + adjacency.T
    degrees = np.asarray(adjacency.sum(axis=1)).ravel()
    return nodes, index, adjacency, degrees


def candidates_and_scores(
    adjacency: sp.csr_matrix, degrees: np.ndarray
) -> tuple[tuple[np.ndarray, np.ndarray], dict[str, np.ndarray]]:
    """All non-edge pairs sharing >=1 neighbour, with three exact scores.

    Common neighbours (CN), Adamic-Adar (AA) and the link-prediction Jaccard
    coefficient share the same support, which keeps label lookups simple.
    The +2 in log(degree+2) keeps the weight finite for degree-1 neighbours.
    """
    common = adjacency @ adjacency
    common = common - common.multiply(adjacency != 0)  # drop existing edges
    common.setdiag(0)
    common.eliminate_zeros()

    rows, cols = common.nonzero()
    cn_values = np.asarray(common[rows, cols]).ravel()

    weights = (1.0 / np.log(degrees + 2.0)).astype(np.float32)
    aa_matrix = adjacency @ sp.diags(weights) @ adjacency
    aa_matrix = aa_matrix - aa_matrix.multiply(adjacency != 0)
    aa_matrix.setdiag(0)
    aa_matrix.eliminate_zeros()
    aa_values = np.asarray(aa_matrix[rows, cols]).ravel()

    union = degrees[rows] + degrees[cols] - cn_values
    jac_values = cn_values / np.maximum(union, 1.0)

    # The support is symmetric, so every pair appears twice - keep one copy.
    keep = rows < cols
    rows, cols = rows[keep], cols[keep]
    cn_values, aa_values, jac_values = (
        cn_values[keep], aa_values[keep], jac_values[keep]
    )

    scores = {"common_neighbours": cn_values, "adamic_adar": aa_values, "jaccard": jac_values}
    return (rows, cols), scores


def evaluate_scores(
    pairs: tuple[np.ndarray, np.ndarray],
    scores: dict[str, np.ndarray],
    labels: np.ndarray,
) -> dict[str, Any]:
    """Precision@K, Recall@K and ROC-AUC for the whole candidate universe."""
    from sklearn.metrics import roc_auc_score

    ks = [10, 50, 100, 500]
    positives = int(labels.sum())
    base_rate = labels.mean() if len(labels) else 0.0

    results: dict[str, Any] = {
        "candidate_pairs": int(len(labels)),
        "positive_pairs": positives,
        "random_precision_expected": round(float(base_rate), 4),
    }
    for name, score in scores.items():
        k_results = {}
        for k in ks:
            if k >= len(score):
                k_results[str(k)] = {"precision": None, "recall": None}
                continue
            chosen = np.argpartition(-score, k)[:k]
            k_results[str(k)] = {
                "precision": round(float(labels[chosen].mean()), 4),
                "recall": round(float(labels[chosen].sum() / positives), 4) if positives else 0.0,
            }
        results[name] = {"auc": round(float(roc_auc_score(labels, score)), 4), "per_k": k_results}
    return results


def random_precision(labels: np.ndarray, draws: int = 20) -> dict[str, float]:
    """Empirical random-precision baseline (seeded), matching the theory value."""
    rng = random.Random(SEED)
    n = len(labels)
    values = [labels[rng.sample(range(n), 100)].mean() for _ in range(draws)]
    return {
        "empirical_mean": round(float(np.mean(values)), 4),
        "empirical_std": round(float(np.std(values)), 4),
        "draws": draws,
        "sample_size": 100,
    }


def top_recommendations(
    nodes: list[str],
    graph: nx.Graph,
    train: nx.Graph,
    pairs: tuple[np.ndarray, np.ndarray],
    scores: dict[str, np.ndarray],
    community_map: dict[str, int],
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Top pairs by Adamic-Adar with names, institutions and both scores."""
    rows, cols = pairs
    order = np.argsort(-scores["adamic_adar"])[:limit]
    result = []
    for i in order:
        i1, i2 = rows[i], cols[i]
        u, v = nodes[i1], nodes[i2]
        result.append(
            {
                "rank": len(result) + 1,
                "name_1": graph.nodes[u].get("name", ""),
                "institution_1": graph.nodes[u].get("institution", ""),
                "name_2": graph.nodes[v].get("name", ""),
                "institution_2": graph.nodes[v].get("institution", ""),
                "shared_neighbours": int(scores["common_neighbours"][i]),
                "adamic_adar": round(float(scores["adamic_adar"][i]), 4),
                "jaccard": round(float(scores["jaccard"][i]), 5),
                "same_community": community_map[u] == community_map[v],
            }
        )
    return result


# ---------------------------------------------------------------------------
# Silos: Louvain communities and structural isolation
# ---------------------------------------------------------------------------


def louvain(graph: str = "authorGraph") -> tuple[dict[str, Any], dict[str, int]]:
    """Louvain via GDS on the core projection; also written back to Neo4j.

    Returns aggregate info plus id -> communityId for the whole core graph.
    Both the stream and the write use the same fixed seed and concurrency 1,
    so the partition is reproducible.
    """
    driver = get_driver()
    # Note: this GDS build rejects a randomSeed key for Louvain; with
    # concurrency: 1 the partition is deterministic, which keeps reruns stable.
    community_rows = run(
        driver,
        f"""
        CALL gds.louvain.stream('{graph}', {{concurrency: 1}})
        YIELD nodeId, communityId
        RETURN gds.util.asNode(nodeId).author_id AS id, communityId
        """,
    )
    community_map = {row["id"]: int(row["communityId"]) for row in community_rows}

    # Note: this build's louvain.write spells the mandatory key `writeProperty`
    # (not `communityProperty` as in the GDS docs).
    write = run(
        driver,
        f"CALL gds.louvain.write('{graph}', {{writeProperty: 'community', "
        "concurrency: 1}) "
        "YIELD nodePropertiesWritten, modularity, communityCount "
        "RETURN nodePropertiesWritten, modularity, communityCount",
    )[0]

    info = {
        "community_count_gds": int(write["communityCount"]),
        "modularity_gds": round(float(write["modularity"]), 4),
        "nodes_with_community_written": int(write["nodePropertiesWritten"]),
        "determinism_note": "this GDS build has no randomSeed key for Louvain; "
        "concurrency 1 is used, but the partition can still vary slightly between runs "
        "(observed: 545-546 communities, modularity 0.6234-0.6248). The submitted run "
        "is canonical; headline conclusions are stable, community labels are not.",
    }
    return info, community_map


def silo_statistics(
    graph: nx.Graph, community_map: dict[str, int]
) -> dict[str, Any]:
    """Community sizes, isolation (internal edge share), small groups, connectors."""
    sizes = Counter(community_map.values())

    # Community isolation: an internal edge has both ends in the community
    # (counted once); a boundary edge touches exactly one member in it.
    incident: Counter[int] = Counter()
    internal: Counter[int] = Counter()
    for u, v in graph.edges():
        cu, cv = community_map[u], community_map[v]
        if cu == cv:
            internal[cu] += 1
        else:
            incident[cu] += 1
            incident[cv] += 1
    # Communities without any edges (235 single-author groups in the core
    # graph) are isolated by definition - internal share = 1.0.
    internal_share = {
        community: (
            internal[community] / (internal[community] + incident[community])
            if (internal[community] + incident[community]) > 0
            else 1.0
        )
        for community in sizes
    }

    community_rows = []
    for community, size in sizes.most_common():
        members = [n for n, c in community_map.items() if c == community]
        institutions = Counter(graph.nodes[n].get("institution", "unknown") for n in members)
        community_rows.append(
            {
                "community_id": int(community),
                "size": size,
                "internal_edge_share": round(internal_share[community], 4),
                "top_institutions": [f"{n} ({c})" for n, c in institutions.most_common(3)],
            }
        )

    silos = [r for r in community_rows if r["size"] >= 20 and r["internal_edge_share"] >= 0.90]

    # Participation coefficient (structural holes, per node): 1 means every tie
    # leaves the own community (pure connector), 0 means fully embedded.
    neighbour_coms: dict[str, Counter[int]] = defaultdict(Counter)
    for u, v in graph.edges():
        neighbour_coms[u][community_map[v]] += 1
        neighbour_coms[v][community_map[u]] += 1
    participation = [
        (sum(c.values()) - c.get(community_map[node], 0)) / sum(c.values())
        for node, c in neighbour_coms.items()
    ]

    small_groups = sum(1 for c in nx.connected_components(graph) if len(c) < 5)

    return {
        "communities": community_rows,
        "silos": silos,
        "components_smaller_than_5": small_groups,
        "participation": {
            "definition": "share of an author's ties that leave their own community",
            "mean": round(float(np.mean(participation)), 4),
            "max": round(float(np.max(participation)), 4),
            "pure_connectors_zero_internal_ties": sum(1 for p in participation if p == 1.0),
        },
        "counts_note": "internal edges counted once; each boundary edge touches one member; "
        "communities with no edges (singletons) are isolated by definition",
    }


# ---------------------------------------------------------------------------
# GDS nodeSimilarity candidates on a time-filtered projection
# ---------------------------------------------------------------------------


def nodesim_candidates() -> tuple[list[tuple[str, str, float]], dict[str, Any]]:
    """nodeSimilarity topK on a train-only projection (no future edges).

    The GraphML train graph holds the same edges; doing this in GDS keeps the
    technique demonstrably in Neo4j. Existing edges are removed afterwards
    because nodeSimilarity also scores still-connected pairs.
    """
    driver = get_driver()
    info: dict[str, Any] = {}
    if not graph_exists(driver, "authorGraph"):
        raise SystemExit(
            "Projection 'authorGraph' missing. Run: python -m analysis.load_neo4j --gds-only"
        )
    drop_train_projection()  # idempotent reruns

    projection = run(
        driver,
        f"""
        CALL gds.graph.project.cypher('{TRAIN_PROJECTION}',
            'MATCH (a:Author {{core: 1}}) RETURN id(a) AS id',
            'MATCH (a:Author {{core: 1}})-[r:CO_AUTHORED]->(b:Author {{core: 1}})
             WHERE toInteger(r.first_year) <= {SPLIT_YEAR}
             RETURN id(a) AS source, id(b) AS target'
        )
        """,
    )[0]
    info["projection_nodes"] = projection["nodeCount"]
    info["projection_relationships"] = projection["relationshipCount"]
    info["topK"] = NODESIM_TOPK

    rows = run(
        driver,
        f"""
        CALL gds.nodeSimilarity.stream('{TRAIN_PROJECTION}', {{topK: {NODESIM_TOPK}, similarityCutoff: 0.1}})
        YIELD node1, node2, similarity
        RETURN gds.util.asNode(node1).author_id AS a,
               gds.util.asNode(node2).author_id AS b,
               similarity
        """,
    )

    info["pairs_returned"] = len(rows)
    return [(row["a"], row["b"], float(row["similarity"])) for row in rows], info


def drop_train_projection() -> None:
    driver = get_driver()
    if graph_exists(driver, TRAIN_PROJECTION):
        run(driver, f"CALL gds.graph.drop('{TRAIN_PROJECTION}')")


def evaluate_nodesim(
    candidates: list[tuple[str, str, float]],
    train: nx.Graph,
    test_pairs: set[tuple[str, str]],
) -> dict[str, Any]:
    """Precision@K for the GDS candidate stream (existing edges removed)."""
    unique: dict[tuple[str, str], float] = {}
    for a, b, sim in candidates:
        key = (min(a, b), max(a, b))
        if key[0] != key[1] and not train.has_edge(key[0], key[1]):
            unique[key] = max(unique.get(key, 0.0), sim)

    ordered = sorted(unique.items(), key=lambda item: -item[1])
    hits = sum(1 for pair, _ in ordered if pair in test_pairs)
    per_k: dict[str, float | None] = {}
    for k in (10, 50, 100):
        if k <= len(ordered):
            per_k[str(k)] = round(
                sum(1 for pair, _ in ordered[:k] if pair in test_pairs) / k, 4
            )
        else:
            per_k[str(k)] = None
    return {
        "candidate_pairs_after_cleanup": len(unique),
        "total_new_pairs_found": hits,
        "per_k": per_k,
        "note": "nodeSimilarity also scores still-connected pairs; train edges were removed before ranking",
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def plot_community_sizes(community_rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    top = community_rows[:20]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(range(len(top)), [r["size"] for r in top], color=BLUE)
    ax.set_xlabel("community rank")
    ax.set_ylabel("authors")
    ax.set_title(f"Louvain community sizes (top 20 of {len(community_rows)})")
    save(fig, "fig_p2_community_sizes.png")


def plot_silo_share(community_rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    top = [r for r in community_rows if r["size"] >= 20][:15]
    shares = [100 * r["internal_edge_share"] for r in top]
    labels = [f"#{i+1} (n={r['size']})" for i, r in enumerate(top)]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh(labels[::-1], shares[::-1], color=[ORANGE if s >= 90 else BLUE for s in shares[::-1]])
    ax.set_xlabel("internal edge share (%)")
    ax.set_title("How closed-off are the biggest communities?\norange = silo (>= 90% internal ties)")
    ax.set_xlim(0, 100)
    save(fig, "fig_p2_silo_share.png")


def plot_link_prediction(eval_results: dict[str, Any], nodesim: dict[str, float | None] | None) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    styles = {
        "common_neighbours": (RED, "-o", "Common neighbours"),
        "adamic_adar": (BLUE, "-s", "Adamic-Adar"),
        "jaccard": (PURPLE, "-^", "Jaccard"),
    }
    for name, (colour, line, label) in styles.items():
        points = eval_results[name]["per_k"]
        ks = [int(k) for k, v in points.items() if v["precision"] is not None]
        ys = [100 * points[str(k)]["precision"] for k in ks]
        if ks:
            ax.plot(ks, ys, line, color=colour, label=label)
    base = eval_results["random_precision_expected"]
    ax.axhline(100 * base, color=GREY, linestyle="--", label=f"Random baseline ({base:.1%})")

    if nodesim and "per_k" in nodesim and nodesim["per_k"].get("10") is not None:
        ns_ks = [int(k) for k, v in nodesim["per_k"].items() if v is not None]
        ns_ys = [100 * nodesim["per_k"][str(k)] for k in ns_ks]
        if ns_ks:
            ax.plot(ns_ks, ns_ys, "-D", color=ORANGE, label="GDS nodeSimilarity")

    ax.set_xscale("log")
    ax.set_xticks([10, 50, 100, 500])
    ax.set_xticklabels(["10", "50", "100", "500"])
    ax.set_xlabel("K (top-K ranked predictions)")
    ax.set_ylabel("precision (%)")
    ax.set_title("Can we predict which collaborations happen next?\n(validated on real 2021-2025 collaborations)")
    ax.legend(loc="lower left")
    save(fig, "fig_p2_link_prediction.png")


# ---------------------------------------------------------------------------


def main() -> None:
    # Windows consoles default to cp1252; author names contain unicode dashes.
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    started = time.time()
    ensure_dirs()

    graph = load_core_graph()
    print(f"Core network: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges", flush=True)

    print("Time split...", flush=True)
    train, test_pairs, split_stats = time_split(graph, SPLIT_YEAR)
    print(
        f"  train: {split_stats['train_nodes']} nodes / {split_stats['train_edges']} edges; "
        f"test pairs {split_stats['test_pairs_between_existing_authors']} "
        f"(+{split_stats['test_pairs_with_newcomer_author_excluded']} with a newcomer author, excluded)"
    )

    print("Candidate pairs and exact scores...", flush=True)
    nodes, _, adjacency, degrees = build_matrices(train)
    pairs, scores = candidates_and_scores(adjacency, degrees)
    rows, cols = pairs
    labels = np.zeros(len(rows), dtype=np.int8)
    for i in range(len(rows)):
        label = (min(nodes[rows[i]], nodes[cols[i]]), max(nodes[rows[i]], nodes[cols[i]])) in test_pairs
        labels[i] = 1 if label else 0
    coverage = labels.mean() if len(labels) else 0.0
    print(
        f"  candidates: {len(rows)} non-edge pairs sharing >=1 neighbour; "
        f"{labels.sum()} became real ({coverage:.1%} base rate)"
    )
    eval_results = evaluate_scores(pairs, scores, labels)
    eval_results["random_empirical"] = random_precision(labels)
    for name in ("common_neighbours", "adamic_adar", "jaccard"):
        r = eval_results[name]
        print(f"  {name}: AUC {r['auc']}  P@100 {r['per_k']['100']['precision']}  R@100 {r['per_k']['100']['recall']}")

    print("Silos (Louvain via GDS)...", flush=True)
    louvain_info, community_map = louvain()
    communities = silo_statistics(graph, community_map)
    print(f"  communities: {louvain_info['community_count_gds']}, modularity {louvain_info['modularity_gds']}")
    print(f"  silos (>=20 authors, >=90% internal ties): {len(communities['silos'])}")
    real_clustering_modularity = _python_modularity(graph, community_map)
    louvain_info["modularity_python_crosscheck"] = real_clustering_modularity

    print("GDS nodeSimilarity candidates...", flush=True)
    try:
        candidates, nodesim_info = nodesim_candidates()
        nodesim_eval = evaluate_nodesim(candidates, train, test_pairs)
        print(
            f"  candidates after cleanup: {nodesim_eval['candidate_pairs_after_cleanup']}, "
            f"new pairs found: {nodesim_eval['total_new_pairs_found']}"
        )
    except Exception as exc:  # noqa: BLE001 - report the failure honestly
        nodesim_info = {"error": str(exc)[:200]}
        nodesim_eval = {"error": "nodeSimilarity candidate stream failed; see nodesim_info"}
        print(f"  nodeSimilarity failed: {str(exc)[:120]}")
    finally:
        drop_train_projection()

    top = top_recommendations(nodes, graph, train, pairs, scores, community_map)
    with (RESULTS_DIR / "p2_top_recommendations.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(top[0].keys()))
        writer.writeheader()
        writer.writerows(top)

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": "python -m analysis.p2_silos_linkpred",
        "graph": graph_summary(graph),
        "graph_note": "core analysis network: authors with >=2 papers and >=1 co-author",
        "time_split": {
            "split_year": SPLIT_YEAR,
            "rule": "train = pairs whose first shared paper is <= 2020; "
                    "test = pairs whose first shared paper is >= 2021 between authors already in training",
            **split_stats,
            "candidate_coverage": round(float(coverage), 4),
        },
        "link_prediction_static": eval_results,
        "link_prediction_gds_nodesim": {"info": nodesim_info, "evaluation": nodesim_eval},
        "louvain": louvain_info,
        "silos": {k: v for k, v in communities.items() if k != "communities"},
        "communities_top20": communities["communities"][:20],
        "recommendations_top20": top[:20],
        "runtime_seconds": round(time.time() - started, 1),
    }
    (RESULTS_DIR / "p2_silos_linkprediction.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Figures...", flush=True)
    plot_community_sizes(communities["communities"])
    plot_silo_share(communities["communities"])
    plot_link_prediction(eval_results, nodesim_eval if "per_k" in nodesim_eval else None)

    print()
    print(f"Communities: {louvain_info['community_count_gds']}, modularity: {louvain_info['modularity_gds']}")
    print(f"Silos found: {len(communities['silos'])}; isolated small components: {communities['components_smaller_than_5']}")
    print("Top predictions (Adamic-Adar):")
    for row in top[:5]:
        print(f"  {row['name_1']} + {row['name_2']}  (shared neighbours: {row['shared_neighbours']})")
    print(f"Runtime: {result['runtime_seconds']}s")


def _python_modularity(graph: nx.Graph, community_map: dict[str, int]) -> float:
    """Independent modularity cross-check with NetworkX."""
    from networkx.algorithms.community import modularity

    partition: dict[int, list[str]] = defaultdict(list)
    for node, community in community_map.items():
        partition[community].append(node)
    return round(modularity(graph, list(partition.values())), 4)


if __name__ == "__main__":
    main()
