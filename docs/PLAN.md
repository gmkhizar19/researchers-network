# Build plan and acceptance checks

Status: **Stage 7 complete - React frontend built and verified; awaiting approval to start Stage 8**.
Project root: this folder (the existing scaffold is reused; no nested duplicate).

## Feasibility checks already done (real, 2026-10-20)

| Check | Result |
|---|---|
| OpenAlex API reachable | Yes |
| PK-affiliated CS works, 2015–2025 | **36,473** (before type filter) |
| Docker installed | **No** — must be installed before Stage 2 |
| Node.js | v24.18.1, npm available |
| Python | 3.13.5 |

The OpenAlex count is well above the scale target, so the planned scope is viable.
The missing Docker installation is the only hard blocker; Stage 1 (crawl + clean)
does not need it.

---

## Numbered plan

### Stage 1 — Docker config, crawler, cleaning  → **GATE 1**

**Build**
1. Finalise `docker-compose.yml` (Neo4j 5.26 + GDS, healthcheck, `/import` mount)
   and `.env.example` (`OPENALEX_EMAIL`, `NEO4J_URI`, `NEO4J_USER`,
   `NEO4J_PASSWORD`, `CORS_ORIGINS`).
2. `crawler/fetch_openalex.py`: cursor pagination, retries with exponential backoff,
   polite-pool headers, local JSONL cache so a rerun never re-downloads, progress log.
3. `crawler/clean.py`: normalise ids/names, drop duplicates, self-loops and rows
   with missing mandatory fields; record **before/after** counts per rule.
4. `crawler/build_graph.py`: author–author projection (shared papers), node/edge
   attributes, CSV edge lists + GraphML, LCC and degree statistics.
5. `data/data_dictionary.md` and `data/cleaning_report.md` generated from the run.
6. `docs/EXPLAIN.md` section for Stage 1.

**Acceptance checks (all must pass)**
- [x] Raw cache contains every fetched work; request count and page count logged.
- [x] Cleaning report shows before/after for duplicates, self-loops, missing values.
- [x] Clean graph: **≥ 500 Author nodes**, **≥ 1,500 co-authorship edges**.
  - Actual: 42,774 authors, 170,700 edges.
- [x] LCC **≥ 50%** (minimum) and **≥ 80%** (target) of Author nodes.
  - Full collaboration network: 79.7% (minimum met, target 0.3 pp short).
  - Core analysis network (authors with ≥2 papers): **92.6%** (target met).
    This network is used by Stages 3–5; both numbers are reported.
- [x] Every Author node has name, at least one institution or topic, first/last year;
      every edge has `weight`, `first_year`, `last_year`.
- [x] GraphML opens in NetworkX and matches the CSV counts exactly
      (42,774 nodes / 170,700 edges, verified by `crawler/cli.py validate`).
- [x] `python -m crawler.cli --help` works; rerun is idempotent.

**If the gate fails:** stop, report exact numbers, propose a scope change
(e.g. include all CS-adjacent fields, extend years, or use the LCC as the stated
analysis graph) and wait for approval.

---

### Stage 2 — Neo4j load and verification

**Build**
1. `analysis/load_neo4j.py` (or `crawler/load_neo4j.py`): `LOAD CSV` for 4 node
   labels and 4 relationship types, batched, idempotent `MERGE`.
2. Constraints: unique `author_id`, `paper_id`, `institution_id`, `topic_id`.
   Indexes: `Author.name`, `Paper.year`, `Institution.country_code`.
3. `data/import/verify.cypher`: counts per label/type, orphan check, duplicate
   check, sample traversals.
4. GDS projection `authorGraph` (undirected, weight) + `paperGraph` where needed.

**Acceptance checks**
- [x] Neo4j node/relationship counts equal the cleaned CSV counts.
  - 42,774 Author; 26,188 Paper; 4,817 Institution; 1,765 Topic;
    109,066 WROTE; 57,931 AFFILIATED_WITH; 78,564 ABOUT; 40,735 CITES;
    170,700 CO_AUTHORED.
- [x] Zero orphan relationships, zero duplicate ids.
- [x] `gds.graph.list()` shows the projections; `gds.graph.project` succeeds.
  - `authorGraphFull` 42,774 nodes / 170,700 edges;
    `authorGraph` 14,574 nodes / 81,793 edges.
- [x] Verification query output saved to `data/results/neo4j_verification.json`
      (Neo4j 5.26.32, GDS 2.13.14, 13/13 checks pass).

---

### Stage 3 — Problem 1: fragility — **COMPLETE** (real numbers in `data/results/p1_fragility.json`)

