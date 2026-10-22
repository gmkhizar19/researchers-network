"""Unit tests for the Problem 3 logic (COI rules, scoring metrics, matchers).

Tiny hand-made graphs are used here on purpose: these tests check the *logic*,
not the dataset. The real numbers are covered by the analysis outputs.
"""

from __future__ import annotations

from collections import Counter

import networkx as nx
import numpy as np
import pandas as pd
import pytest

import analysis.p3_reviewers as p3


def test_seed_is_fixed() -> None:
    assert p3.SEED == 42


def test_build_adjacency_is_undirected_and_year_filtered() -> None:
    edges = pd.DataFrame(
        {
            "source": ["A", "B"],
            "target": ["B", "C"],
            "first_year": [2019, 2021],
        }
    )
    full = p3.build_adjacency(edges)
    assert full["A"] == {"B"}
    assert full["B"] == {"A", "C"}

    train = p3.build_adjacency(edges, max_year=2020)
    assert train["B"] == {"A"}
    assert "C" not in train


def test_coi_blocks_author_coauthor_and_two_hops() -> None:
    train = {"A": {"B", "C"}, "C": {"D"}}
    ever = {"A": {"B", "E"}}

    blocked = p3.coi_authors_for_paper(["A"], ever, train)

    assert {"A", "B", "C", "D", "E"} <= blocked
    assert "F" not in blocked


def test_verify_assignments_detects_every_conflict_type() -> None:
    sample = ["P1"]
    reviewers = ["A", "B", "C", "D", "E"]
    paper_authors = {"P1": ["A"]}
    coauthor_ever = {"A": {"B"}}
    train_adjacency = {"A": {"C"}}
    institution_of = {"A": "I1", "B": "I2", "C": "I3", "D": "I1", "E": "I4"}

    # Assignments store reviewer *indices* into the reviewers list.
    conflicts = p3.verify_assignments(
        {0: [0, 1, 2]},  # A (author), B (co-author), C (distance 1)
        sample,
        reviewers,
        paper_authors,
        coauthor_ever,
        train_adjacency,
        institution_of,
        capacity=3,
    )
    assert conflicts["conflict_violations"] == 3

    same_institution = p3.verify_assignments(
        {0: [3]},  # D shares the institution with author A
        sample,
        reviewers,
        paper_authors,
        coauthor_ever,
        train_adjacency,
        institution_of,
        capacity=3,
        per_paper=1,
    )
    assert same_institution["conflict_violations"] == 1
    assert same_institution["conflict_examples"][0]["reason"] == "same institution"

    clean = p3.verify_assignments(
        {0: [4]},  # E is unrelated
        sample,
        reviewers,
        paper_authors,
        coauthor_ever,
        train_adjacency,
        institution_of,
        capacity=3,
        per_paper=1,
    )
    assert clean["conflict_violations"] == 0
    assert clean["capacity_violations"] == 0


def test_assignment_metrics_coverage_and_loads() -> None:
    scores = np.array([[0.9, 0.5], [0.8, 0.4]])
    assignment = {0: [0, 1], 1: [0, 1]}

    metrics = p3.assignment_metrics(
        assignment, scores, n_reviewers=2, capacity=2, per_paper=2
    )

    assert metrics["coverage"] == 1.0
    assert metrics["mean_score"] == 0.65
    assert metrics["mean_top_score_per_paper"] == 0.85
    assert metrics["loads"]["max"] == 2
    assert metrics["loads"]["reviewers_unused"] == 0


def test_min_cost_flow_respects_capacity() -> None:
    # Four papers, four reviewers, capacity 3: exactly 12 slots for 12 demand.
    scores = np.full((4, 4), 0.1)
    np.fill_diagonal(scores, 0.9)
    eligible = [np.arange(4) for _ in range(4)]

    assignment = p3.min_cost_flow_assignment(scores, eligible, 4, 3, 10)

    assert all(len(chosen) == 3 for chosen in assignment.values())
    loads = Counter(reviewer for chosen in assignment.values() for reviewer in chosen)
    assert max(loads.values()) == 3
    assert sum(loads.values()) == 12


def test_min_cost_flow_reports_infeasible_instances() -> None:
    scores = np.full((4, 3), 0.5)
    eligible = [np.arange(3) for _ in range(4)]

    with pytest.raises(nx.NetworkXUnfeasible):
        p3.min_cost_flow_assignment(scores, eligible, 3, 2, 10)


def test_hungarian_masks_conflicting_reviewers() -> None:
    scores = np.array([[0.9, 0.8, 0.1], [0.7, 0.6, 0.5]])
    # Paper 0 may only be reviewed by reviewer 1.
    eligible = [np.array([1]), np.array([0, 1, 2])]

    assignment = p3.hungarian_assignment(scores, eligible, 3)

    assert assignment[0] == 1
    assert assignment[1] != 1


def test_random_assignment_respects_capacity_and_is_seeded() -> None:
    eligible = [np.arange(3) for _ in range(2)]  # 2 papers x 3 reviewers
    first = p3.random_assignment(eligible, n_reviewers=3, capacity=2, runs=3)
    second = p3.random_assignment(eligible, n_reviewers=3, capacity=2, runs=3)

    assert first == second  # same SEED -> identical baseline
    for assignment in first:
        assert all(len(chosen) == 3 for chosen in assignment.values())
        loads = Counter(reviewer for chosen in assignment.values() for reviewer in chosen)
        assert max(loads.values()) <= 2
