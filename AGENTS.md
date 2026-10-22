# AGENTS.md — Rules for this project

This file is the contract for anyone (human or AI) working on this repository.
Read it fully before changing code. If a rule conflicts with a request, stop and ask.

---

## 1. Project

**Pakistan's Researchers Network** — a research-collaboration knowledge graph built
from real OpenAlex data, stored and analysed in Neo4j, served by a FastAPI backend
and a React frontend.

Semester project, 20 marks. Three problems:

1. **Fragility** — who/what holds the network together, and how fast it breaks when
   key researchers are removed.
2. **Silos & collaboration prediction** — where the isolated groups are, and which
   new collaborations should happen. Validated by a time split: train on papers up
   to 2020, test on real collaborations from 2021 onward.
3. **Reviewer assignment** — assign papers to well-matched reviewers under a
   per-reviewer workload cap and a conflict-of-interest rule; compare with random
   assignment.

## 2. Non-negotiable grading requirements

| Requirement | Rule |
|---|---|
| Real data | OpenAlex only (free, open). **No synthetic or mock data as the main dataset.** Cite source and licence (CC0 1.0). |
| Scale (minimum) | 100+ nodes, 300+ edges, largest connected component (LCC) ≥ 50% of nodes. |
| Scale (target) | 500+ nodes, 1,500+ edges, LCC ≥ 80%, several node and edge attributes. |
| Cleaning | Document duplicates, self-loops and missing values with **before/after** statistics. |
| Data files | CSV edge lists, GraphML, `data/data_dictionary.md`. |
| Techniques | ≥ 4 total, ≥ 2 graph theory, ≥ 2 network science. Aim for ~10. |
| Neo4j | **Mandatory.** Cypher + Graph Data Science (GDS) wherever possible. No Aura Free (no GDS). |
| Python | Only for what GDS lacks: cascade/failure simulation, null models, Hungarian/min-cost flow, plots, API. State clearly which stage runs where. |
| Reproducibility | Every script runs on the submitted dataset. Seeds fixed for all randomness. |
| Deliverables | Report, source code, dataset files, figures/screenshots, all in one folder. |

## 3. Data source and scope

- **Source:** OpenAlex API, <https://api.openalex.org>. Licence: CC0 1.0 Universal.
  Cite: Priem, J., Piwowar, H., & Orr, R. (2022). *OpenAlex: A fully-open index of
  scholarly works, authors, venues, institutions, and concepts.* arXiv:2205.01833.
- **Polite pool:** every request sends `mailto` from `OPENALEX_EMAIL` and a
  descriptive `User-Agent`. The email is **never** hard-coded or committed.
- **Scope (initial, verified against live counts before building):**
  - works with `institutions.country_code:PK` (at least one Pakistani-affiliated
    institution),
  - `primary_topic.field.id:fields/17` (Computer Science),
  - `publication_year:2015-2025`,
  - types: `article`, `proceedings-article`, `review`, `book-chapter`
    (preprints excluded to avoid duplicate versions).
- **Scope changes are allowed only with evidence** (real counts), recorded in
  `data/cleaning_report.md`, and announced at the Stage 1 gate.

## 4. Graph model

Nodes:

- `Author` — `author_id`, `name`, `orcid`, `works_count`, `cited_by_count`,
  `first_year`, `last_year`, `pk_affiliated`
- `Paper` — `paper_id`, `doi`, `title`, `year`, `type`, `cited_by_count`, `is_pk`
- `Institution` — `institution_id`, `name`, `country_code`, `type`
- `Topic` — `topic_id`, `name`, `subfield`, `field`, `domain`

Relationships:

- `(Author)-[:WROTE {position, is_corresponding}]->(Paper)`
- `(Author)-[:AFFILIATED_WITH {years: [...]}]->(Institution)`
- `(Paper)-[:ABOUT]->(Topic)`
- `(Paper)-[:CITES]->(Paper)` (only when the cited paper is also in the dataset)

**Analysis projection:** author-to-author graph. Edge weight = number of shared
papers; edge attributes: `first_year`, `last_year`, `papers` (list of paper ids,
capped in exports). Node attributes: institution, topics, first/last year, degree.

**Analysis network (decided at Gate 1, from real counts):** because the full
co-authorship network's LCC is 79.7% (just below the 80% target), Stages 3–5 use
the *core* network induced by authors with at least two papers (14,574 nodes,
81,793 edges, LCC 92.6%). The full network (42,774 nodes, 170,700 edges, LCC
79.7%) remains loaded in Neo4j and both figures are reported everywhere. This is
a documented scope refinement, not a silent filter.

## 5. Architecture and folder layout

Project root = this folder (the existing scaffold is kept, not nested twice).

```
researchers-network/            <- repository root (this folder)
  AGENTS.md  docker-compose.yml  .env.example  README.md  run_all.ps1
  data/
    raw/            compact JSONL exactly as fetched (needed fields only)
    cleaned/        nodes_*.csv, edges_*.csv, graphml/
    import/         CSVs mounted into the Neo4j container (/import)
    results/        analysis JSON/CSV outputs
    data_dictionary.md
    cleaning_report.md
  crawler/          fetch_openalex.py, clean.py, build_graph.py, cli.py
  analysis/         p1_fragility.py, p2_silos_linkpred.py, p3_reviewers.py, common/
  backend/          FastAPI app (main.py, routers/, services/, tests in ../tests)
  frontend/         React + Vite + Cytoscape.js
  report/           figures/ , screenshots/
  docs/             EXPLAIN.md (viva explanations), PLAN.md
  tests/            pytest suite
```