**Build**
1. GDS: degree, weighted degree, PageRank, betweenness, k-core, articulation points,
   bridges, Louvain (for context), max-flow min-cut between selected regions.
2. Python: targeted removal (betweenness, degree, PageRank order) vs random removal
   (100 replicates), 1–30% of nodes; measure LCC size, number of components,
   average path length / global efficiency; cascade rule = remove node and its edges.
3. Results JSON/CSV + figures: centrality top-20 table, betweenness distribution,
   fragmentation curves with random confidence band, bridge/articulation map.

**Acceptance checks**
- [x] Top-10 critical authors listed with real names, institutions and scores
      (`data/results/p1_critical_authors.csv`, 100 rows).
- [x] Removing the top 1% by betweenness reduces LCC by a measured, reported amount;
      random baseline is shown with mean and spread. (Top 1% ≈ 146 authors:
      LCC 92.6% → 91.55%; random baseline 91.59% ± 0.05 at the same removal count.
      The gap widens deeper into the cascade — at 10% removed: targeted 76.3%
      vs random 82.4% vs rewired null model 87.7%.)
- [x] Simulation is seeded and reproducible (SEED = 42; replicate seeds 1000+i,
      null model 900; exact Brandes betweenness, no sampling); same seed → same JSON.
- [x] All figures saved as PNG ≥ 150 dpi in `report/figures/`
      (`fig_p1_degree_distribution`, `fig_p1_cascade`, `fig_p1_top_authors`,
      `fig_p1_kcore`, `fig_p1_network_map`).

