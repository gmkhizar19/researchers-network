"""Problem 1 - fragility: who holds Pakistan's research network together?

Nothing in this file invents data: all numbers come from either Neo4j GDS or the
co-authorship GraphML built in Stage 1.

What runs where (the boundary the brief requires):
  Neo4j GDS  - PageRank, betweenness (exact), k-core, articulation points,
               bridges, min/max-cut between the two most connected authors.
  Python     - targeted vs random node-removal cascades, the configuration-model
               null model, degree distribution, clustering, figures and JSON.

Outputs:
  data/results/p1_fragility.json
  data/results/p1_critical_authors.csv
  report/figures/fig_p1_*.png
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter
from typing import Any

import networkx as nx

from analysis.common.dataset import graph_summary, largest_component, load_core_graph
from analysis.common.neo4j_client import get_driver, graph_exists, run, scalar
from analysis.common.plotting import BLUE, GREY, ORANGE, PURPLE, RED, save
from crawler.config import RESULTS_DIR, ensure_dirs

SEED = 42
STEP_FRACTION = 0.0025   # remove 0.25% of the nodes in each cascade step
MAX_FRACTION = 0.10      # stop the cascade at 10% of the network
RANDOM_REPLICATES = 20   # independent random-removal orderings
BFS_SOURCES = 300        # sample size for mean-distance estimates

AS_NODE = "gds.util.asNode(nodeId)"


# ---------------------------------------------------------------------------
# Neo4j GDS metrics
# ---------------------------------------------------------------------------


def ensure_projection(graph: str = "authorGraph") -> None:
    driver = get_driver()
    if not graph_exists(driver, graph):
        raise SystemExit(
            f"GDS projection '{graph}' is missing. Run: python -m analysis.load_neo4j --gds-only"
        )


def gds_metrics(graph: str = "authorGraph") -> dict[str, Any]:
    """Run every GDS algorithm used by Problem 1 and write the scores back."""
    driver = get_driver()
    ensure_projection(graph)
    out: dict[str, Any] = {}
    out["gds_version"] = scalar(driver, "RETURN gds.version()")

    print("  PageRank...", flush=True)
    pagerank = run(
        driver,
        f"""
        CALL gds.pageRank.stream('{graph}', {{maxIterations: 20, dampingFactor: 0.85}})
        YIELD nodeId, score
        RETURN {AS_NODE}.author_id AS id, {AS_NODE}.name AS name, score
        """,
    )
    pagerank.sort(key=lambda row: -row["score"])

    print("  k-core...", flush=True)
    # NOTE: in this GDS build (2.13.14) the procedure is spelled `gds.kcore.*`
    # and its output column is `coreValue` (not `coreness`).
    kcore = run(
        driver,
        f"""
        CALL gds.kcore.stream('{graph}')
        YIELD nodeId, coreValue
        RETURN {AS_NODE}.author_id AS id, {AS_NODE}.name AS name, coreValue AS coreness
        """,
    )
    kcore.sort(key=lambda row: -row["coreness"])

    print("  articulation points...", flush=True)
    articulation = run(
        driver,
        f"""
        CALL gds.articulationPoints.stream('{graph}')
        YIELD nodeId
        RETURN {AS_NODE}.author_id AS id, {AS_NODE}.name AS name
        """,
    )

    print("  bridges...", flush=True)
    bridges_raw = run(
        driver,
        f"""
        CALL gds.bridges.stream('{graph}')
        YIELD from, to
        WITH [from, to] AS pair
        RETURN gds.util.asNode(pair[0]).author_id AS source,
               gds.util.asNode(pair[1]).author_id AS target
        """,
    )
    unique_bridges: list[dict[str, str]] = []
    seen: set[frozenset[str]] = set()
    for row in bridges_raw:
        key = frozenset((row["source"], row["target"]))
        if key not in seen:
            seen.add(key)
            unique_bridges.append(row)

    print("  betweenness (exact)...", flush=True)
    betweenness = betweenness_stream(driver, graph)
    betweenness.sort(key=lambda row: -row["betweenness"])

    write_back(driver, graph, [row["id"] for row in articulation])

    out["pagerank"] = pagerank
    out["kcore"] = kcore
    out["articulation_points"] = articulation
    out["bridges"] = unique_bridges
    out["betweenness"] = betweenness
    return out


def betweenness_stream(driver, graph: str) -> list[dict[str, Any]]:
    """Exact Brandes betweenness, computed by GDS.

    Stage 8 removed source sampling: GDS ignored ``samplingSeed`` when its
    internal concurrency was greater than one, so sampled scores changed between
    runs. Exact Brandes is deterministic and takes about 35 s on this 14,574-node
    graph, which is cheap enough for reproducibility.
    """
    return run(
        driver,
        f"""
        CALL gds.betweenness.stream('{graph}')
        YIELD nodeId, score
        RETURN {AS_NODE}.author_id AS id, {AS_NODE}.name AS name, score AS betweenness
        """,
    )


def min_vertex_cut(component: nx.Graph, src: str, dst: str) -> dict[str, Any]:
    """Menger's theorem in Python (this GDS build has no maxFlow procedure).

    The maximum number of node-disjoint paths between two authors equals the
    size of the minimum vertex cut separating them. We measure it for the two
    most central researchers: it is the smallest set of co-authors whose exit
    would sever their connection.
    """
    import time as _time

    started = _time.time()
    cut = nx.minimum_node_cut(component, src, dst)
    return {
        "source_graph": "networkx.minimum_node_cut",
        "max_flow": len(cut),
        "min_cut_size": len(cut),
        "interpretation": "max node-disjoint co-authorship paths = minimum vertex cut (Menger)",
        "seconds": round(_time.time() - started, 1),
    }


def write_back(driver, graph: str, articulation_ids: list[str]) -> None:
    """Persist GDS node properties so later stages can query them in Cypher."""
    run(
        driver,
        f"CALL gds.pageRank.write('{graph}', {{writeProperty: 'pagerank', "
        "maxIterations: 20, dampingFactor: 0.85})",
    )
    run(
        driver,
        f"CALL gds.betweenness.write('{graph}', {{writeProperty: 'betweenness'}})",
    )
    run(driver, f"CALL gds.kcore.write('{graph}', {{writeProperty: 'kcore'}})")
    run(driver, "MATCH (a:Author) REMOVE a.articulation")
    run(
        driver,
        "UNWIND $ids AS id MATCH (a:Author {author_id: id}) SET a.articulation = true",
        ids=articulation_ids,
    )
    print(f"  wrote pagerank/betweenness/kcore; articulation flag on {len(articulation_ids)} authors")


# ---------------------------------------------------------------------------
# Python: failure simulation and null model
# ---------------------------------------------------------------------------


def cascade_curve(graph: nx.Graph, order: list[str], steps: int, chunk: int) -> list[dict[str, float]]:
    """Remove nodes in the given order and measure how the network breaks.

    Each entry holds the state AFTER the cumulative removals. We recompute the
    connected components each step, which is cheap (<20 ms) for this graph size.
    """
    result: list[dict[str, float]] = []
    working = graph.copy()
    for step in range(steps + 1):
        removed = step * chunk
        if step > 0:
            working.remove_nodes_from(order[(step - 1) * chunk : removed])
        sizes = [len(c) for c in nx.connected_components(working)]
        largest = max(sizes) if sizes else 0
        result.append(
            {
                "removed": removed,
                "lcc_fraction": round(largest / graph.number_of_nodes(), 4),
                "components": len(sizes),
            }
        )
    return result


def random_cascades(graph: nx.Graph, replicates: int, steps: int, chunk: int) -> list[list[dict[str, float]]]:
    """Repeat the random removal with different shuffles, seeds documented."""
    curves = []
    for replicate in range(replicates):
        rng = random.Random(1000 + replicate)  # deterministic seed scheme
        order = list(graph.nodes())
        rng.shuffle(order)
        curves.append(cascade_curve(graph, order, steps, chunk))
    return curves


def sampled_mean_distance(graph: nx.Graph, sources: int = BFS_SOURCES) -> float:
    """Mean shortest path from many sources inside the largest component.

    Exact all-pairs distances would be too slow, so we average over `sources`
    BFS trees. The sample size is reported in the output JSON.
    """
    component = largest_component(graph)
    if component.number_of_nodes() < 2:
        return 0.0
    rng = random.Random(SEED)
    picks = rng.sample(list(component.nodes()), min(sources, component.number_of_nodes()))
    total = 0
    count = 0
    for source in picks:
        distances = nx.single_source_shortest_path_length(component, source)
        total += sum(distances.values())
        count += len(distances) - 1  # exclude distance to self
    return round(total / count, 3) if count else 0.0


def attacked_distances(graph: nx.Graph, order: list[str], checkpoints: list[int]) -> dict[str, float]:
    """Mean distance within the remaining giant component after batch removals."""
    result: dict[str, float] = {}
    working = graph.copy()
    for checkpoint in checkpoints:
        working.remove_nodes_from(order[:checkpoint])
        result[str(checkpoint)] = sampled_mean_distance(working)
    return result


def null_model(graph: nx.Graph, steps: int, chunk: int) -> dict[str, Any]:
    """Configuration model: same degree sequence, uniformly rewired edges.

    This network-science null model answers whether fragility or clustering is a
    property of the degree sequence alone or of the real connection pattern.
    """
    rewired = graph.copy()
    edges = rewired.number_of_edges()
    # NOTE: in NetworkX 3.x double_edge_swap mutates the graph in place and
    # returns the graph itself (older versions returned the swap count).
    # It raises NetworkXError if it needed more than max_tries, so reaching
    # this line means all `nswap` swaps were completed.
    nx.double_edge_swap(
        rewired, nswap=max(1, edges), max_tries=max(100, 40 * edges), seed=SEED
    )
    swapped = edges  # every requested swap was performed (otherwise it raised)

    rng = random.Random(900)
    curves = [cascade_curve(rewired, rng.sample(list(rewired.nodes()), k=rewired.number_of_nodes()), steps, chunk)
              for _ in range(5)]

    return {
        "algorithm": "configuration model (degree-preserving double edge swap)",
        "swaps": swapped,
        "target_swaps": edges,
        "nodes": rewired.number_of_nodes(),
        "edges": rewired.number_of_edges(),
        "lcc_pct": round(
            100 * max(len(c) for c in nx.connected_components(rewired)) / rewired.number_of_nodes(), 2
        ),
        "avg_clustering": round(nx.average_clustering(rewired), 4),
        "random_curve_mean": [
            round(float(row["lcc_fraction"]), 4)
            for row in cascade_mean(curves)
        ],
    }


def cascade_mean(curves: list[list[dict[str, float]]]) -> list[dict[str, float]]:
    """Element-wise mean of several cascade curves."""
    import numpy as np

    matrix = np.array([[row["lcc_fraction"] for row in curve] for curve in curves])
    mean = matrix.mean(axis=0)
    return [{"lcc_fraction": value} for value in mean]


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def plot_degree_distribution(graph: nx.Graph) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    degrees = [d for _, d in graph.degree()]
    counts = Counter(degrees)
    xs, ys = zip(*sorted(counts.items()))
    axes[0].scatter(xs, ys, s=18, color=BLUE)
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("degree k")
    axes[0].set_ylabel("number of authors")
    axes[0].set_title("Degree distribution (log-log)")

    ranked = sorted(degrees, reverse=True)
    axes[1].plot(range(len(ranked)), ranked, color=BLUE)
    axes[1].set_xlabel("author rank")
    axes[1].set_ylabel("degree")
    ax_title = "Highly skewed: a few authors know everyone"
    axes[1].set_title(ax_title)
    save(fig, "fig_p1_degree_distribution.png")


def plot_cascade(
    curves: dict[str, Any],
    targets: int,
    chunk: int,
    steps: int,
    null_random_mean: list[float] | None,
) -> None:
    import numpy as np
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    xs = np.array([row["removed"] for row in curves["betweenness"]]) / targets
    styles = {
        "betweenness": (RED, "Targeted: betweenness"),
        "degree": (ORANGE, "Targeted: degree"),
        "pagerank": (PURPLE, "Targeted: PageRank"),
    }
    for key, (color, label) in styles.items():
        ax.plot(xs, [row["lcc_fraction"] for row in curves[key]], color=color, label=label)

    matrix = np.array(
        [[row["lcc_fraction"] for row in curve] for curve in curves["random_curves"]]
    )
    mean, std = matrix.mean(axis=0), matrix.std(axis=0)
    ax.plot(xs, mean, color=GREY, label=f"Random removal (mean of {len(curves['random_curves'])})")
    ax.fill_between(xs, mean - std, mean + std, color=GREY, alpha=0.25)
    if null_random_mean:
        ax.plot(xs, null_random_mean, color=GREY, linestyle="--", label="Null model, random removal")

    ax.set_xlabel("fraction of authors removed")
    ax.set_ylabel("largest component (fraction of original size)")
    ax.set_title("How fast does the network fall apart?")
    ax.legend(loc="lower left")
    ax.set_xlim(left=0)
    ax.set_ylim(0.4, 1.0)
    save(fig, "fig_p1_cascade.png")


def plot_top_authors(rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    top = rows[:15][::-1]
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.barh([row["name"] for row in top], [row["betweenness"] for row in top], color=RED)
    ax.set_xlabel("betweenness centrality (GDS, sampled)")
    ax.set_title("Top 15 critical authors by betweenness")
    ax.tick_params(axis="y", labelsize=8)
    save(fig, "fig_p1_top_authors.png")


def plot_kcore(rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt

    counts = Counter(row["coreness"] for row in rows)
    xs, ys = zip(*sorted(counts.items()))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(xs, ys, color=BLUE)
    ax.set_xlabel("k-core shell value")
    ax.set_ylabel("authors")
    ax.set_title("k-core decomposition of the core network")
    save(fig, "fig_p1_kcore.png")


def plot_network_map(
    graph: nx.Graph,
    betweenness: list[dict[str, Any]],
    articulation_ids: set[str],
    bridges: list[dict[str, str]],
) -> None:
    """A readable map of the critical part of the network.

    Induced subgraph on the top-120 betweenness authors only (no neighbour
    expansion, which would swallow the whole largest component).
    """
    import matplotlib.lines as mlines
    import matplotlib.pyplot as plt

    top_ids = [row["id"] for row in betweenness[:120]]
    subgraph = graph.subgraph(top_ids).copy()

    pos = nx.spring_layout(subgraph, seed=SEED, k=0.35)
    node_colors = [RED if node in articulation_ids else BLUE for node in subgraph.nodes()]
    node_sizes = [16 + 22 * subgraph.degree(node) ** 0.6 for node in subgraph.nodes()]
    bridge_edges = [
        (row["source"], row["target"])
        for row in bridges
        if subgraph.has_edge(row["source"], row["target"])
    ]

    fig, ax = plt.subplots(figsize=(11, 8))
    nx.draw_networkx_edges(subgraph, pos, ax=ax, alpha=0.2, edge_color=GREY)
    if bridge_edges:
        nx.draw_networkx_edges(
            subgraph, pos, edgelist=bridge_edges, ax=ax, edge_color=ORANGE, width=1.6
        )
    nx.draw_networkx_nodes(subgraph, pos, ax=ax, node_color=node_colors, node_size=node_sizes, alpha=0.9)
    ax.set_title(
        "Critical zone: co-authorship ties among the top-120 authors by betweenness\n"
        "red = articulation point, orange = bridge edge",
        fontsize=11,
    )
    ax.axis("off")
    handles = [
        mlines.Line2D([], [], color=RED, marker="o", linestyle="", label="articulation point"),
        mlines.Line2D([], [], color=BLUE, marker="o", linestyle="", label="other critical author"),
    ]
    ax.legend(handles=handles, loc="upper right")
    save(fig, "fig_p1_network_map.png")


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Problem 1: fragility analysis")
    parser.add_argument("--skip-null", action="store_true", help="skip the rewiring null model")
    args = parser.parse_args(argv)

    ensure_dirs()
    started = time.time()

    graph = load_core_graph()
    targets = graph.number_of_nodes()
    chunk = max(1, round(targets * STEP_FRACTION))
    steps = round(MAX_FRACTION / STEP_FRACTION)
    print(f"Core network: {targets} nodes, {graph.number_of_edges()} edges")
    print(f"Cascade: remove {chunk} authors per step, up to {steps} steps ({MAX_FRACTION:.0%} of the network)")

    gds = gds_metrics()
    betweenness = gds["betweenness"]
    pagerank = gds["pagerank"]
    kcore_rows = gds["kcore"]
    articulation_ids = {row["id"] for row in gds["articulation_points"]}

    if not betweenness:
        raise SystemExit("No betweenness scores were returned by GDS.")

    # Independent cross-check of the GDS articulation points with NetworkX.
    # articulation_points is defined per connected component, so run it on every
    # component of the core graph (the GDS stream covers all of them).
    local_articulation: set[str] = set()
    for component_nodes in nx.connected_components(graph):
        local_sub = graph.subgraph(component_nodes)
        local_articulation.update(nx.articulation_points(local_sub))
    local_component = largest_component(graph)  # reuse for min-cut and distances
    print(
        f"  articulation points: GDS {len(articulation_ids)} / NetworkX {len(local_articulation)}"
    )
    if len(articulation_ids) != len(local_articulation):
        print("  WARNING: GDS and NetworkX disagree (documented in the JSON output).")

    # Graph-theory check on the giant component: max node-disjoint paths between
    # two hubs == minimum vertex cut separating them (Menger's theorem).
    # The pair is chosen deterministically from exact node degrees (sampled
    # betweenness rankings can shuffle ties between runs): highest-degree author,
    # and the highest-degree author in a different institution who is not a
    # direct co-author. Removing that cut would sever the two hubs entirely.
    name_of = {row["id"]: row["name"] for row in betweenness}
    by_degree = sorted(
        graph.nodes(),
        key=lambda node: (
            -graph.degree(node),
            str(graph.nodes[node].get("institution", "")),
            str(graph.nodes[node].get("name", "")),
        ),
    )
    hub = by_degree[0]
    hub_inst = graph.nodes[hub].get("institution", "")
    partner = next(
        node
        for node in by_degree
        if graph.nodes[node].get("institution", "") != hub_inst
        and not graph.has_edge(hub, node)
    )
    print(
        f"  min vertex cut between '{name_of[hub]}' and '{name_of[partner]}'...",
        flush=True,
    )
    maxflow = min_vertex_cut(local_component, hub, partner)
    maxflow["source"] = name_of[hub]
    maxflow["target"] = name_of[partner]
    maxflow["source_institution"] = hub_inst
    maxflow["target_institution"] = graph.nodes[partner].get("institution", "")

    # Top-100 table for the report and later stages
    pagerank_by_id = {row["id"]: row["score"] for row in pagerank}
    kcore_by_id = {row["id"]: row["coreness"] for row in kcore_rows}
    critical = [
        {
            "author_id": row["id"],
            "name": row["name"],
            "institution": graph.nodes[row["id"]].get("institution", ""),
            "betweenness": round(row["betweenness"], 6),
            "pagerank": round(pagerank_by_id.get(row["id"], 0.0), 6),
            "degree": graph.degree(row["id"]),
            "strength": graph.degree(row["id"], weight="weight"),
            "kcore": kcore_by_id.get(row["id"], 0),
            "is_articulation": row["id"] in articulation_ids,
        }
        for row in betweenness[:100]
    ]
    with (RESULTS_DIR / "p1_critical_authors.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(critical[0].keys()))
        writer.writeheader()
        writer.writerows(critical)

    print("Failure simulation...", flush=True)
    orders = {
        "betweenness": [row["id"] for row in betweenness],
        "degree": sorted(graph.nodes(), key=lambda node: -graph.degree(node)),
        "pagerank": [row["id"] for row in pagerank],
    }
    curves: dict[str, Any] = {
        key: cascade_curve(graph, order, steps, chunk) for key, order in orders.items()
    }
    curves["random_curves"] = random_cascades(graph, RANDOM_REPLICATES, steps, chunk)

    import numpy as np

    random_matrix = np.array(
        [[row["lcc_fraction"] for row in curve] for curve in curves["random_curves"]]
    )

    def lcc_after(strategy: str, n_removed: int) -> float:
        index = min(n_removed // chunk, len(curves[strategy]) - 1)
        return curves[strategy][index]["lcc_fraction"]

    damage_summary = {
        # Fraction of ALL core-network nodes that belong to the LCC before any
        # removal (the core graph has 511 components, LCC is not 100%).
        "lcc_fraction_before": curves["betweenness"][0]["lcc_fraction"],
        "removed_50_by_betweenness": lcc_after("betweenness", 50),
        "removed_50_by_degree": lcc_after("degree", 50),
        "removed_50_by_pagerank": lcc_after("pagerank", 50),
        "random_mean_after_50": round(
            float(random_matrix[:, min(50 // chunk, steps)].mean()), 4
        ),
        "random_std_after_50": round(
            float(random_matrix[:, min(50 // chunk, steps)].std()), 4
        ),
    }

    print("Mean-distance sampling...", flush=True)
    distance_before = sampled_mean_distance(graph)
    distance_after = attacked_distances(graph, orders["betweenness"], [20, 50, 100])

    if args.skip_null:
        null: dict[str, Any] = {"skipped": True}
    else:
        print("Null model (configuration model)...", flush=True)
        null = null_model(graph, steps, chunk)

    real_clustering = round(nx.average_clustering(local_component), 4)

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": "python -m analysis.p1_fragility",
        "graph": graph_summary(graph),
        "graph_note": "core analysis network: authors with >=2 papers and >=1 co-author",
        "cascade": {
            "step_fraction": STEP_FRACTION,
            "max_fraction": MAX_FRACTION,
            "chunk": chunk,
            "steps": steps,
            "random_replicates": RANDOM_REPLICATES,
            "betweenness_mode": "exact",
            "curves": curves,
        },
        "damage_summary": damage_summary,
        "distances": {
            "sampled_mean_distance_before": distance_before,
            "after_removals_by_betweenness": distance_after,
            "bfs_sources": BFS_SOURCES,
        },
        "articulation": {
            "count": len(articulation_ids),
            "networkx_crosscheck": len(local_articulation),
            "pct_of_nodes": round(100 * len(articulation_ids) / targets, 2),
        },
        "bridges": {"count": len(gds["bridges"]), "pairs": gds["bridges"][:20]},
        "kcore": {
            "max": max(row["coreness"] for row in kcore_rows),
            "distribution": dict(Counter(row["coreness"] for row in kcore_rows)),
            "top": kcore_rows[:20],
        },
        "clustering": {
            "real_network": real_clustering,
            "null_model": null.get("avg_clustering"),
            "note": "average clustering on the largest component",
        },
        "null_model": {k: v for k, v in null.items() if k not in ("random_curves",)},
        "maxflow": maxflow,
        "pagerank_top20": pagerank[:20],
        "betweenness_top20": betweenness[:20],
        "gds_version": gds["gds_version"],
        "runtime_seconds": round(time.time() - started, 1),
    }
    (RESULTS_DIR / "p1_fragility.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    print("Figures...", flush=True)
    plot_degree_distribution(graph)
    plot_cascade(
        curves, targets, chunk, steps, None if "skipped" in null else null["random_curve_mean"]
    )
    plot_top_authors(betweenness)
    plot_kcore(kcore_rows)
    plot_network_map(graph, betweenness, articulation_ids, gds["bridges"])

    print()
    print(f"Nodes {targets}, edges {graph.number_of_edges()}")
    print(f"Articulation points: {len(articulation_ids)} ({result['articulation']['pct_of_nodes']}% of nodes)")
    print(f"Bridges: {len(gds['bridges'])}")
    print(f"Max k-core: {result['kcore']['max']}")
    print(f"Clustering: real {real_clustering} vs configuration-model {null.get('avg_clustering')}")
    print(
        "Removing 50 top-betweenness authors: LCC "
        f"{damage_summary['removed_50_by_betweenness'] * 100:.1f}% of original "
        f"(random mean {damage_summary['random_mean_after_50'] * 100:.1f}%)"
    )
    print(f"Max node-disjoint paths between the two most central authors: {maxflow.get('max_flow')}")
    print(f"Runtime: {result['runtime_seconds']}s")


if __name__ == "__main__":
    main()