## 6. Tech stack

- Neo4j 5.26 community in Docker + GDS plugin (`NEO4J_PLUGINS='["graph-data-science"]'`).
- Python 3.11+ backend/analysis: `neo4j` driver, FastAPI, NetworkX, pandas,
  scikit-learn, SciPy, Matplotlib.
- React 18 + Vite + Cytoscape.js.
- Config only through `.env` (`OPENALEX_EMAIL`, `NEO4J_URI`, `NEO4J_USER`,
  `NEO4J_PASSWORD`, `CORS_ORIGINS`). Never commit secrets or a personal email.

## 7. Where each technique runs

| # | Technique | Type | Runs in |
|---|---|---|---|
| 1 | Degree / strength distribution | Network science | Neo4j (Cypher) + Python plot |
| 2 | PageRank | Network science | Neo4j GDS |
| 3 | Betweenness centrality | Network science | Neo4j GDS |
| 4 | Articulation points & bridges | Graph theory | Neo4j GDS |
| 5 | k-core decomposition | Network science | Neo4j GDS |
| 6 | Louvain communities + modularity | Network science | Neo4j GDS |
| 7 | Link prediction (Adamic-Adar, common neighbours, Jaccard) | Network science | Neo4j GDS nodeSimilarity + Python evaluation |
| 8 | Targeted vs random failure cascade (LCC, efficiency) | Network science | Python (GDS has no cascade) |
| 9 | Random-graph null model (configuration model) | Network science | Python |
| 10 | Bipartite matching / min-cost flow (Hungarian) | Graph theory | Python (SciPy/NetworkX) |
| 11 | Connectivity / min-cut / max-flow | Graph theory | Neo4j GDS maxFlow + Python check |
| 12 | Dijkstra / shortest paths (collaboration distance) | Graph theory | Neo4j GDS / Cypher |

At least 2 graph-theory and 2 network-science techniques are therefore guaranteed.

## 8. Build stages and gates

Work in order. **Stop after every stage**, report real numbers, and wait.
Never continue past a failed gate.

1. **Stage 1 — Docker config, crawler, cleaning.** Gate: scale + LCC measured on the
   real cleaned graph (see `docs/PLAN.md`). If minimums fail, stop and propose a
   scope change.
2. **Stage 2 — Neo4j load**, constraints/indexes, verification Cypher, GDS projection.
3. **Stage 3 — Problem 1** (fragility): centrality, bridges/articulation points,
   k-core, failure simulation, figures.
4. **Stage 4 — Problem 2** (silos + link prediction with 2020 split, precision/recall).
5. **Stage 5 — Problem 3** (reviewer assignment + random baseline).
6. **Stage 6 — FastAPI** endpoints and tests.
7. **Stage 7 — Frontend** with four views.
8. **Stage 8 — README, `run_all` script, screenshot checklist.**

`docs/EXPLAIN.md` is updated in plain language **after each stage** (what was built,
why this algorithm, how to explain it in a viva).

## 9. Coding rules

- Small, readable, well-commented code. Prefer the simple solution.
- Comment every non-obvious line; docstrings say *what* and *why*, not just *how*.
- Type hints on public functions. No clever one-liners.
- One script per problem in `analysis/`; shared helpers in `analysis/common/`.
- All randomness uses an explicit seed (`SEED = 42`).
- Idempotent scripts: re-running overwrites outputs, never duplicates data.
- Files are UTF-8, LF line endings, relative paths resolved from the repo root.
- Every analysis script can load its input from the submitted CSVs/GraphML —
  no hidden state from an earlier run.

## 10. Honesty and reporting rules

- **Never fabricate, estimate or "adjust" a number.** Report what the code produced.
- Every reported metric must be reproducible by a named command.
- If something fails, say so in the stage report and in `docs/EXPLAIN.md`.
- Limitations (API coverage, name disambiguation, missing citations) are stated,
  not hidden.
- Before/after cleaning statistics are mandatory: raw rows, removed rows, reason,
  final rows.
- The analysis graph and any filtered subgraph must be clearly distinguished in
  every table and figure caption.

## 11. Deliverables checklist

- [ ] `AGENTS.md`, `README.md`, `docker-compose.yml`, `.env.example`, `run_all.ps1`
- [ ] Crawler + cleaning code, raw/cleaned data, GraphML, data dictionary,
      cleaning report with before/after stats
- [ ] Neo4j load scripts, constraints, indexes, verification queries
- [ ] Three analysis modules + JSON/CSV results + figures
- [ ] FastAPI app + tests
- [ ] React frontend with 4 views + screenshots
- [ ] `docs/EXPLAIN.md` (viva guide)
- [ ] Report (only when explicitly requested, separate step)

## 12. Out of scope for now

- Do **not** write the final report yet. The user will request it separately
  (Times New Roman 12 pt, 1.5 spacing, justified).
- No Neo4j Aura Free (no GDS).
- No synthetic data as the main dataset.
- No secrets, tokens or personal email in the repository.