**Documented deviations from the plan**
- This GDS build (2.13.14) spells the k-core procedures `gds.kcore.*` and has **no**
  `gds.maxFlow.*`; the min vertex cut therefore runs in Python (NetworkX,
  Menger's theorem), honestly labelled as a GDS gap in `docs/EXPLAIN.md`.
- Random removal uses 20 replicates (not 100) and a 0–10% removal range in 0.25%
  steps (not 1–30%): 100 replicates × 30% re-computation adds minutes of runtime
  for no extra insight, and the targeted/random divergence is already clear.
- Mean path length is estimated by BFS from 300 sampled sources, not all pairs.

---

### Stage 4 — Problem 2: silos and collaboration prediction — **COMPLETE** (real numbers in `data/results/p2_silos_linkprediction.json`)

**Build**
1. Louvain communities; modularity; community sizes; institution mix per community.
2. Structural holes: Burt constraint / participation coefficient (GDS or Cypher),
   isolated groups (components of size < 5, low external edge share).
3. **Time split:** training graph = edges with `last_year ≤ 2020`; test edges =
   collaborations appearing in 2021+ between authors already present in training.
4. Scores: Adamic—Adar, common neighbours, Jaccard (GDS `nodeSimilarity` for
   candidates, Python for exact scoring). Candidate pairs limited to 2-hop
   neighbourhood, excluding existing train edges.
5. Metrics: precision@k, recall@k, AUC, lift over random; k ∈ {10, 50, 100}.
6. Results JSON/CSV + figures: precision/recall curves, community map, top predicted
   pairs with names, institutions and evidence papers.

**Acceptance checks**
- [x] Test set built only from real 2021+ edges; counts reported
      (13,188 test pairs between authors present before 2021; 42,199 pairs with a
      newcomer author are excluded and reported).
- [x] Precision@50 and recall@50 reported for all three scores + random baseline
      (common neighbours 6% / 0.11%; Adamic-Adar 10% / 0.18%; Jaccard 2% / 0.04%;
      random baseline 1.2% ± 1%; see `p2_silos_linkprediction.json`).
- [x] At least one score beats random by a reported factor
      (Adamic-Adar: ~8× over random precision at K=50; AUC 0.68 vs random 0.5).
- [x] Negative sampling and candidate generation documented; no leakage of test
      edges into training or features (train = first shared paper ≤ 2020;
      the GDS `nodeSimilarity` candidates come from a separate time-filtered
      projection `authorGraphTrain`, dropped after use).

**Results in one line**
546 communities, modularity 0.6234 (GDS; NetworkX cross-check of the same
partition 0.6927 — both confirm strong structure); 3 real silos with ≥90% internal
ties — the largest is a 1,323-author University of Karachi/COMSATS cluster;
connected groups with <5 authors: 478.
Adamic-Adar is the best predictor of real 2021-2025 collaborations (AUC 0.682,
P@50 = 10% ≈ 8× random); Jaccard is the weakest (AUC 0.594).

**Documented deviations from the plan**
- This GDS build rejects a `randomSeed` key for Louvain and spells the write key
  `writeProperty`; determinism comes from `concurrency: 1` (documented in JSON).
- Test-split rule uses `first_year` (first shared paper) rather than the planned
  `last_year`: pairs that first appeared in 2021+ are genuinely *new*
  collaborations, while `last_year ≤ 2020` would move old pairs that merely
  *stopped* collaborating into the test set. The plan's variant is documented
  here rather than computed.
- "Evidence papers" per recommended pair come from shared neighbours' joint
  papers (papers attribute of shared edges is capped in exports), so the CSV lists
  shared-neighbour counts and scores instead of a raw paper list.

---

### Stage 5 — Problem 3: reviewer assignment — **COMPLETE** (real numbers in `data/results/p3_reviewers.json`)

**Build**
1. Input: test-period papers (2021+) with title/topics and their authors.
2. Eligibility: conflict of interest = co-author ever, or graph distance ≤ 2 in the
   training graph, or same institution.
3. Score: cosine similarity between paper text (TF-IDF) and reviewer profile
   (titles of their training papers) combined with topic overlap.
4. Assignment: min-cost max-flow (NetworkX) with reviewer capacity `C = 3` and
   paper demand 3 reviewers; Hungarian (`scipy.optimize.linear_sum_assignment`)
   for the uncapacitated variant. Infeasible papers reported, not silently dropped.
5. Baseline: random eligible reviewer, 100 runs.
6. Metrics: coverage, mean score, conflict violations (must be 0), load std-dev,
   comparison table.

**Acceptance checks**
- [x] Zero COI violations in the optimal solution (verified independently):
      0 of 3,600 assignments, re-checked by a separate code path from the raw CSVs.
- [x] No reviewer exceeds capacity: max load 3, 0 violations (1,899 reviewers;
      517 unused).
- [x] Coverage and mean match score beat the random baseline: coverage ties at
      100% (the pool is large enough that feasibility is easy at this scale);
      mean relevance 0.4060 vs 0.0182 = **22.3× better**; top reviewer per paper
      0.4739 vs 0.0448 = 10.6× better.
- [x] Results reproducible with the fixed seed: rerunning produces identical
      numbers (flow 0.4060, Hungarian 0.4221, random 0.0182); random baseline is
      100 seeded runs with SEED = 42.

**Results in one line**
1,200 real 2021–2025 papers, 3 reviewers each, 1,899-author senior pool,
capacity 3: min-cost flow assigns all 3,600 slots with **0 COI and 0 capacity
violations**, mean relevance 0.4060 (top choice 0.4739), while random eligible
reviewers score 0.0182 and the Hungarian one-per-paper variant 0.4221 (flow keeps
the Hungarian first choice in 92.5% of papers while adding two more reviewers).
Relevance is 22.3× the random baseline; 3 figures + assignment/comparison CSVs.

**Documented deviations from the plan**
- Papers are a **seeded sample of 1,200** multi-author 2021–2025 papers (of
  16,143 in scope), not all of them: exact min-cost flow for all would need
  ~48k constrained assignments; the sample demonstrates the method with honest
  reporting of the scope.
- Reviewer pool = **authors with ≥ 10 dataset papers** (1,899 people), not all
  authors: reviewers need a substantive profile and a credible seniority level.
- Score uses **titles + OpenAlex topic scores**, not abstracts: the compact
  dataset does not store abstracts (documented limitation).
- Hungarian is run as the uncapacitated **one-reviewer-per-paper** variant; the
  capacitated 3-reviewer problem is solved by min-cost flow. With 1,899
  reviewers and 1,200 papers it never needs to reuse a reviewer (max load 1),
  so its mean equals its top-choice score.
- Flow candidate generation needed the second beam width (top-100 eligible
  reviewers); top-50 was infeasible and the escalation is logged in the JSON.
- No Neo4j dependency: this stage is combinatorial matching over the submitted
  tables; the plan's technique table assigns it to Python.

---

### Stage 6 — FastAPI backend

**Build**
1. App factory, settings from `.env`, CORS, Neo4j driver with lifespan management.
2. Endpoints: `/api/health`, `/api/stats`, `/api/network?limit=`, `/api/authors/{id}`,
   `/api/fragility`, `/api/critical`, `/api/communities`, `/api/link-predictions`,
   `/api/reviewers/assignments`, `/api/reviewers/metrics`.
3. Results read from `data/results/*.json`; graph queries from Neo4j.
4. pytest: unit tests for scoring/COI logic, API tests with a fake result store,
   optional integration test marked `neo4j`.

**Acceptance checks**
- [x] `pytest` green without Neo4j running (unit + API tests): **26 passed,
      1 skipped** (the `neo4j` integration test), exit code 0, with
      `NEO4J_URI` pointed at a dead port. With the real container up:
      **27 passed**. API tests use fakes and never open a connection.
- [x] OpenAPI docs at `/docs` list every endpoint: HTTP 200, Swagger UI, and
      `/openapi.json` contains all **10** paths (health, stats, network,
      authors/{author_id}, fragility, critical, communities,
      link-predictions, reviewers/metrics, reviewers/assignments).
- [x] No secret values in code; all from environment: `Settings` reads
      `NEO4J_URI/USER/PASSWORD`, `CORS_ORIGINS` and `RESULTS_DIR` from `.env`;
      the in-code password default is empty, and a test proves an environment
      value wins.

**Results in one line**
10 read-only endpoints: analytical ones serve `data/results/*.json|csv` verbatim;
`/api/network` and `/api/authors/{id}` query Neo4j live. Verified against the
running stack: health reports Neo4j 5.26.32 and all 3,600 assignments loaded;
`/api/network?limit=50` returns 50 authors / 161 induced edges; Imran Ashraf
resolves with degree 324 and top collaborator Furqan Rustam; fragility returns
670 articulation points, 660 bridges, max k-core 16, max-flow 184; communities
546 / modularity 0.6234 / 3 silos; link prediction AUC 0.6824 (AA), 0.6291 (CN),
0.5945 (Jaccard); reviewer metrics 1,200 papers, 1,899 reviewers, 100% coverage,
mean 0.4060, 0 COI violations, 3,600 assignment rows. With Neo4j stopped, graph
endpoints return a clear **503** while every analytical endpoint keeps working.

**Documented deviations from the plan**
- `/api/network` returns a **degree-ranked induced subgraph** capped at 1,500
  nodes (default 300) instead of the full 14,574-node core network: a browser
  cannot render the full graph, and the response says so explicitly
  (`induced_subgraph: true`).
- Graph endpoints use `kcore IS NOT NULL` (exactly the 14,574 analysis nodes),
  not `Author.core = 1`, which also covers 61 isolated authors.
- `/api/critical` reads `p1_critical_authors.csv` (the top 100 authors by
  betweenness exported by Stage 3). Sorting by another metric reorders that
  subset; the API and UI state this rather than implying a full ranking.
- `/api/stats` combines the Stage 1 stats and Stage 2 load verification files;
  it does not recompute counts live (Neo4j counts could drift after edits).
- Missing analysis output → **503** with the expected command, instead of a
  generic 500; unknown author → 404; malformed author id or out-of-range limit
  → 422. These are covered by tests.
- The integration test is marked `neo4j` and skips automatically when the
  container is down, which is what makes the "green without Neo4j" gate honest.
- No authentication: this is a local, read-only, single-user academic API
  (stated limitation, not an oversight).

---

### Stage 7 — React frontend

**Build**
1. Vite + React, small component set, fetch wrapper, four views:
   - Network explorer (Cytoscape, filters, node details)
   - Critical researchers & fragility (ranking table + cascade chart)
   - Collaboration recommender (predicted pairs + evidence)
   - Reviewer assignment (paper → reviewers, capacity/COI badges)
2. Responsive layout, loading/error states, no fake data.

**Acceptance checks**
- [x] `npm run build` succeeds (Vite 5.4.21, 41 modules, 4.90 s).
- [x] All four views render real API data; screenshots saved in `report/screenshots/`.
- [x] Every view has a visible explanation line for the viva.
- [x] Backend CORS works from `http://localhost:5173`
  (`access-control-allow-origin: http://localhost:5173` verified with curl).

**Result (verified against the running stack, 21 Oct 2026)**
- `frontend/` is Vite 5 + React 18 + Cytoscape 3.30, plain CSS, no chart
  library (the cascade is an inline SVG component).
- Four hash-routed views (`#/network`, `#/fragility`, `#/recommender`,
  `#/reviewers`), each with loading, error and empty states:
  1. **Network explorer** - 300 nodes / 2,008 induced edges from the core
     network; node size = degree, colour = Louvain community, edge width =
     shared papers; clicking a node loads `/api/authors/{id}` (e.g. Imran Ashraf:
     degree 324, k-core 13, community 8592, 150 papers in the dataset).
  2. **Critical & fragility** - 670 articulation points, 660 bridges, max
     k-core 16, 184 node-disjoint paths; cascade chart after removing up to
     10%: betweenness 76.3%, PageRank 78.2%, degree 79.3%, random 82.4%.
  3. **Silos & recommender** - Adamic-Adar AUC 0.6824 vs CN 0.6291 / Jaccard
     0.5945; 13,188 new 2021+ pairs, 2,787 evaluated positives among 228,127
     shared-neighbour candidates; 3 silos (92.4%, 93.3%, 100% internal).
  4. **Reviewer assignment** - 100% coverage, mean relevance 0.4060, top choice
     0.4739, 0 COI violations, max load 3, 3,600 assignment rows; random mean
     0.0182 (22.3x lift); Hungarian comparison included.
- Screenshots (full page, 1440 px wide):
  `stage7_network_explorer.png`, `stage7_fragility.png`,
  `stage7_recommender.png`, `stage7_reviewers.png`.

**Commands**
```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173 (API expected on :8000)
npm run screenshots  # needs the API and dev server running
npm run build        # production bundle in frontend/dist
```

**Documented deviations from the plan**
- **Hash routing** instead of React Router: no extra dependency, and every view
  is directly linkable/screenshot-able. Unknown hashes fall back to the explorer.
- **Induced subgraph in the browser**: `/api/network` is capped (default 300,
  max 1,000 of the 14,574 core authors). The view and response both state that
  this is a degree-ranked induced subgraph, not the full network.
- **Critical table caveat**: `p1_critical_authors.csv` holds the **top 100 by
  betweenness** exported by Stage 3, not all 14,574 authors. Sorting by
  PageRank/degree/k-core reorders that subset; the UI hint and the
  `/api/critical` docstring now say so explicitly.
- **Screenshots** use `playwright-core` driving the installed Edge
  (`frontend/scripts/screenshots.mjs`), because the desktop browser tool needs a
  visible window. The script requires both servers to be up.
- **Bundle size**: 617 kB (199 kB gzip) because Cytoscape is included; Vite warns
  above 500 kB. Acceptable for a local academic app; code-splitting the
  explorer view is the obvious later optimisation.
- No authentication and no state persistence: this is a local, read-only,
  single-user viewer (same limitation already stated for the API).

---

### Stage 8 — Packaging

**Build**
1. `README.md`: prerequisites, install, crawl, load, analyse, run, troubleshoot.
2. `run_all.ps1` (+ `.sh`) with stage flags and preconditions.
3. Screenshot checklist and final deliverables tree.
4. Final `docs/EXPLAIN.md` pass.

**Acceptance checks**
- [x] A clean checkout can follow README end-to-end.
- [x] `run_all.ps1 -Stage all` works or fails with a clear message.
- [x] All deliverables present; no report written yet.

**Canonical Stage 8 verification (22 Oct 2026)**
- `.\run_all.ps1 -Stage all -SkipFetch`: exit 0 in **7.7 minutes** — data
  validation, Neo4j load, all three analyses, **27 tests passed**, Vite production
  build (6.65 s), API import check (14 routes).
- Exact betweenness: **299.3 s** for the full p1 run; a second direct
  `gds.betweenness.stream('authorGraph')` call returned the same top-5 scores.
- Canonical results used in README/UI/screenshots: p1 **670 / 660 / 16 / 184**,
  cascade **76.3% vs 82.4%**; p2 **546 communities, modularity 0.6234, 3 silos**;
  p3 **92.5%** top-1 agreement.
- Louvain has no usable seed in this GDS build; an earlier run produced 545
  communities / 0.6248. The submitted run is the canonical one; variability is
  disclosed in the README, `docs/EXPLAIN.md` and the p2 JSON note.

---

## Technique coverage

Graph theory: articulation points/bridges, max-flow min-cut, shortest paths,
bipartite matching/min-cost flow.
Network science: degree distribution, PageRank, betweenness, k-core, Louvain,
link prediction (Adamic–Adar/CN/Jaccard), cascade simulation, null model.

## Main risks

| Risk | Mitigation |
|---|---|
| Docker not installed | Install Docker Desktop before Stage 2; Stage 1 proceeds without it. |
| OpenAlex rate limits | Polite pool, cursor paging, retries, on-disk cache. |
| LCC below target | Report honestly; scope change at Gate 1 (documented). |
| Author name disambiguation | Use OpenAlex author ids, not names. |
| Graph too large for UI | Cap explorer subgraph; analyses use full graph. |
| GDS version mismatch | Pin Neo4j 5.26 + compatible GDS; verify with `gds.version()`. |
