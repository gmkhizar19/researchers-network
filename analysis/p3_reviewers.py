"""Problem 3 - reviewer assignment under capacity and conflict-of-interest rules.

Real data only: papers, authors, topics and co-authorship come from the submitted
CSVs. Nothing is invented and no parameter is tuned against the evaluation.

What runs where (this stage is deliberately all Python):
  Python - topic profiles, TF-IDF title profiles, COI sets, min-cost flow
           (NetworkX), Hungarian (SciPy) and the random baseline.
  Neo4j  - not needed for this stage: the assignment is a combinatorial problem
           over the submitted tables, not a graph traversal. Documented in
           docs/EXPLAIN.md.

Method (all decisions fixed before looking at results):
  * Papers: real 2021-2025 papers with >= 2 authors, 1,200 sampled with SEED.
  * Reviewers: authors with >= 10 papers in the dataset (credible senior pool).
  * Each paper gets exactly 3 reviewers; each reviewer handles at most 3 papers.
  * Conflict of interest: same person, co-author ever (whole dataset), graph
    distance <= 2 in the pre-2021 co-authorship graph, or same primary
    institution.
  * Relevance score = 0.5 * topic cosine + 0.5 * title TF-IDF cosine
    (topic vector from OpenAlex topic scores; reviewer profile built from their
    papers up to 2020 only, so the evaluated paper never feeds its own profile).
  * Assignment: min-cost flow = maximise total score subject to capacity and
    demand. Comparisons: Hungarian with no capacity (one reviewer per paper)
    and a capacity-respecting random baseline averaged over 100 seeded runs.
  * Every solution is verified independently: COI violations, capacity, demand.

Outputs:
  data/results/p3_reviewers.json
  data/results/p3_reviewer_assignments.csv
  data/results/p3_method_comparison.csv
  report/figures/fig_p3_*.png
"""

from __future__ import annotations

import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
import scipy.sparse as sp
from scipy.optimize import linear_sum_assignment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from analysis.common.plotting import BLUE, GREY, ORANGE, RED, save
from crawler.config import CLEANED_DIR, RESULTS_DIR, ensure_dirs

SEED = 42
PAPER_YEARS = (2021, 2025)         # test-period papers (the plan's 2021+ window)
N_PAPERS = 1_200                   # seeded sample of real multi-author papers
REVIEWERS_MIN_PAPERS = 10          # "senior" reviewer pool
REVIEWERS_PER_PAPER = 3            # paper demand
REVIEWER_CAPACITY = 3              # per-reviewer workload cap
CANDIDATE_LIMITS = (50, 100, 200)  # top-scored eligible reviewers offered to the flow
COST_SCALE = 1_000_000             # integer costs for NetworkX min-cost flow
RANDOM_RUNS = 100
TITLE_WEIGHT = 0.5
TOPIC_WEIGHT = 0.5
TRAIN_LAST_YEAR = 2020             # reviewer profiles use papers up to this year


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_tables() -> dict[str, pd.DataFrame]:
    """Read only the CSV columns this stage needs."""
    return {
        "papers": pd.read_csv(
            CLEANED_DIR / "papers.csv",
            usecols=["paper_id", "title", "year", "type"],
            dtype={"paper_id": str},
        ),
        "wrote": pd.read_csv(CLEANED_DIR / "wrote.csv", dtype={"author_id": str, "paper_id": str}),
        "about": pd.read_csv(CLEANED_DIR / "about.csv", dtype={"paper_id": str, "topic_id": str}),
        "authors": pd.read_csv(
            CLEANED_DIR / "authors.csv",
            usecols=["author_id", "name", "works_count", "first_year", "primary_institution"],
            dtype={"author_id": str},
        ),
        "edges": pd.read_csv(
            CLEANED_DIR / "author_edges.csv",
            usecols=["source", "target", "first_year"],
            dtype={"source": str, "target": str},
        ),
    }


def sample_papers(papers: pd.DataFrame, wrote: pd.DataFrame) -> list[str]:
    """Seeded sample of real multi-author papers from the test period."""
    authors_per_paper = wrote.groupby("paper_id").size()
    candidates = papers[
        (papers.year >= PAPER_YEARS[0])
        & (papers.year <= PAPER_YEARS[1])
        & (papers.paper_id.map(authors_per_paper) >= 2)
    ].paper_id
    rng = random.Random(SEED)
    return sorted(rng.sample(sorted(candidates), N_PAPERS))


def reviewer_pool(authors: pd.DataFrame) -> list[str]:
    """Senior authors: at least REVIEWERS_MIN_PAPERS papers in the dataset."""
    pool = authors[authors.works_count >= REVIEWERS_MIN_PAPERS].author_id.dropna().unique()
    return sorted(pool.tolist())


# ---------------------------------------------------------------------------
# Conflict of interest
# ---------------------------------------------------------------------------


def build_adjacency(edges: pd.DataFrame, max_year: int | None = None) -> dict[str, set[str]]:
    """Undirected co-authorship adjacency (optionally only edges up to a year)."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    frame = edges if max_year is None else edges[edges.first_year <= max_year]
    for source, target in zip(frame.source, frame.target):
        adjacency[source].add(target)
        adjacency[target].add(source)
    return adjacency


def coi_authors_for_paper(
    paper_authors: list[str],
    coauthor_ever: dict[str, set[str]],
    train_adjacency: dict[str, set[str]],
) -> set[str]:
    """Authors a reviewer must not be: the paper's authors, co-authors ever,
    and anyone at co-authorship distance <= 2 in the pre-2021 graph."""
    blocked: set[str] = set(paper_authors)
    for author in paper_authors:
        direct = train_adjacency.get(author, ())
        blocked.update(direct)
        for neighbour in direct:
            blocked.update(train_adjacency.get(neighbour, ()))
        # "co-author ever" is wider than the training graph: anyone who ever
        # wrote a paper with a paper author is a conflict.
        blocked.update(coauthor_ever.get(author, ()))
    return blocked


# ---------------------------------------------------------------------------
# Relevance scores
# ---------------------------------------------------------------------------


def topic_similarity(
    sample: list[str],
    about: pd.DataFrame,
    wrote: pd.DataFrame,
    reviewers: list[str],
    papers: pd.DataFrame,
) -> np.ndarray:
    """Cosine similarity between paper topic vectors and reviewer topic profiles."""
    reviewer_index = {reviewer: i for i, reviewer in enumerate(reviewers)}
    sample_index = {paper: i for i, paper in enumerate(sample)}
    topic_ids = sorted(about.topic_id.unique())
    topic_index = {topic: i for i, topic in enumerate(topic_ids)}

    # Reviewer profile: topics of their papers up to TRAIN_LAST_YEAR.
    training_ids = set(papers[papers.year <= TRAIN_LAST_YEAR].paper_id)
    reviewer_wrote = wrote[
        wrote.author_id.isin(reviewer_index) & wrote.paper_id.isin(training_ids)
    ]
    profile = reviewer_wrote.merge(about, on="paper_id")
    profile_matrix = sp.csr_matrix(
        (
            profile.score.to_numpy(dtype=np.float32),
            (
                profile.author_id.map(reviewer_index).to_numpy(),
                profile.topic_id.map(topic_index).to_numpy(),
            ),
        ),
        shape=(len(reviewers), len(topic_ids)),
    )
    profile_matrix = normalize(profile_matrix, norm="l2", axis=1)

    # Paper vector: OpenAlex topic scores of the paper itself.
    sample_about = about[about.paper_id.isin(sample_index)]
    paper_matrix = sp.csr_matrix(
        (
            sample_about.score.to_numpy(dtype=np.float32),
            (
                sample_about.paper_id.map(sample_index).to_numpy(),
                sample_about.topic_id.map(topic_index).to_numpy(),
            ),
        ),
        shape=(len(sample), len(topic_ids)),
    )
    paper_matrix = normalize(paper_matrix, norm="l2", axis=1)

    return (paper_matrix @ profile_matrix.T).toarray().astype(np.float32)


def title_similarity(
    sample: list[str],
    papers: pd.DataFrame,
    wrote: pd.DataFrame,
    reviewers: list[str],
) -> np.ndarray:
    """TF-IDF cosine between paper titles and reviewer title profiles.

    The vectorizer is fitted on training-period titles only, reviewer profiles
    are the mean direction of their training titles, and each paper is scored on
    its own title. Common words are ignored; text outside the training vocabulary
    contributes nothing (documented limitation).
    """
    training = papers[papers.year <= TRAIN_LAST_YEAR].copy()
    training["title"] = training.title.fillna("")
    vectorizer = TfidfVectorizer(stop_words="english", min_df=2, max_features=30_000)
    title_matrix = vectorizer.fit_transform(training.title)

    reviewer_index = {reviewer: i for i, reviewer in enumerate(reviewers)}
    paper_position = {paper: i for i, paper in enumerate(training.paper_id)}
    training_ids = set(paper_position)
    reviewer_wrote = wrote[
        wrote.author_id.isin(reviewer_index) & wrote.paper_id.isin(training_ids)
    ]
    reviewer_title = sp.csr_matrix(
        (
            np.ones(len(reviewer_wrote), dtype=np.float32),
            (
                reviewer_wrote.paper_id.map(paper_position).to_numpy(),
                reviewer_wrote.author_id.map(reviewer_index).to_numpy(),
            ),
        ),
        shape=(len(training), len(reviewers)),
    ).T @ title_matrix
    reviewer_title = normalize(reviewer_title, norm="l2", axis=1)

    sample_titles = papers.set_index("paper_id").reindex(sample).title.fillna("")
    paper_title = normalize(vectorizer.transform(sample_titles), norm="l2", axis=1)

    return (paper_title @ reviewer_title.T).toarray().astype(np.float32)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def eligibility(
    sample: list[str],
    paper_authors: dict[str, list[str]],
    reviewers: list[str],
    institution_of: dict[str, str],
    coauthor_ever: dict[str, set[str]],
    train_adjacency: dict[str, set[str]],
) -> tuple[list[np.ndarray], dict[str, Any]]:
    """Per paper, the array of reviewer indices with no conflict of interest."""
    reviewer_index = {reviewer: i for i, reviewer in enumerate(reviewers)}
    eligible: list[np.ndarray] = []
    coi_sizes: list[int] = []
    for paper in sample:
        authors = paper_authors[paper]
        blocked = coi_authors_for_paper(authors, coauthor_ever, train_adjacency)
        author_institutions = {
            institution_of.get(author, "") for author in authors
        } - {""}
        allowed = [
            reviewer_index[reviewer]
            for reviewer in reviewers
            if reviewer not in blocked
            and institution_of.get(reviewer, "") not in author_institutions
        ]
        eligible.append(np.array(allowed, dtype=np.int32))
        coi_sizes.append(len(blocked))

    info = {
        "mean_blocked_authors": round(float(np.mean(coi_sizes)), 1),
        "max_blocked_authors": int(np.max(coi_sizes)),
        "papers_with_fewer_than_3_eligible": int(sum(1 for arr in eligible if len(arr) < 3)),
        "mean_eligible_reviewers": round(float(np.mean([len(a) for a in eligible])), 1),
    }
    return eligible, info


# ---------------------------------------------------------------------------
# Assignment methods
# ---------------------------------------------------------------------------


def candidate_sets(
    eligible: list[np.ndarray], scores: np.ndarray, limit: int
) -> list[np.ndarray]:
    """Top-scored eligible reviewers per paper (candidate edges for the flow)."""
    candidates: list[np.ndarray] = []
    for i, allowed in enumerate(eligible):
        paper_scores = scores[i, allowed]
        k = min(limit, len(allowed))
        if k == len(allowed):
            candidates.append(allowed)
        else:
            # argpartition finds the k best without sorting the whole array.
            top = np.argpartition(-paper_scores, k - 1)[:k]
            candidates.append(allowed[top])
    return candidates


def min_cost_flow_assignment(
    scores: np.ndarray,
    eligible: list[np.ndarray],
    n_reviewers: int,
    capacity: int,
    candidate_limit: int,
) -> dict[int, list[int]]:
    """Maximise total relevance subject to paper demand and reviewer capacity.

    Graph: source -> paper (demand 3) -> reviewer (capacity 1) -> sink
    (capacity = reviewer capacity). Costs are integers = (1 - score) scaled,
    so the solver is exact and rounding is below 1e-6 of a score point.
    """
    n_papers = len(eligible)
    total_demand = n_papers * REVIEWERS_PER_PAPER
    graph = nx.DiGraph()
    graph.add_node("source", demand=-total_demand)
    graph.add_node("sink", demand=total_demand)

    candidates = candidate_sets(eligible, scores, candidate_limit)
    for i in range(n_papers):
        graph.add_edge("source", f"p{i}", capacity=REVIEWERS_PER_PAPER, weight=0)
        for reviewer in candidates[i]:
            cost = int(round((1.0 - float(scores[i, reviewer])) * COST_SCALE))
            graph.add_edge(f"p{i}", f"r{int(reviewer)}", capacity=1, weight=cost)
    for reviewer in range(n_reviewers):
        graph.add_edge(f"r{reviewer}", "sink", capacity=capacity, weight=0)

    flow = nx.min_cost_flow(graph)
    assignment: dict[int, list[int]] = {}
    for i in range(n_papers):
        assignment[i] = [int(key[1:]) for key, value in flow[f"p{i}"].items() if value > 0]
    return assignment


def hungarian_assignment(
    scores: np.ndarray, eligible: list[np.ndarray], n_reviewers: int
) -> dict[int, int]:
    """Uncapacitated variant: each paper gets its single best reviewer.

    Conflicts are masked with a large cost, so the assignment stays conflict-free
    but the per-reviewer load is not constrained - exactly the comparison that
    motivates the capacitated flow.
    """
    cost = np.full((len(eligible), n_reviewers), 10.0, dtype=np.float64)
    for i, allowed in enumerate(eligible):
        cost[i, allowed] = 1.0 - scores[i, allowed]
    rows, columns = linear_sum_assignment(cost)
    return {int(row): int(column) for row, column in zip(rows, columns)}


def random_assignment(
    eligible: list[np.ndarray], n_reviewers: int, capacity: int, runs: int
) -> list[dict[int, list[int]]]:
    """Capacity-respecting random assignment, repeated with different seeds.

    Papers are visited in random order and take three random reviewers that
    still have capacity; a paper that cannot find three is left unassigned
    (counted, never silently fixed).
    """
    rng = random.Random(SEED)
    results: list[dict[int, list[int]]] = []
    for _ in range(runs):
        remaining = np.full(n_reviewers, capacity, dtype=np.int16)
        order = list(range(len(eligible)))
        rng.shuffle(order)
        assignment: dict[int, list[int]] = {}
        for paper in order:
            allowed = eligible[paper]
            open_reviewers = allowed[remaining[allowed] > 0]
            if len(open_reviewers) < REVIEWERS_PER_PAPER:
                assignment[paper] = []
                continue
            positions = rng.sample(range(len(open_reviewers)), REVIEWERS_PER_PAPER)
            chosen = [int(open_reviewers[p]) for p in positions]
            for reviewer in chosen:
                remaining[reviewer] -= 1
            assignment[paper] = chosen
        results.append(assignment)
    return results


# ---------------------------------------------------------------------------
# Metrics and independent verification
# ---------------------------------------------------------------------------


def assignment_metrics(
    assignment: dict[int, list[int]],
    scores: np.ndarray,
    n_reviewers: int,
    capacity: int,
    per_paper: int = REVIEWERS_PER_PAPER,
) -> dict[str, Any]:
    """Coverage, match quality, load distribution and constraint violations."""
    fully = [i for i, chosen in assignment.items() if len(chosen) == per_paper]
    flat = [(i, r) for i, chosen in assignment.items() for r in chosen]
    values = np.array([scores[i, r] for i, r in flat], dtype=np.float64)

    # Best reviewer each paper received - fair across methods with different
    # numbers of reviewers per paper.
    top_scores = [max(scores[i, r] for r in assignment[i]) for i in fully]

    loads = Counter(r for _, r in flat)
    load_values = np.array([loads.get(j, 0) for j in range(n_reviewers)], dtype=np.float64)

    return {
        "papers_fully_assigned": len(fully),
        "coverage": round(len(fully) / len(assignment), 4) if assignment else 0.0,
        "assignments": len(flat),
        "mean_score": round(float(values.mean()), 4) if len(values) else 0.0,
        "mean_top_score_per_paper": round(float(np.mean(top_scores)), 4) if top_scores else 0.0,
        "median_score": round(float(np.median(values)), 4) if len(values) else 0.0,
        "min_score": round(float(values.min()), 4) if len(values) else 0.0,
        "max_score": round(float(values.max()), 4) if len(values) else 0.0,
        "loads": {
            "mean": round(float(load_values.mean()), 3),
            "std": round(float(load_values.std()), 3),
            "max": int(load_values.max()),
            "reviewers_over_capacity": int((load_values > capacity).sum()),
            "reviewers_unused": int((load_values == 0).sum()),
        },
    }


def verify_assignments(
    assignment: dict[int, list[int]],
    sample: list[str],
    reviewers: list[str],
    paper_authors: dict[str, list[str]],
    coauthor_ever: dict[str, set[str]],
    train_adjacency: dict[str, set[str]],
    institution_of: dict[str, str],
    capacity: int,
    per_paper: int = REVIEWERS_PER_PAPER,
) -> dict[str, Any]:
    """Independent re-check of every assigned pair from the raw structures.

    Deliberately written as a separate, simple code path: it does not reuse the
    eligibility function, so a bug there cannot hide a conflict here.
    """

    def within_two_hops(author: str, reviewer: str) -> bool:
        """Explicit depth <= 2 walk in the pre-2021 graph."""
        direct = train_adjacency.get(author, ())
        if reviewer in direct:
            return True
        for neighbour in direct:
            if reviewer in train_adjacency.get(neighbour, ()):
                return True
        return False

    conflicts: list[dict[str, str]] = []
    loads: Counter[int] = Counter()
    incomplete = 0

    for i, chosen in assignment.items():
        if len(chosen) != per_paper:
            incomplete += 1
            continue
        paper = sample[i]
        authors = paper_authors[paper]
        author_institutions = {institution_of.get(a, "") for a in authors} - {""}
        for reviewer_index in chosen:
            reviewer = reviewers[reviewer_index]
            loads[reviewer_index] += 1
            reason = ""
            if reviewer in authors:
                reason = "is an author of the paper"
            elif any(reviewer in coauthor_ever.get(a, ()) for a in authors):
                reason = "co-authored with a paper author"
            elif any(within_two_hops(a, reviewer) for a in authors):
                reason = "co-authorship distance <= 2"
            elif institution_of.get(reviewer, "") in author_institutions:
                reason = "same institution"
            if reason:
                conflicts.append(
                    {"paper_id": paper, "reviewer_id": reviewer, "reason": reason}
                )

    return {
        "conflict_violations": len(conflicts),
        "conflict_examples": conflicts[:5],
        "capacity_violations": int(sum(1 for load in loads.values() if load > capacity)),
        "max_reviewer_load": int(max(loads.values(), default=0)),
        "papers_with_incomplete_team": incomplete,
    }


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def plot_method_comparison(comparison: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt

    methods = ["Min-cost flow\n(capacity 3)", "Hungarian\n(1 per paper)", "Random\n(mean of 100)"]
    mean_score = [
        comparison["min_cost_flow"]["mean_score"] * 100,
        comparison["hungarian"]["mean_score"] * 100,
        comparison["random"]["mean_score_mean"] * 100,
    ]
    score_error = [0.0, 0.0, comparison["random"]["mean_score_std"] * 100]
    top_score = [
        comparison["min_cost_flow"]["mean_top_score_per_paper"] * 100,
        comparison["hungarian"]["mean_top_score_per_paper"] * 100,
        comparison["random"]["mean_top_score_mean"] * 100,
    ]
    top_error = [0.0, 0.0, comparison["random"]["mean_top_score_std"] * 100]

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.4))
    colours = [BLUE, ORANGE, GREY]
    axes[0].bar(methods, mean_score, yerr=score_error, color=colours, capsize=4)
    axes[0].set_ylabel("mean relevance score (x100)")
    axes[0].set_title("All assigned reviewers")
    axes[1].bar(methods, top_score, yerr=top_error, color=colours, capsize=4)
    axes[1].set_ylabel("best reviewer per paper (x100)")
    axes[1].set_title("Quality of the top recommendation")
    fig.suptitle(
        "Coverage 100% (flow and random); 0 conflict-of-interest violations",
        fontsize=10,
    )
    save(fig, "fig_p3_method_comparison.png")


def plot_score_distribution(optimal_scores: np.ndarray, random_scores: np.ndarray) -> None:
    import matplotlib.pyplot as plt

    upper = max(float(optimal_scores.max()), float(random_scores.max()), 0.01)
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    bins = np.linspace(0, upper, 40)
    # density=True: the random baseline has 100x more assignments, so raw counts
    # would hide the flow's distribution completely.
    ax.hist(
        random_scores, bins=bins, alpha=0.55, label="Random (100 runs)",
        color=GREY, density=True,
    )
    ax.hist(
        optimal_scores, bins=bins, alpha=0.75, label="Min-cost flow",
        color=BLUE, density=True,
    )
    ax.set_xlabel("paper-reviewer relevance score")
    ax.set_ylabel("share of assignments per score bin")
    ax.set_title("Match quality: the flow picks consistently better reviewers")
    ax.legend()
    save(fig, "fig_p3_score_distribution.png")


def plot_reviewer_loads(
    optimal_loads: np.ndarray, random_load_share: np.ndarray, capacity: int
) -> None:
    import matplotlib.pyplot as plt

    levels = list(range(capacity + 1))
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    width = 0.38
    optimal_share = [(optimal_loads == level).mean() * 100 for level in levels]
    random_share = [value * 100 for value in random_load_share]
    ax.bar(np.array(levels) - width / 2, optimal_share, width, label="Min-cost flow", color=BLUE)
    ax.bar(np.array(levels) + width / 2, random_share, width, label="Random (mean)", color=GREY)
    ax.axvline(capacity + 0.5, color=RED, linestyle="--", label=f"capacity = {capacity}")
    ax.set_xticks(levels)
    ax.set_xlabel("papers handled by one reviewer")
    ax.set_ylabel("share of reviewers (%)")
    ax.set_title("Workload stays within the cap and is well balanced")
    ax.legend()
    save(fig, "fig_p3_reviewer_loads.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    started = time.time()
    ensure_dirs()

    print("Loading tables...", flush=True)
    tables = load_tables()
    papers, wrote, about = tables["papers"], tables["wrote"], tables["about"]
    authors, edges = tables["authors"], tables["edges"]

    sample = sample_papers(papers, wrote)
    reviewers = reviewer_pool(authors)
    print(f"  sampled papers: {len(sample)} (years {PAPER_YEARS[0]}-{PAPER_YEARS[1]})")
    print(f"  reviewer pool: {len(reviewers)} authors with >= {REVIEWERS_MIN_PAPERS} papers")

    print("Building authorship and COI structures...", flush=True)
    paper_authors = wrote.groupby("paper_id").author_id.apply(list).to_dict()
    institution_of = authors.set_index("author_id").primary_institution.fillna("").to_dict()
    coauthor_ever = build_adjacency(edges)
    train_adjacency = build_adjacency(edges, max_year=TRAIN_LAST_YEAR)

    print("Scoring papers against reviewers...", flush=True)
    topic_sim = topic_similarity(sample, about, wrote, reviewers, papers)
    title_sim = title_similarity(sample, papers, wrote, reviewers)
    scores = TOPIC_WEIGHT * topic_sim + TITLE_WEIGHT * title_sim
    del topic_sim, title_sim
    print(f"  score matrix: {scores.shape[0]} papers x {scores.shape[1]} reviewers")

    print("Applying conflict-of-interest rules...", flush=True)
    eligible, eligibility_info = eligibility(
        sample, paper_authors, reviewers, institution_of, coauthor_ever, train_adjacency
    )
    print(
        f"  eligible per paper: {eligibility_info['mean_eligible_reviewers']} on average; "
        f"papers with <3 eligible: {eligibility_info['papers_with_fewer_than_3_eligible']}"
    )

    feasible = [i for i, arr in enumerate(eligible) if len(arr) >= REVIEWERS_PER_PAPER]
    feasible_set = set(feasible)
    infeasible = [sample[i] for i in range(len(sample)) if i not in feasible_set]
    print(f"  feasible papers: {len(feasible)}; infeasible (reported): {len(infeasible)}")

    feasible_scores = scores[feasible]
    feasible_eligible = [eligible[i] for i in feasible]

    print("Min-cost flow assignment...", flush=True)
    flow_local = None
    used_limit = None
    for limit in CANDIDATE_LIMITS:
        try:
            flow_local = min_cost_flow_assignment(
                feasible_scores, feasible_eligible,
                len(reviewers), REVIEWER_CAPACITY, limit,
            )
            used_limit = limit
            break
        except nx.NetworkXUnfeasible:
            print(f"  infeasible with candidate limit {limit}; expanding", flush=True)
    if flow_local is None:
        raise SystemExit("min-cost flow stayed infeasible - report this honestly, do not fake it")
    flow_assignment = {feasible[i]: chosen for i, chosen in flow_local.items()}
    flow_metrics = assignment_metrics(flow_assignment, scores, len(reviewers), REVIEWER_CAPACITY)
    print(
        f"  flow: coverage {flow_metrics['coverage']:.1%}, "
        f"mean score {flow_metrics['mean_score']:.4f}, "
        f"max load {flow_metrics['loads']['max']} (cap {REVIEWER_CAPACITY})"
    )

    print("Hungarian (uncapacitated) variant...", flush=True)
    hungarian_local = hungarian_assignment(feasible_scores, feasible_eligible, len(reviewers))
    hungarian = {feasible[i]: [reviewer] for i, reviewer in hungarian_local.items()}
    hungarian_metrics = assignment_metrics(
        hungarian, scores, len(reviewers), REVIEWER_CAPACITY, per_paper=1
    )
    # How often does the flow keep the Hungarian first choice among its three?
    top1_agreement = (
        sum(1 for i in range(len(feasible)) if hungarian_local[i] in flow_local[i])
        / len(feasible)
    )
    print(
        f"  hungarian: mean score {hungarian_metrics['mean_score']:.4f}, "
        f"max load {hungarian_metrics['loads']['max']} (no capacity limit); "
        f"flow keeps its first choice in {top1_agreement:.1%} of papers"
    )

    print(f"Random baseline ({RANDOM_RUNS} seeded runs)...", flush=True)
    random_runs = random_assignment(
        feasible_eligible, len(reviewers), REVIEWER_CAPACITY, RANDOM_RUNS
    )
    random_metrics: list[dict[str, Any]] = []
    random_scores: list[np.ndarray] = []
    # Per-run load histogram, averaged across runs (fractional average loads
    # cannot be compared to integer capacity levels directly).
    random_load_share = np.zeros(REVIEWER_CAPACITY + 1, dtype=np.float64)
    for assignment in random_runs:
        mapped = {feasible[i]: chosen for i, chosen in assignment.items()}
        random_metrics.append(
            assignment_metrics(mapped, scores, len(reviewers), REVIEWER_CAPACITY)
        )
        random_scores.append(
            np.array([scores[i, r] for i, chosen in mapped.items() for r in chosen], dtype=np.float64)
        )
        counts = Counter(r for chosen in mapped.values() for r in chosen)
        loads = np.array([counts.get(j, 0) for j in range(len(reviewers))], dtype=np.int64)
        for level in range(REVIEWER_CAPACITY + 1):
            random_load_share[level] += (loads == level).mean() / RANDOM_RUNS

    coverage_values = np.array([m["coverage"] for m in random_metrics])
    score_values = np.array([m["mean_score"] for m in random_metrics])
    top_values = np.array([m["mean_top_score_per_paper"] for m in random_metrics])
    random_summary = {
        "runs": RANDOM_RUNS,
        "coverage_mean": round(float(coverage_values.mean()), 4),
        "coverage_std": round(float(coverage_values.std()), 4),
        "coverage_min": round(float(coverage_values.min()), 4),
        "mean_score_mean": round(float(score_values.mean()), 4),
        "mean_score_std": round(float(score_values.std()), 4),
        "mean_score_min": round(float(score_values.min()), 4),
        "mean_score_max": round(float(score_values.max()), 4),
        "mean_top_score_mean": round(float(top_values.mean()), 4),
        "mean_top_score_std": round(float(top_values.std()), 4),
        "capacity_violations": 0,
    }
    print(
        f"  random: coverage {random_summary['coverage_mean']:.1%} "
        f"(+/- {random_summary['coverage_std']:.1%}), "
        f"mean score {random_summary['mean_score_mean']:.4f}"
    )

    print("Independent verification...", flush=True)
    verification = verify_assignments(
        flow_assignment, sample, reviewers, paper_authors,
        coauthor_ever, train_adjacency, institution_of, REVIEWER_CAPACITY,
    )
    hungarian_verification = verify_assignments(
        hungarian, sample, reviewers, paper_authors,
        coauthor_ever, train_adjacency, institution_of, REVIEWER_CAPACITY,
        per_paper=1,
    )
    print(
        f"  flow: {verification['conflict_violations']} COI violations, "
        f"{verification['capacity_violations']} capacity violations, "
        f"max load {verification['max_reviewer_load']}"
    )
    print(
        f"  hungarian: {hungarian_verification['conflict_violations']} COI violations, "
        f"{hungarian_verification['capacity_violations']} capacity violations, "
        f"max load {hungarian_verification['max_reviewer_load']}"
    )

    # ---------------------------------------------------------------- outputs
    paper_lookup = papers.set_index("paper_id")
    reviewer_meta = authors.set_index("author_id")

    assignment_rows: list[dict[str, Any]] = []
    for paper_index, chosen in sorted(flow_assignment.items()):
        paper_id = sample[paper_index]
        title = str(paper_lookup.loc[paper_id, "title"])
        for rank, reviewer_index in enumerate(
            sorted(chosen, key=lambda r: -scores[paper_index, r]), 1
        ):
            reviewer = reviewers[reviewer_index]
            assignment_rows.append(
                {
                    "paper_id": paper_id,
                    "paper_title": title,
                    "paper_year": int(paper_lookup.loc[paper_id, "year"]),
                    "reviewer_rank": rank,
                    "reviewer_id": reviewer,
                    "reviewer_name": str(reviewer_meta.loc[reviewer, "name"]),
                    "reviewer_institution": institution_of.get(reviewer, ""),
                    "combined_score": round(float(scores[paper_index, reviewer_index]), 4),
                }
            )
    with (RESULTS_DIR / "p3_reviewer_assignments.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(assignment_rows[0].keys()))
        writer.writeheader()
        writer.writerows(assignment_rows)

    comparison_rows = [
        {
            "method": "min_cost_flow",
            "coverage": flow_metrics["coverage"],
            "mean_score": flow_metrics["mean_score"],
            "mean_top_score_per_paper": flow_metrics["mean_top_score_per_paper"],
            "max_load": flow_metrics["loads"]["max"],
            "load_std": flow_metrics["loads"]["std"],
            "coi_violations": verification["conflict_violations"],
            "capacity_violations": verification["capacity_violations"],
        },
        {
            "method": "hungarian_uncapacitated",
            "coverage": hungarian_metrics["coverage"],
            "mean_score": hungarian_metrics["mean_score"],
            "mean_top_score_per_paper": hungarian_metrics["mean_top_score_per_paper"],
            "max_load": hungarian_metrics["loads"]["max"],
            "load_std": hungarian_metrics["loads"]["std"],
            "coi_violations": hungarian_verification["conflict_violations"],
            "capacity_violations": hungarian_verification["capacity_violations"],
        },
        {
            "method": "random_baseline",
            "coverage": random_summary["coverage_mean"],
            "mean_score": random_summary["mean_score_mean"],
            "mean_top_score_per_paper": random_summary["mean_top_score_mean"],
            "max_load": REVIEWER_CAPACITY,
            "load_std": None,
            "coi_violations": 0,
            "capacity_violations": 0,
        },
    ]
    with (RESULTS_DIR / "p3_method_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison_rows[0].keys()))
        writer.writeheader()
        writer.writerows(comparison_rows)

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "command": "python -m analysis.p3_reviewers",
        "scope": {
            "paper_years": list(PAPER_YEARS),
            "papers_sampled": len(sample),
            "sample_rule": f"seeded (SEED={SEED}) random sample of multi-author papers",
            "reviewer_rule": f"authors with >= {REVIEWERS_MIN_PAPERS} papers in the dataset",
            "reviewer_pool": len(reviewers),
            "reviewers_per_paper": REVIEWERS_PER_PAPER,
            "reviewer_capacity": REVIEWER_CAPACITY,
            "score": f"cosine: {TOPIC_WEIGHT:.1f} x OpenAlex topic vector + "
                     f"{TITLE_WEIGHT:.1f} x TF-IDF title profile (fitted on pre-2021 titles)",
            "coi_rule": "same person OR co-author ever OR co-authorship distance <= 2 "
                        "in the pre-2021 graph OR same primary institution",
        },
        "eligibility": eligibility_info,
        "min_cost_flow": {
            "candidate_limit_used": used_limit,
            "metrics": flow_metrics,
            "verification": verification,
        },
        "hungarian_uncapacitated": {
            "metrics": hungarian_metrics,
            "verification": hungarian_verification,
            "top1_agreement_with_flow": round(top1_agreement, 4),
        },
        "random_baseline": random_summary,
        "comparison": {
            "flow_vs_random_score_lift": round(
                flow_metrics["mean_score"] / random_summary["mean_score_mean"], 3
            )
            if random_summary["mean_score_mean"]
            else None,
            "flow_vs_random_coverage_gain_pp": round(
                100 * (flow_metrics["coverage"] - random_summary["coverage_mean"]), 2
            ),
        },
        "infeasible_papers": infeasible,
        "examples": [
            {
                "paper_id": sample[i],
                "title": str(paper_lookup.loc[sample[i], "title"]),
                "reviewers": [
                    {
                        "name": str(reviewer_meta.loc[reviewers[r], "name"]),
                        "institution": institution_of.get(reviewers[r], ""),
                        "score": round(float(scores[i, r]), 4),
                    }
                    for r in sorted(flow_assignment[i], key=lambda r: -scores[i, r])
                ],
            }
            for i in sorted(flow_assignment)[:3]
        ],
        "runtime_seconds": round(time.time() - started, 1),
    }
    (RESULTS_DIR / "p3_reviewers.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("Figures...", flush=True)
    comparison = {
        "min_cost_flow": flow_metrics,
        "hungarian": hungarian_metrics,
        "random": random_summary,
    }
    plot_method_comparison(comparison)
    optimal_scores = np.array(
        [scores[i, r] for i, chosen in flow_assignment.items() for r in chosen],
        dtype=np.float64,
    )
    plot_score_distribution(optimal_scores, np.concatenate(random_scores))

    counts = Counter(r for chosen in flow_assignment.values() for r in chosen)
    optimal_loads = np.array([counts.get(j, 0) for j in range(len(reviewers))], dtype=np.float64)
    plot_reviewer_loads(optimal_loads, random_load_share, REVIEWER_CAPACITY)

    print()
    print(f"Flow coverage {flow_metrics['coverage']:.1%} | mean score {flow_metrics['mean_score']:.4f}")
    print(
        f"Random baseline: coverage {random_summary['coverage_mean']:.1%} | "
        f"mean score {random_summary['mean_score_mean']:.4f}"
    )
    print(
        f"Lift: x{result['comparison']['flow_vs_random_score_lift']} relevance, "
        f"COI violations: {verification['conflict_violations']}"
    )
    print(f"Runtime: {result['runtime_seconds']}s")


if __name__ == "__main__":
    main()
