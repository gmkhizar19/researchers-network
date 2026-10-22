# Viva explanation guide

Plain-language explanations of every module, written so that each design choice
can be defended out loud. Updated after every stage.

---

# Stage 1 — Data acquisition, cleaning and graph construction

## 1. What was built

1. A Docker Compose file that starts **Neo4j 5.26** with the **Graph Data Science**
   plugin.
2. A crawler that downloads real **OpenAlex** works for the project scope.
3. A cleaning script that removes duplicates, self-loops, unusable rows and
   citations outside the dataset, and writes a before/after report.
4. A builder that projects the Author–Paper bipartite graph into an
   author-to-author collaboration graph and exports CSV + GraphML.

**Everything in this stage runs in Python.** Neo4j is not used until Stage 2.
This is stated in the code and in this document, as the brief requires.

## 2. Why OpenAlex?

- It is free, open and does not need an institutional subscription.
- It provides **persistent author ids**, institution ids and topic ids. Names
  alone are ambiguous (many Pakistani researchers share names), so ids are the
  difference between a real network and a name-matching mess.
- It covers both journals and conferences, which matters for Computer Science.
- It is licensed **CC0 1.0**, so the data can be redistributed in the submission.

## 3. Scope and why it was chosen

Query (one request per publication year):

```
institutions.country_code:PK
primary_topic.field.id:fields/17        (Computer Science)
publication_year:2015-2025
type:article|proceedings-article|review|book-chapter
```

- **Pakistan + Computer Science** keeps the project focused and explainable. A
  broad "all Pakistani research" graph would mix medicine, physics and social
  science, and reviewer assignment would compare unrelated papers.
- **2015–2025** gives eleven years, enough for a meaningful 2020 train/test split
  and enough time for collaborations to form.
- The API reported **26,627 works** for this scope. That is far above the 500-node
  / 1,500-edge target, so no scope expansion was needed.
- Preprints are excluded so that a preprint and its published version do not
  double-count the same collaboration.

**2026 API change (worth mentioning in the viva):** OpenAlex now requires a free
API key for cursor paging, and anonymous requests share a small daily budget. The
crawler therefore pages **one year at a time** with `page=1,2,...`; each year is
below the 10,000-result page limit. The cache is resumable, so a failed run
continues instead of starting over.

## 4. How the crawler works (simple version)

1. Ask OpenAlex for year *Y*, page 1, 200 results per page.
2. Write the page to `data/raw/page_YYYY_NNNNN.json` **before** updating the
   manifest. A crash can only re-download one page; it can never lose a page.
3. Continue until a page contains fewer than 200 results → that year is finished.
4. Move to the next year.
5. On a rerun, the manifest says which year/page comes next.

Rate limiting: 0.2 s between requests and exponential backoff on HTTP 429/5xx.
Identity: a descriptive `User-Agent`; `OPENALEX_EMAIL` is used only when it is a
real address (the `.env.example` placeholder is rejected by OpenAlex with 401).

## 5. Cleaning rules and real before/after numbers

| Rule | Before | After |
|---|---:|---:|
| Raw works fetched | 26,627 | 26,627 |
| Duplicate work ids | 0 removed | 26,188 kept |
| Works without any usable author id | 439 removed | 26,188 |
| Authorship rows | 119,372 | 109,066 `WROTE` edges |
| Authorships without an author id | 10,052 removed | — |
| Same author twice on one paper (self-loop) | 254 removed | — |
| Citation references | 915,022 | 40,735 `CITES` edges |
| Paper citing itself | 158 removed | — |
| Citation target outside the dataset | 874,129 removed | — |

Missing optional values are left empty and counted, never imputed:

- 1,727 papers without a DOI,
- 21,803 authorships without an ORCID,
- 4,309 authorships without an institution.

**Why 10,052 authorships have no author id:** OpenAlex has not disambiguated
those names. Merging them by name would create false identities, so they are
dropped and reported. This is a limitation, not a hidden fix.

## 6. From bipartite graph to collaboration graph

The knowledge graph is:

```
(Author)-[:WROTE]->(Paper)-[:ABOUT]->(Topic)
(Author)-[:AFFILIATED_WITH]->(Institution)
(Paper)-[:CITES]->(Paper)
```

For network analysis we need authors connected to authors. **Projection:** if two
authors appear on the same paper, add an undirected edge. The edge weight is the
number of shared papers. This is the standard co-authorship projection.

Why cap at 30 authors per paper? Nine papers have huge consortium author lists.
A 200-author paper adds ~20,000 edges, almost all of which are not real working
relationships. Those nine papers are skipped and the avoided edges are reported
(19,998), so nothing is hidden.

## 7. Real numbers (Gate 1)

| Measure | Value | Requirement |
|---|---:|---|
| Authors | **42,774** | 500+ target |
| Papers | 26,188 | — |
| Co-authorship edges | **170,700** | 1,500+ target |
| Institutions | 4,817 | — |
| Topics | 1,765 | — |
| Components (collaborating authors) | 2,148 | — |
| Largest component | 32,879 | — |
| **LCC, full collaboration network** | **79.7%** | ≥50% minimum, ~80% target |
| **LCC, core network (authors with 2+ papers)** | **92.6%** | ≥80% target |
| Core network nodes / edges | 14,574 / 81,793 | — |

**How to explain the two LCC numbers:** the full network includes every author who
ever co-authored one paper. Many of them sit in small, one-paper groups. The core
network keeps authors with at least two papers — people with a recurring
collaboration pattern. It is the network used for the analyses because one-off
authors add noise to centrality, communities and link prediction. Both numbers
are reported; neither is hidden.

## 8. Files produced

```
data/raw/                       raw OpenAlex pages + manifest + fetch.log
data/cleaned/authors.csv        Author nodes (42,774)
data/cleaned/papers.csv         Paper nodes (26,188)
data/cleaned/institutions.csv   Institution nodes (4,817)
data/cleaned/topics.csv         Topic nodes (1,765)
data/cleaned/wrote.csv          109,066 WROTE edges
data/cleaned/affiliated_with.csv 57,931 AFFILIATED_WITH edges
data/cleaned/about.csv          78,564 ABOUT edges
data/cleaned/cites.csv          40,735 CITES edges
data/cleaned/author_nodes.csv   42,774 authors + degree/strength
data/cleaned/author_edges.csv   170,700 co-authorship edges
data/cleaned/graphml/           full and core GraphML
data/cleaned/author_nodes_core.csv / author_edges_core.csv
data/cleaning_report.md         before/after report
data/graph_report.md            projection statistics
data/data_dictionary.md         every column explained
```

## 9. Viva questions and short answers

**Q: Why not scrape Google Scholar?**
A: It is not open, blocks automated access, and has no stable author ids. OpenAlex
is free, CC0, and designed for programmatic use.

**Q: How do you know two authors are the same person?**
A: We use OpenAlex author ids. We do not merge by name. This avoids false merges
but inherits OpenAlex's disambiguation errors, which we state as a limitation.

**Q: Why is 79.7% not 80%?**
A: LCC is a property of the data, not something we can tune. The full network is
79.7%; the core network, which the analyses use, is 92.6%. We report both. The
minimum requirement (50%) is comfortably met.

**Q: What is a self-loop here?**
A: Two kinds: the same author listed twice on one paper (removed 254 times), and a
paper citing itself (removed 158 times).

**Q: Why are most citations missing?**
A: A cited paper is kept only if it is also in our 26k-paper slice. 95.5% of
references point outside the slice. The citation graph is therefore a subgraph,
and we say so wherever it is used.

**Q: Is the data synthetic?**
A: No. Every row comes from the live OpenAlex API; the raw cache and the request
log are included so the download can be audited.

## 10. Commands

```powershell
copy .env.example .env
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

python -m crawler.cli fetch        # resumable download
python -m crawler.cli clean        # before/after cleaning report
python -m crawler.cli build        # graph + GraphML + statistics
python -m crawler.cli status       # cache summary
```

---

# Stage 2 — Loading into Neo4j and Graph Data Science

## 1. What was built

- Neo4j **5.26.32** running in Docker with the **Graph Data Science 2.13.14** plugin.
- Four node labels (`Author`, `Paper`, `Institution`, `Topic`) and five relationship
  types (`WROTE`, `AFFILIATED_WITH`, `ABOUT`, `CITES`, `CO_AUTHORED`).
- Uniqueness constraints on every node id, plus indexes for the properties used in
  lookups.
- Batched `LOAD CSV` loading, idempotent thanks to `MERGE`.
- Two GDS projections: the full author graph and the core author graph.
- A verification report comparing Neo4j counts with the CSV counts.

**What runs where:** all loading, schema, verification and graph projection is
**Cypher/Neo4j**. Python only opens the driver and sends the Cypher; no data is
processed in pandas in this stage.

## 2. Why store this in Neo4j instead of only CSV?

CSV files are good for storage, but every question in this project is a
traversal: "who co-authored with whom", "which papers connect these authors",
"which authors share a topic". Neo4j stores those connections directly, so a
traversal does not need repeated table joins. It also gives us:

- **constraints** that make duplicate ids impossible,
- **Cypher**, a declarative query language for paths,
- **GDS**, an in-memory graph library with PageRank, Louvain, betweenness,
  articulation points, bridges, k-core and max-flow.

## 3. The graph model (and why)

```
(Author)-[:WROTE {position, is_corresponding}]->(Paper)
(Author)-[:AFFILIATED_WITH {years}]->(Institution)
(Paper)-[:ABOUT {score}]->(Topic)
(Paper)-[:CITES]->(Paper)
(Author)-[:CO_AUTHORED {weight, first_year, last_year, papers}]-(Author)
```

- `WROTE` keeps the bipartite Author–Paper structure. It is the source of truth.
- `CO_AUTHORED` is a **derived** projection. Materialising it makes GDS
  projection trivial and avoids recomputing cliques on every analysis.
- Relationship properties are used where they belong: `weight` on a
  collaboration, `score` on a topic assignment, `years` on an affiliation.
- `core = 1` marks authors with at least two papers. It is an **integer**, not a
  Boolean, because GDS 2.13 cannot load Boolean node properties.
  `authorGraph` additionally requires `degree > 0`, so it matches
  `author_nodes_core.csv` exactly (14,574 nodes).

## 4. Loading strategy

1. Copy the cleaned CSVs into `data/import/`, which Docker mounts at `/import`.
   `LOAD CSV` can only read from that folder.
2. Create constraints and indexes **before** loading. This makes `MERGE` fast and
   guarantees that a rerun cannot create duplicates.
3. Load nodes first, then relationships (relationships need both endpoints).
4. Every load query is wrapped in `CALL (row) { ... } IN TRANSACTIONS OF 5000 ROWS`.
   That commits in batches instead of one huge transaction, so memory stays low
   and a failure does not roll back the whole dataset.
5. `MERGE` makes the load idempotent: running it twice gives the same counts.

## 5. Verified numbers (real output)

| Item | CSV | Neo4j |
|---|---:|---:|
| Author | 42,774 | 42,774 |
| Paper | 26,188 | 26,188 |
| Institution | 4,817 | 4,817 |
| Topic | 1,765 | 1,765 |
| WROTE | 109,066 | 109,066 |
| AFFILIATED_WITH | 57,931 | 57,931 |
| ABOUT | 78,564 | 78,564 |
| CITES | 40,735 | 40,735 |
| CO_AUTHORED | 170,700 | 170,700 |

Structural checks: 0 papers without an author, 0 papers without a topic,
0 co-author edges without a weight. 2,244 authors have no institution on record
(they still have topics and publications).

**GDS projections**

| Graph | Nodes | Unique relationships |
|---|---:|---:|
| `authorGraphFull` | 42,774 | 170,700 |
| `authorGraph` (core) | 14,574 | 81,793 |

GDS reports `relationshipCount = 341,400` and `163,586` because an undirected
relationship is stored once per direction. The code stores the corrected
`uniqueRelationships` value as well.

A PageRank smoke test on the core graph returned (top 3):

1. Imran Ashraf — 13.71
2. Tanzila Saba — 12.29
3. Yazeed Yasin Ghadi — 12.10

These are preliminary; the full Problem 1 analysis comes in Stage 3.

## 6. Useful Cypher (viva demo)

```cypher
// Who are the most connected authors?
MATCH (a:Author)
RETURN a.name, a.primary_institution, a.degree
ORDER BY a.degree DESC LIMIT 10;

// Which institutions have the most authors in the dataset?
MATCH (a:Author) WHERE a.primary_institution IS NOT NULL
RETURN a.primary_institution, count(*) AS authors
ORDER BY authors DESC LIMIT 10;

// A small subgraph for the Neo4j Browser screenshot
MATCH (a:Author)-[r:CO_AUTHORED]-(b:Author)
WHERE a.degree > 150
RETURN a, r, b LIMIT 100;
```

The full set is in `analysis/cypher/verify.cypher`.

## 7. Viva questions and short answers

**Q: Why both `WROTE` and `CO_AUTHORED`?**
A: `WROTE` is the real data: who wrote which paper. `CO_AUTHORED` is a projection
needed for author-level algorithms. Keeping both lets us audit the projection and
avoids repeating it in every query.

**Q: Why constraints before loading?**
A: They enforce one row per OpenAlex id and let Neo4j build faster lookup
structures. Without them, a rerun could silently duplicate nodes.

**Q: What is GDS?**
A: An in-memory graph catalogue. We project Neo4j data into a compressed
in-memory structure, run algorithms (PageRank, Louvain, …) there, and optionally
write scores back. It is much faster than Python for large graphs.

**Q: Why two projections?**
A: The full graph answers dataset-level questions. The core graph removes one-off
authors and is the network used by the three problems. Both are built from the
same Neo4j data, so they cannot drift apart.

**Q: Why does GDS report twice as many relationships?**
A: The projection is undirected; GDS stores an arc in each direction. The number
of unique edges is half the reported count. We record both values.

**Q: Where is Python used here?**
A: Only to send Cypher and save the verification JSON. No graph algorithm in this
stage runs in Python.

---

## 8. Commands

```powershell
docker compose up -d
python -m analysis.load_neo4j --reset     # full load
python -m analysis.load_neo4j --gds-only  # rebuild projections only
python -m analysis.p1_fragility           # Stage 3 (needs the authorGraph projection)
python -m analysis.p2_silos_linkpred      # Stage 4 (needs authorGraph too)
```

Neo4j Browser: <http://localhost:7474> (user `neo4j`, password from `.env`).

---

# Stage 3 - Problem 1: fragility (real numbers)

Command: `python -m analysis.p1_fragility` (~2.5 min, Neo4j must be running).
All numbers below come from `data/results/p1_fragility.json`; nothing is invented.

## What runs where (the honest boundary)

| Technique | Type | Engine |
|---|---|---|
| Degree / strength distribution | Network science | Python (plots) — degree stored in Neo4j |
| PageRank (20 iter, d=0.85) | Network science | **Neo4j GDS**, written back as `Author.pagerank` |
| Betweenness (exact Brandes) | Network science | **Neo4j GDS**, written back as `Author.betweenness` |
| k-core decomposition | Network science | **Neo4j GDS** `gds.kcore.*`, written back as `Author.kcore` |
| Articulation points | Graph theory | **Neo4j GDS**, flag written back as `Author.articulation`; cross-checked with NetworkX (parallel computation, same result 670) |
| Bridges | Graph theory | **Neo4j GDS** `gds.bridges.stream` |
| Min vertex cut / max node-disjoint paths | Graph theory | **Python (NetworkX `minimum_node_cut`)** — this GDS build has no `maxFlow` procedure |
| Targeted vs random removal cascade | Network science | **Python** (GDS has no failure simulation) |
| Configuration-model null model | Network science | **Python** (degree-preserving double edge swap) |
| Mean path length (sampled BFS) | Network science | **Python** |

GDS gaps found by inspecting `SHOW PROCEDURES` (helper: `python -m analysis.discover_gds`):
`kCore` is spelled `kcore` and its output column is `coreValue`; there is no `maxFlow`.
Both facts are recorded here instead of being silently worked around.

## The numbers

Graph analysed = core analysis network (Stage 1/2): 14,574 authors, 81,793 edges,
511 components, LCC 13,493 (92.58%). The cascade starts at 92.58%, not 100%,
because 235 authors outside the LCC are removed too.

- **Betweenness top-15** (exact Brandes): Imran Ashraf (2,163,790), Yazeed Yasin
  Ghadi (2,119,487), Ali Kashif Bashir (2,049,770), Tanzila Saba (1,662,326),
  Muhammad Asif Zahoor Raja (1,494,731), Muhammad Adnan Khan, Amjad Ur Rehman,
  Joel J. P. C. Rodrigues, Muhammad Attique Khan, Usman Tariq, Sajjad Ahmad,
  Ahmad Almogren, Muhammad Ali Imran, Jawad Elsayed Ahmad, Muhammad Khurram Khan
  (full ranked table: `data/results/p1_critical_authors.csv`, 100 rows with
  betweenness, PageRank, degree, strength, k-core, articulation flag, institution).
- **PageRank top-5**: Imran Ashraf (13.71), Tanzila Saba (12.28), Yazeed Yasin Ghadi
  (12.10), Muhammad Asif Zahoor Raja (11.22), Amjad Ur Rehman (10.92).
- **Articulation points**: 670 (4.6% of authors); GDS and NetworkX agree exactly.
- **Bridges**: 660 unique co-authorship edges whose removal disconnects a component.
- **k-core**: max shell 16 (34 authors); the distribution is broad — most authors sit
  in shells 3–8, only ~3.6% reach shells 13–16.
- **Clustering**: real 0.5423 vs configuration-model null 0.0058 — the network is
  ~95× more clustered than its degree sequence alone, i.e. co-authorship cliques
  (research groups) are real structure, not an artefact of degrees.
- **Min vertex cut**: 184 node-disjoint paths separate Imran Ashraf (Yeungnam
  University) from Tanzila Saba (Prince Sultan University); removing 184 specific
  co-authors would sever every co-authorship route between them (Menger's theorem).
  The pair is chosen deterministically from exact degrees, not from betweenness.
- **Failure cascade** (0.25% steps to 10%, chunk = 36 authors/step):
  - Removing the top 1% (144 authors) by betweenness: LCC 92.58% → 91.55%;
    random removal at the same count: 91.59% ± 0.05.
  - At 10% removed: targeted-betweenness LCC 76.3%, random mean 82.4%,
    rewired null model under random removal 87.7%.
  - Component count rises from 511 to 907 under targeted removal at 10%
    (random: 583) — targeted removal shatters the network into more pieces.
  - Mean path length inside the surviving LCC (BFS from 300 sampled sources):
    4.65 → 4.691 (top 20 removed) → 4.796 (top 50) → 4.915 (top 100).

**Interpretation (viva)**: the network is *densely clustered*, so small removals
barely dent the giant component — every research group has redundant internal ties
(660 bridges / 4.6% articulation points is a low share). But the order of removal
matters steadily: betweenness-targeted removal always falls below random, sheds the
LCC ~5 pp faster at 10%, and multiplies component count. The null model shows the
other side of the coin: randomly rewired degrees *without* cliques keep the LCC at
88% because hub-and-spoke redundancy survives rewiring — cohesion here is local
(cliques), not global-hub-driven, which again confirms the clustering result.

## Figures (report/figures/)

1. `fig_p1_degree_distribution.png` — log-log degree distribution + rank curve.
2. `fig_p1_cascade.png` — LCC fraction vs removed fraction: targeted (betweenness,
   degree, PageRank), random mean ± std (20 replicates), null-model random curve.
3. `fig_p1_top_authors.png` — top-15 by betweenness.
4. `fig_p1_kcore.png` — shell-size histogram (max 16).
5. `fig_p1_network_map.png` — co-authorship ties among the top-120 betweenness
   authors; red = articulation point, orange = bridge edge.

## Viva questions and short answers

**Q: Why is betweenness exact now?**
A: Stage 3 sampled 2,000 sources, but GDS ignored the sampling seed when its
internal concurrency was greater than one, so rankings moved between reruns.
Exact Brandes takes only about 35 s on this 14,574-node graph (two GDS passes,
about 70 s total in the script), so Stage 8 removed sampling entirely. Every
score in the JSON and the ranking is now deterministic.

**Q: Why does removing 50 top authors change so little?**
A: Because the network is clustered — cliques give redundant paths, so cuts are
local. The interesting dynamics appear at scale (10%), where the targeted curve
visibly separates (76.3% vs 82.4% random). Reporting both scales is the honest story.

**Q: Why is the min-cut a vertex cut, not an edge cut?**
A: We ask "which *researchers* hold the network together", so the cut object is a
person. Menger's theorem equates max node-disjoint paths with the min vertex cut.

**Q: What runs in Neo4j and what in Python?**
A: See the table above — GDS does every metric it offers; Python only does what
GDS lacks (cascade simulation, null model, min vertex cut, sampled distances, plots).


---

# Stage 4 - Problem 2: silos and collaboration prediction (real numbers)

Command: `python -m analysis.p2_silos_linkpred` (~25 s, Neo4j must be running).
All numbers come from `data/results/p2_silos_linkprediction.json` and
`data/results/p2_top_recommendations.csv`.

## What runs where

| Technique | Type | Engine |
|---|---|---|
| Louvain communities + modularity | Network science | **Neo4j GDS** (`gds.louvain.*`, written back as `Author.community`), modularity cross-checked in Python |
| Participation coefficient (structural holes) | Network science | Python |
| Link prediction: common neighbours, Adamic-Adar, Jaccard | Network science | Python (exact sparse scores over the 2-hop candidate universe) |
| GDS nodeSimilarity candidates | Network science | **Neo4j GDS** on a time-filtered projection `authorGraphTrain` (dropped after use) |
| Validation vs real 2021-2025 collaborations | Graph science practice | Python (precision@K, recall@K, ROC-AUC) |

## The time split (no leakage)

- Train: every pair whose **first shared paper is ≤ 2020** — 26,406 edges among
  7,219 authors.
- Test: pairs whose **first shared paper is ≥ 2021** between authors that already
  exist in the train graph — **13,188 pairs**. A further 42,199 new pairs involve a
  newcomer author (impossible to predict from past data) — counted, excluded.
- Candidates: non-edge pairs sharing ≥ 1 neighbour in the train graph — 228,127.
  Of those, 2,787 became real collaborations in 2021-2025 (base rate 1.22%).

## Silos (real numbers)

- 546 Louvain communities; 235 of them are single-author groups (authors with two
  papers but no co-author). 478 connected components have < 5 authors.
- Modularity: **0.6234** from `gds.louvain.write`; an independent NetworkX
  re-computation of the same partition gives **0.6927**. The two numbers are
  reported as produced — GDS and NetworkX differ in small definitional details
  (intermediate-level modularity vs fully aggregated partition), and both are far
  above 0.4, confirming strong community structure.
- Reproducibility (Stage 8): this GDS build has no `randomSeed` key for Louvain.
  Two full runs on the same graph gave 545 and 546 communities with modularity
  0.6248 and 0.6234 (NetworkX 0.6927-0.6943); labels and small community
  boundaries move, but "strong modularity, 3 silos" is stable. The 546/0.6234
  run is the canonical output used by the UI and screenshots.
- Note (documented, not hidden): the Neo4j `Author.core` flag covers 14,635
  authors while the exported core GraphML contains 14,574 — a 61-author
  application difference of Stage 2's core rule. The 61 extra nodes are isolated
  in the train projection and generate no candidates; the GDS train projection's
  relationships (26,406) match the GraphML train edges exactly.
- **3 genuine silos** (≥ 20 authors and ≥ 90% of their ties stay inside):
  1. 1,323 authors, 92.4% internal — a large University of Karachi / COMSATS
     University Islamabad / Government College Faisalabad cluster.
  2. 62 authors, 93.3% internal — Malakand / PIEAS / HUST group.
  3. 20 authors, 100% internal — Lahore Leads / Sukkur IBA group.
- The mid-size communities (500-900 authors) keep only 40-55% of their ties
  internal — the network's big middle is *not* siloed.
- Mean participation coefficient 0.2274: the average author sends only ~23% of
  their ties outside their own community.

## Can we predict next collaborations? (validated on real 2021-2025 data)

| Score | AUC | P@10 | P@50 | P@100 | P@500 | R@50 | R@500 |
|---|---|---|---|---|---|---|---|
| Common neighbours | 0.629 | 10% | 6% | 10% | 6% | 0.11% | 1.08% |
| **Adamic-Adar** | **0.682** | **10%** | **10%** | 9% | 7.4% | 0.18% | 1.33% |
| Jaccard | 0.594 | 10% | 2% | 4% | 4.6% | 0.04% | 0.83% |
| Random baseline | 0.5 by construction | — | — | — | — | — | — |

Random draws give precision 1.3% ± 1% (= base rate 1.22%). **Adamic-Adar at
P@50 = 10% is ~8× the random rate**; common neighbours ties or beats it deeper
into the list. Jaccard is the weak link: normalising by degree destroys the
"two big pools of shared neighbours" signal.

- GDS nodeSimilarity (topK=10, on the train-only projection): 15,884 candidate
  pairs after cleanup; finds 359 real new pairs; P@50 = 6% (3.8× better than
  random on its own stream; its candidate stream is smaller, so numbers are not
  directly comparable to the full universe).
- Top recommended pairs (Adamic-Adar): Mohsen Guizani + Abdullah Gani (19 shared
  neighbours), Muhammad Khurram Khan + Joel J. P. C. Rodrigues (19),
  Kim-Kwang Raymond Choo + Muhammad Khurram Khan (16), Nadeem Javaid +
  Adnan Akhunzada (16) — all "obvious in hindsight" pairs of heavily-published
  Pakistani-network authors who share many co-workers but had not co-authored by
  2020. Full table: `p2_top_recommendations.csv` (200 pairs).

## Interpretation (viva)

The network has clear communities (modularity 0.62) but they are not walls:
most large communities trade 45-55% of their ties with outsiders. The real silos
are few - the giant University of Karachi / COMSATS cluster (92.4% internal) plus small
fully-closed groups. Prediction works because scientific collaboration is
homophilous: shared co-authors are the strongest signal (Adamic-Adar ~8× random).
Jaccard underperforms because it penalises precisely the pairs with many
co-workers — the most likely future collaborators. That contrast *is* the
lesson: penalising high-degree shared neighbours (Adamic-Adar, common
neighbours) beats penalising them (Jaccard) in this dataset.

## Figures (report/figures/)

1. `fig_p2_community_sizes.png` — top-20 community sizes.
2. `fig_p2_silo_share.png` — internal tie share of the 15 biggest communities;
   orange = silo.
3. `fig_p2_link_prediction.png` — precision@K for the three scores, GDS
   nodeSimilarity, and the random baseline.

## Viva questions and short answers

**Q: Where could leakage sneak in?**
A: Candidates are built from the train graph only (2020 edges); test pairs are
removed from the candidate set by construction (they were non-edges in train).
The GDS candidate stream also runs on a separate train-only projection, which is
dropped after use — nothing learned from 2021+ edges touches the features.

**Q: Why is Jaccard bad here?**
A: It divides the shared-neighbour count by the union of both neighbourhoods,
so it down-weights pairs with many accessible co-workers — exactly the pairs
that form next in this field.

**Q: Why not Burt's constraint for structural holes?**
A: A full constraint computation is O(n·degree²) with per-node view sets; we
report the participation coefficient, which captures the same
"bridge between groups" idea in one number and is cheap and explainable.

**Q: Is 10% precision good?**
A: Judged against the base rate (1.2%) it is 8× better, and against random
top-50 picks it means 5 of every 50 recommended pairs materialised in reality
within 2021-2025 — a strong, honest, verifiable lift.

---

# Stage 5 — Problem 3: reviewer assignment (real numbers)

Command: `python -m analysis.p3_reviewers` (~30-40 s, no Neo4j needed).
All numbers below come from `data/results/p3_reviewers.json`,
`p3_reviewer_assignments.csv` and `p3_method_comparison.csv`.

## What runs where

| Technique | Type | Engine |
|---|---|---|
| Topic cosine + TF-IDF title cosine scoring | Information retrieval | Python (SciPy sparse, scikit-learn) |
| Conflict-of-interest rules (co-author ever, distance ≤ 2, same institution) | Graph theory | Python |
| Min-cost flow with capacity (the assignment) | Graph theory | Python (NetworkX) |
| Hungarian assignment (uncapacitated variant) | Graph theory | Python (SciPy) |
| Random-eligible baseline, 100 runs | Baseline | Python |

This stage is deliberately Python-only: the plan's technique table assigns
bipartite matching / min-cost flow to Python (GDS has no matching procedure),
and the data needed are the submitted tables, not graph traversals. Neo4j is
still used for the other stages and for the frontend.

## Scope (fixed before looking at results)

- **Papers:** 1,200 real multi-author papers from 2021–2025, drawn with
  `SEED = 42` from the 16,143 in scope (the full set would need ~48,000
  constrained assignments; exact flow on a documented sample is the honest
  alternative).
- **Reviewers:** 1,899 authors with **≥ 10 papers** in the dataset.
- **Demand:** exactly **3 reviewers per paper**; **capacity 3 papers per
  reviewer**.
- **COI:** the reviewer must not be an author of the paper, must never have
  co-authored any of its authors (whole 2015–2025 dataset), must not be at
  co-authorship distance ≤ 2 in the **pre-2021** graph, and must not share a
  primary institution with any author.
- **Score:** `0.5 × topic cosine + 0.5 × title TF-IDF cosine`.
  Reviewer topic profiles and title profiles come from their papers **up to
  2020 only**; the paper's own topic vector comes from its OpenAlex topics.
  No abstracts are stored in the compact dataset — a documented limitation.

## The numbers

| | Min-cost flow (capacity 3) | Hungarian (1 per paper, no cap) | Random (100 runs) |
|---|---|---|---|
| Papers fully assigned | 1,200 / 1,200 (100%) | 1,200 / 1,200 (100%) | 1,200 / 1,200 (100%) |
| Mean relevance, all assignments | **0.4060** | 0.4221 | **0.0182 ± 0.0010** |
| Best reviewer per paper | **0.4739** | 0.4221 | 0.0448 ± 0.0023 |
| Max reviewer load | **3** (cap respected) | 1 | 3 |
| COI violations (independent check) | **0 / 3,600** | 0 / 1,200 | 0 |
| Capacity violations | **0** | 0 | 0 |

- Size of the instance: 1,200 papers × 3 = 3,600 assignments; 1,899 reviewers,
  517 of them unused by the optimal solution; per-reviewer load mean 1.896,
  std-dev 1.315.
- Eligibility: on average **1,764.1 of 1,899 reviewers** are conflict-free for
  a paper (mean 279.8 authors blocked per paper, max 2,189). No paper had fewer
  than 3 eligible reviewers, so nothing was dropped.
- The flow needed a **top-100 candidate beam** (top-50 was infeasible for the
  flow network; the escalation is logged in the JSON).
- **Lift over random: 22.3×** on mean relevance, 10.6× on the top reviewer per
  paper.

### Why the Hungarian comparison looks "better" on one line — and why it is not

Hungarian assigns **one** reviewer per paper, so its mean (0.4221) is an
average of each paper's single best pick. The flow must supply **three**
reviewers per paper, so its mean (0.4060) also averages the 2nd and 3rd
choices — naturally lower. The fair comparison is the **best reviewer per
paper**: the flow achieves **0.4739**, higher than Hungarian's 0.4221, because
capacity 3 lets the same excellent reviewer serve up to three papers, while
Hungarian must spread 1,200 papers over 1,200 distinct reviewers. The flow
keeps the Hungarian first choice in **92.5%** of papers and adds two more
reviewers per paper.

### Honest notes

- Coverage cannot discriminate here: with ~1,764 eligible reviewers per paper
  and capacity 3, both the flow and the random baseline assign all papers.
  The discriminating metric is relevance, where the gap is 22×.
- The reviewer "seniority" rule (≥ 10 dataset papers) is a proxy for real
  reviewing experience, not a verified review history.
- Absolute scores (~0.4) are modest because reviewer profiles are averages over
  many papers; the relative lift over random is the meaningful number.

## Interpretation (viva)

The assignment problem is a constrained optimisation: every paper needs three
well-matched reviewers, nobody may review a conflict, and no reviewer may take
more than three papers. Min-cost flow encodes all three rules in one graph and
solves them exactly; the random baseline shows what happens when the matching
signal is ignored (relevance collapses from 0.406 to 0.018). The Hungarian
variant demonstrates the cost of removing capacity: one reviewer per paper and
a lower top-choice score, even though it looks fine on a per-assignment average.

## Figures (report/figures/)

1. `fig_p3_method_comparison.png` — mean relevance of all assignments and of the
   best reviewer per paper, for flow / Hungarian / random.
2. `fig_p3_score_distribution.png` — density of assignment scores: the flow is
   spread over 0.1–0.8, random sits at ~0.
3. `fig_p3_reviewer_loads.png` — share of reviewers at each load level: the
   flow fills the cap (55% at load 3) while random spreads the work.

## Viva questions and short answers

**Q: Why min-cost flow rather than Hungarian?**
A: Hungarian solves one-to-one assignment. Here each paper needs three distinct
reviewers and each reviewer can take up to three papers; flow models both
constraints directly. Hungarian would need reviewer "slots" duplicated and is
better used as the uncapacitated comparison.

**Q: How do you know there are no conflicts?**
A: The solution is re-checked by a separate function that rebuilds the
co-authorship structures from the raw CSVs and walks each assigned pair
explicitly (author list, co-author-ever set, depth-2 walk, institution). It
reports 0 violations out of 3,600 assignments.

**Q: Why is the random baseline so bad?**
A: Random eligible reviewers are, by construction, only weakly related to the
paper; the average cosine is 0.018. The flow raises it to 0.406 — a 22× lift.

**Q: What would you do with more compute?**
A: Run the flow on all 16,143 in-scope papers, add reviewer keywords from
abstracts (not stored here), and calibrate capacity from real review loads
instead of a fixed 3.

# Stage 6 - FastAPI backend (real numbers)

## What was built

A read-only web API in `backend/` that exposes the results of Stages 1-5 and
adds two live graph views. It is the layer the React frontend (Stage 7) will
call. The package is deliberately small and split by responsibility:

| File | Job |
|---|---|
| `backend/config.py` | `Settings` from `.env` / environment (no secrets in code) |
| `backend/store.py` | Loads and caches `data/results/*.json` and the two result CSVs |
| `backend/services/graph.py` | Four parameterised Cypher queries + `GraphUnavailable` |
| `backend/deps.py` | FastAPI dependencies returning the store and the graph gateway |
| `backend/routers/*.py` | Nine small routers, one per problem area |
| `backend/main.py` | App factory, lifespan, CORS, exception handlers, router wiring |
| `tests/` | 9 logic tests, 17 API tests, 1 optional Neo4j integration test |

## Where the numbers come from (the honest boundary)

This is the most important design decision in the stage:

* **Analytical endpoints never calculate anything.** `/api/stats`,
  `/api/fragility`, `/api/critical`, `/api/communities`,
  `/api/link-predictions`, `/api/reviewers/metrics` and
  `/api/reviewers/assignments` read the files written by the analysis scripts.
  A number in the API is therefore exactly the number in the report, and it can
  be reproduced with the documented command. The API cannot silently drift from
  the analysis.
* **Only two endpoints talk to Neo4j:** `/api/network` (explorer subgraph) and
  `/api/authors/{id}` (one profile). These are lookups, not analyses.

The result store loads each file once on first use and caches it, so repeated
requests do not re-read JSON from disk.

## The endpoints (verified against the running stack)

All paths are under `/api`; the interactive docs are at `/docs`.

| Endpoint | Returns (real output) |
|---|---|
| `GET /health` | API + file + Neo4j status: Neo4j 5.26.32 available, all expected result files present, 3,600 assignments loaded |
| `GET /stats` | 42,774 authors, 26,188 papers, 170,700 co-author edges, core graph 14,574 nodes, LCC 79.7% of collaborating authors, Neo4j load check passed |
| `GET /network?limit=` | degree-ranked induced subgraph; `limit=50` gave 50 nodes and 161 edges, marked `induced_subgraph: true` |
| `GET /authors/{id}` | Imran Ashraf (`A5032425002`): degree 324, 324 co-authors, top collaborator Furqan Rustam, recent papers |
| `GET /fragility` | 670 articulation points, 660 bridges, max k-core 16, min cut / max flow 184, cascade curves, null model |
| `GET /critical?limit=&sort=` | ranked authors, default by betweenness: Imran Ashraf (2,163,790), Yazeed Yasin Ghadi (2,119,487), Ali Kashif Bashir (2,049,770) |
| `GET /communities` | 546 Louvain communities, modularity 0.6234, 3 silos, top-20 communities |
| `GET /link-predictions` | AUC: Adamic-Adar 0.6824, common neighbours 0.6291, Jaccard 0.5945, plus top-20 recommendations |
| `GET /reviewers/metrics` | 1,200 papers, 1,899 reviewers, 100% coverage, mean relevance 0.4060, 0 COI violations, random baseline 0.0182 |
| `GET /reviewers/assignments` | filterable, paginated rows of the 3,600 assignments (`total`, `papers`, `limit`, `offset`, `returned`, `items`) |

## Why an app factory and dependency injection?

`create_app(settings, store, graph)` builds the application from three objects.
In production it is called with no arguments, so it reads `.env` and creates the
real Neo4j driver. The tests call it with a `FakeStore` and `FakeGraph`, which is
why the API suite passes with **no Neo4j and no real data files**. Without this,
"tests must not hit the database" would be a promise instead of a guarantee.

## What happens when Neo4j is down?

* `/api/network` and `/api/authors/{id}` return **503** with an actionable
  message ("start it with `docker compose up -d`"), not a 500 stack trace.
* `/api/health` still returns **200**, with `neo4j.available = false`.
* Every analytical endpoint keeps working, because it reads result files.

This was tested explicitly: with `NEO4J_URI` pointed at a dead port, `pytest`
reported **26 passed, 1 skipped, exit code 0**; with the container running,
**27 passed**.

## How it was verified

1. **Full suite with Neo4j up:** `27 passed` (including the integration test,
   which calls `/api/network` and `/api/authors/{id}` on the real graph).
2. **Suite with Neo4j unreachable:** `26 passed, 1 skipped, exit 0` - the skip
   reason names the refused connection.
3. **Real server, real data:** `uvicorn backend.main:app` on port 8000, every
   endpoint called; values in the table above are those responses.
4. **OpenAPI:** `/docs` HTTP 200 with Swagger UI; `/openapi.json` lists exactly
   the 10 required paths.
5. **No secrets:** the password default in `config.py` is an empty string; a
   test sets `NEO4J_PASSWORD` in the environment and asserts it wins.

## Viva questions and short answers

**Q: Why not compute the analysis inside the API?**
A: Because then the report and the API could disagree. The analysis scripts are
the single source of truth; the API serves their files. It also keeps requests
fast and makes the API trivially testable.

**Q: What is the app factory for?**
A: It separates *building* the app from *running* it. Production and tests use
the same code path, but tests inject a fake result store and a fake Neo4j
gateway, so they are fast and deterministic and never touch the database.

**Q: How does the API connect to Neo4j?**
A: One async driver is created in FastAPI's lifespan startup hook and closed on
shutdown. It connects lazily, so the API still starts when the database is down;
health reports the problem instead of crashing on boot.

**Q: Why do graph endpoints return only part of the network?**
A: The core network has 14,574 nodes; a browser cannot render that usefully.
`/api/network` takes the top-N by degree and returns only edges *between* those
nodes - an induced subgraph. The response states this explicitly, so nobody can
mistake it for the full graph.

**Q: How is the API tested without a database?**
A: 17 API tests use `FakeStore`/`FakeGraph`; 9 unit tests exercise the Problem 3
COI, scoring and matching logic on tiny hand-made graphs. The one integration
test is marked `neo4j` and skips when the container is down.

**Q: Where is the secret?**
A: Only in `.env`, which is not committed. `.env.example` documents the variable
names with placeholder values; `backend/config.py` declares an empty default and
reads the real value from the environment.

## Commands

```powershell
# Run the API (interactive docs at http://127.0.0.1:8000/docs)
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload

# All tests (integration test skips if Neo4j is down)
.\.venv\Scripts\python.exe -m pytest

# Prove the suite is independent of Neo4j
$env:NEO4J_URI = "bolt://localhost:9999"
.\.venv\Scripts\python.exe -m pytest
Remove-Item Env:NEO4J_URI

# Only the live-graph integration test
.\.venv\Scripts\python.exe -m pytest -m neo4j
```

# Stage 7 - React frontend (real numbers)

The frontend is the presentation layer only. It computes nothing: every number
on screen comes from the FastAPI responses built in Stage 6, which in turn come
from the Stage 3-5 result files or from Cypher on the real Neo4j graph.

## What was built

- `frontend/` - Vite 5.4.21 + React 18.3.1 + Cytoscape 3.30.4, plain CSS.
- No chart library: the cascade chart is a small inline-SVG component
  (`src/components/LineChart.jsx`), which keeps the dependency count low.
- One fetch wrapper (`src/api.js`) and one hook (`src/useApi.js`) provide
  loading, error and empty states for every view.
- Four views, addressed by URL hash so each one is directly linkable:
  `#/network`, `#/fragility`, `#/recommender`, `#/reviewers`.
- The API base is configurable with `VITE_API_BASE` (default
  `http://127.0.0.1:8000`). The frontend calls the real CORS-enabled API, not a
  mock.

## The four views (and what each proves)

### 1. Network explorer (`#/network`)

**What it shows.** The top 300 authors by degree and every co-authorship edge
between them: **300 nodes and 2,008 induced edges** from the 14,574-node core
network. Clicking a node loads its profile from Neo4j. The default selection is
the largest hub, Imran Ashraf: degree 324, strength 843, k-core 13, community
8592, 150 papers in the dataset, 324 co-authors in the panel.

**Encodings.** Node size = degree, node colour = Louvain community, edge width =
number of shared papers. Labels are drawn only for authors with degree >= 40, so
300 labels do not turn the canvas into noise.

**Why it is an induced subgraph.** A browser cannot usefully draw 14,574 nodes
and 81,793 edges. The API takes the top N by degree and keeps only edges whose
two endpoints are both in that set. The response and the on-screen note both say
`induced_subgraph: true`, so the view is never mistaken for the full network.

**Viva line.** "This is a window into the network, not the network itself: the
biggest 300 collaborators, coloured by the community GDS found."

### 2. Critical researchers & fragility (`#/fragility`)

**What it shows.** Real Problem 1 numbers: **670 articulation points**, **660
bridges**, maximum **k-core 16**, and **184 node-disjoint paths** between Imran
Ashraf and Tanzila Saba (max-flow = min-cut, Menger's theorem).

**The cascade chart.** Remove the top x% of authors (by betweenness, PageRank or
degree) and measure the largest connected component, compared with 20 random
removals. At 10% removed (1,440 authors): betweenness **76.3%**, PageRank
**78.2%**, degree **79.3%**, random **82.4%**. Targeted removal is consistently
worse than random, but the dense core prevents a collapse - which is the honest
finding, not a dramatic one.

**The table.** The top 25 of the **top 100 by betweenness** exported by Stage 3,
with institution, betweenness, PageRank, degree, k-core and a cut-vertex badge.
Changing the sort selector reorders those 100; it does **not** rank all 14,574.
The UI hint and the API docstring state this explicitly.

**Viva line.** "Central authors matter - 670 are single points of failure - but
this network is not a house of cards: even removing 10% of the most central
authors leaves 76.3% of the core connected."

### 3. Silos & collaboration recommender (`#/recommender`)

**What it shows.** Problem 2, with the validation visible:

- Adamic-Adar **AUC 0.6824**, common neighbours 0.6291, Jaccard 0.5945.
- Training graph: 7,219 authors / 26,406 pairs (first shared paper <= 2020).
- **13,188** new 2021+ collaborations between training authors; **2,787** of
  them fall inside the **228,127** shared-neighbour candidate universe and are
  the positives used for AUC. The base rate is **1.22%**.
- 546 Louvain communities, modularity 0.6234 (GDS) / 0.6927 (NetworkX
  cross-check), and **3 silos** with 92.4%, 93.3% and 100% internal edges.

**The recommendation table.** The top 20 missing pairs by Adamic-Adar, with both
institutions, shared-neighbour count, AA score, Jaccard and a same-community
badge. The scores rank candidates; they are not probabilities.

**Viva line.** "We trained only on collaborations up to 2020 and tested on pairs
that really formed in 2021 or later; Adamic-Adar ranks those real links with AUC
0.68, so the recommendations are better than guessing."

### 4. Reviewer assignment (`#/reviewers`)

**What it shows.** Problem 3: 1,200 papers, 3 reviewers each, 3,600 assignments.

- Coverage **100%**, mean relevance **0.4060**, best-of-three **0.4739**.
- **0 conflicts of interest**, maximum load **3**, capacity respected.
- Random eligible reviewers: **0.0182** mean relevance, a **22.3x** gap.
- Hungarian (one reviewer per paper): 0.4221 mean, but it cannot satisfy the
  three-reviewer requirement; it agrees with the flow's first choice on 92.5% of
  papers.

**The table.** A filterable, paginated view of all 3,600 rows. Entering an
OpenAlex paper id shows that paper's three reviewers; the rank badge 1/2/3 shows
the order, and the global badges prove zero COI and capacity 3.

**Viva line.** "The flow maximises total topic + text relevance under two hard
constraints - three reviewers per paper and at most three papers per reviewer -
and it never assigns a conflicted reviewer."

## How the browser talks to the API

1. `src/api.js` calls `${VITE_API_BASE}${path}` and turns non-2xx responses into
   readable errors (including FastAPI's `detail` text).
2. `src/useApi.js` runs one request per path and exposes
   `{ data, error, loading }`; a cancelled flag stops a slow response from
   overwriting a newer one.
3. The four views only render; they do not transform analytical values. The one
   exception is presentation maths: converting cascade points to percentages and
   averaging the 20 random replicates for a single readable line.
4. When Neo4j is stopped, the explorer shows the API's 503 hint while the other
   three views keep working from the result files - the same behaviour verified
   for the API in Stage 6.

## How it was verified

1. **Build:** `npm run build` - Vite 5.4.21, 41 modules, **4.90 s**, JS
   617.29 kB (198.72 kB gzip), CSS 7.98 kB, exit code 0. The only warning is the
   500 kB chunk size caused by Cytoscape.
2. **Real data:** API on `127.0.0.1:8000`, Neo4j 5.26 + GDS healthy, Vite dev
   server on `localhost:5173`. All four views loaded their real responses; the
   numbers above are read from the screenshots.
3. **CORS:** a request with `Origin: http://localhost:5173` returned
   `access-control-allow-origin: http://localhost:5173`.
4. **Screenshots:** `npm run screenshots` drives the installed Edge through
   `playwright-core` and writes full-page 1440 px images to
   `report/screenshots/`: `stage7_network_explorer.png`, `stage7_fragility.png`,
   `stage7_recommender.png`, `stage7_reviewers.png`.
5. **States:** loading, error (API down), empty filter result and zero-row
   paper filter are all handled explicitly; there is no placeholder data.

## Honest limitations

- The explorer is a **degree-ranked induced subgraph**, not the full network.
- The critical table is the **top 100 by betweenness**, not all authors; other
  sorts reorder that subset. A full ranking would need a live Neo4j query and is
  a possible extension, not something the current export supports.
- **13,188 vs 2,787**: 13,188 is every new 2021+ collaboration between training
  authors; only 2,787 have at least one shared neighbour and therefore enter the
  Adamic-Adar candidate universe. The UI labels both numbers separately.
- The cascade chart uses a 0-100% y-axis, so the curves sit close together. That
  is deliberate: the point is that the network stays largely connected, not that
  the lines differ dramatically.
- Cytoscape makes the bundle 617 kB; code-splitting the explorer is the obvious
  optimisation if load time matters.
- Local, read-only, single-user tool: no login, no saved state, no write
  endpoints.

## Viva questions and short answers

**Q: Does the frontend compute the analysis?**
A: No. It only formats what the API returns. The analysis is done once by the
Python/GDS scripts, so the report, the API and the UI cannot drift apart.

**Q: How do you know the UI is not showing fake data?**
A: Every value is traceable: the graph comes from Cypher on the loaded Neo4j
database, the other three views come from `data/results/*.json`. The screenshots
were taken against the running stack, and the same numbers appear in the Stage
3-5 sections above.

**Q: Why does the network view show only 300 nodes?**
A: It is an induced subgraph of the top authors by degree. The full core has
14,574 nodes and 81,793 edges; drawing that in a browser is unreadable and slow.
The limit is a UI control (up to 1,000) and the response says it is a subgraph.

**Q: What does node colour mean?**
A: The Louvain community from GDS. The palette cycles through 14 colours, so
two distant clusters can share a colour by coincidence; the selected author's
panel shows the exact community id.

**Q: Is the network fragile or robust?**
A: Both, in different senses. It has 670 articulation points and 660 bridges, so
individual bridges matter; but at 10% targeted removal the LCC is still 76.3%
(vs 82.4% random) and 184 node-disjoint paths connect the two hubs. It degrades
faster than random, but it does not shatter.

**Q: Why is the critical table only 100 rows?**
A: Stage 3 exported the top 100 by betweenness to CSV. Sorting by PageRank,
degree or k-core reorders that exported subset. The UI says so; claiming a full
ranking would be dishonest.

**Q: What does AUC 0.6824 mean here?**
A: Pick one real 2021+ collaboration and one pair that did not form; Adamic-Adar
scores the real one higher about 68% of the time. That is useful ranking signal,
not a guarantee.

**Q: Why does the Hungarian baseline have a higher mean score?**
A: It assigns exactly one reviewer per paper - the best one - and ignores the
three-reviewer requirement. The flow must fill three slots under a capacity of
three, and still keeps the Hungarian first choice in 92.5% of papers.

**Q: How are capacity and COI proved in the UI?**
A: The badges show 0 COI violations out of 3,600 assignments, maximum load 3,
and three reviewers per paper. Those are the verification results computed by
Stage 5, not a UI assertion.

**Q: Why hash routing instead of React Router?**
A: Four static views do not need a router dependency. Hash routing gives direct
links and reliable screenshots, including from a `file://` build.

**Q: How were the screenshots made?**
A: `frontend/scripts/screenshots.mjs` launches the installed Edge with
`playwright-core`, waits for real content, and writes full-page PNGs. It needs
the API and dev server running; the desktop browser tool required a visible
window, so this is the reproducible alternative.

## Commands

```powershell
# 1. Start the API (Neo4j healthy for the explorer)
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 2. Start the frontend
cd frontend
npm install
npm run dev            # http://localhost:5173

# 3. Production build
npm run build          # frontend/dist

# 4. Regenerate the four report screenshots
npm run screenshots    # needs :8000 and :5173 running
```

# Stage 8 - Packaging and reproducibility

Stage 8 adds no analysis. It makes the project runnable by someone who has never
seen it, and it fixes the last packaging defect.

## What was built

- **`README.md`** - prerequisites, setup, crawl, Neo4j load, analyses, API, UI,
  troubleshooting, deliverables tree and screenshot checklist.
- **`run_all.ps1`** - stage-selectable pipeline for Windows PowerShell, with
  precondition checks (`Python venv`, `.env`, Docker, npm) and clear failure
  messages.
- **`run_all.sh`** - the same stages for Linux/macOS/Git Bash.
- **`frontend/scripts/screenshots.mjs`** (from Stage 7) - reproducible
  full-page screenshots via Playwright + installed Edge.
- **`report/screenshots/CHECKLIST.md`** - what every image must prove and how to
  regenerate it.
- **`analysis/cli.py`** - the missing module behind the `rn-analysis` entry point
  (`pyproject.toml` already declared it, but the file did not exist; invoking
  `rn-analysis` would have failed).

## One command

```powershell
.\run_all.ps1 -Stage all -SkipFetch
```

| Stage | What it runs | Needs |
|---|---|---|
| `data` | fetch (unless `-SkipFetch`), clean, build, validate | network + `OPENALEX_EMAIL` for fetch; nothing else with `-SkipFetch` |
| `neo4j` | `docker compose up -d`, wait for healthy, load CSVs, verify, GDS projections | Docker Desktop |
| `analysis` | p1, p2, p3 | Neo4j + GDS for p1/p2; CSVs for p3 |
| `test` | pytest | Python only (live-Neo4j test skips) |
| `frontend` | `npm install` if needed, `npm run build` | Node 18+ |
| `backend` | start uvicorn on `:8000` (blocking) | Neo4j optional (analytics still work) |
| `all` | data -> neo4j -> analysis -> test -> frontend -> backend import check | everything above |

`all` deliberately does **not** leave servers running and does **not** take the
screenshots: those need two long-running terminals. The script prints the exact
commands at the end.

## The packaging bug that was fixed

`pyproject.toml` declared:

```toml
[project.scripts]
rn-analysis = "analysis.cli:main"
```

but `analysis/cli.py` did not exist. The package installed, yet the command
would fail with `ModuleNotFoundError` on first use. The new CLI dispatches:

```powershell
python -m analysis.cli p1 [--skip-null]
python -m analysis.cli p2
python -m analysis.cli p3
python -m analysis.cli all
```

`p1_fragility.main()` now accepts an optional argument list so the wrapper can
forward `--skip-null` without mutating `sys.argv`.

## How to reproduce the submitted numbers

1. Copy `.env.example` to `.env`; set `OPENALEX_EMAIL` and the Neo4j password.
2. Create the venv and install: `python -m venv .venv` then
   `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`.
3. Run `.\run_all.ps1 -Stage all -SkipFetch`.
4. Compare these checkpoints (the values from the submitted run):

| Checkpoint | Expected |
|---|---:|
| Papers / authors / institutions / topics | 26,188 / 42,774 / 4,817 / 1,765 |
| Co-authorship edges (full) | 170,700 |
| Core nodes / edges / LCC | 14,574 / 81,793 / 92.6% |
| Problem 1: articulation / bridges / max k-core / min cut | 670 / 660 / 16 / 184 |
| Problem 2: AA AUC / communities / silos | 0.6824 / 546 / 3 |
| Problem 3: coverage / mean / COI / max load | 100% / 0.4060 / 0 / 3 |

5. Start the API and UI in two terminals:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
cd frontend; npm run dev
```

`-SkipFetch` is the honest reproducibility path for the *submitted* dataset: it
cleans the submitted `data/raw` and rebuilds every derived file. A git-only
checkout does not contain `data/raw` (generated files are ignored), so it must
run without `-SkipFetch` and needs network access plus a real OpenAlex email.

## What was verified

- `run_all.ps1 -Stage frontend`: Vite build succeeded (6.65 s), exit 0.
- `run_all.ps1 -Stage test`: **27 passed** (Neo4j running).
- `run_all.ps1 -Stage all -SkipFetch`: completed every stage in **7.7 minutes**,
  exit 0 — data validation, Neo4j load, three analyses, 27 tests, frontend build,
  API import check (14 routes).
- Exact p1 run: **299.3 s**. A second direct
  `gds.betweenness.stream('authorGraph')` call returned identical top-5 scores,
  so the exact ranking is deterministic. Canonical values: 670 articulation
  points, 660 bridges, max k-core 16, 184 node-disjoint paths, cascade
  **76.3% vs 82.4%**.
- p2 canonical run: **546 communities, modularity 0.6234 (NetworkX 0.6927),
  3 silos**. This GDS build has no usable Louvain seed, so an earlier run gave
  545 / 0.6248; the submitted run is canonical and the variability is disclosed,
  not hidden.
- p3 is deterministic: **92.5%** top-1 agreement, 516 unused reviewers, random
  mean 0.0182.

## Viva questions and short answers

**Q: How would I run this from scratch?**
A: Copy `.env.example` to `.env`, install the Python package and frontend
dependencies, then `.\run_all.ps1 -Stage all -SkipFetch` (or without the flag to
crawl fresh data). Start uvicorn and `npm run dev` for the UI.

**Q: What does `run_all` actually guarantee?**
A: It stops at the first failing stage and prints which one failed. It checks
for the venv, `.env`, Docker and npm before pretending to work. It does not hide
errors or continue with stale data silently.

**Q: Why does `run_all` not start the servers?**
A: A pipeline that blocks forever is not a pipeline. `-Stage backend` starts the
API when you want it; `npm run dev` starts the UI. `all` verifies that the app
imports and that the build succeeds, then exits.

**Q: Where are the secrets?**
A: Only in `.env`, which is ignored by git. `.env.example` has placeholders.
`docker-compose.yml` reads `NEO4J_PASSWORD` from the environment; source code
never contains the real email or password.

**Q: Why is the report not included?**
A: The brief treats the written report as a separate deliverable. The code,
data, figures, screenshots and viva guide are complete; the report is written
only when the author asks for it.

**Q: What would you improve with more time?**
A: A full live ranking for `/api/critical` (the export is top 100 by
betweenness), code-splitting the Cytoscape view, and an automated end-to-end test
that starts the two servers and captures the screenshots.

## Commands

```powershell
# Full reproducibility run from the submitted raw cache
.\run_all.ps1 -Stage all -SkipFetch

# Individual stages
.\run_all.ps1 -Stage data -SkipFetch
.\run_all.ps1 -Stage neo4j
.\run_all.ps1 -Stage analysis
.\run_all.ps1 -Stage test
.\run_all.ps1 -Stage frontend
.\run_all.ps1 -Stage backend

# Linux / macOS
./run_all.sh --stage all --skip-fetch
```

# Final viva cheat sheet

## 60-second demo order

1. **Network explorer** (`#/network`): "Each dot is an author; this is the
   strongest 300 by degree from the 14,574-node core. Click one to see their real
   profile."
2. **Fragility** (`#/fragility`): "670 cut vertices and 660 bridges, but removing
   10% of the most central authors still leaves 76.3% connected - targeted
   damage is worse than random (82.4%), but the core is dense."
3. **Silos & recommender** (`#/recommender`): "546 communities, 3 silos, and
   Adamic-Adar scores real 2021+ collaborations with AUC 0.68 after training only
   on pre-2021 data."
4. **Reviewers** (`#/reviewers`): "Three reviewers per paper, capacity 3, zero
   conflicts, 22x better than random."

## Numbers to remember

| Question | Answer |
|---|---|
| Dataset | 26,627 OpenAlex works -> 26,188 papers, 42,774 authors |
| Graph | 170,700 co-author edges; full LCC 79.7% |
| Analysis network | 14,574 authors, 81,793 edges, LCC 92.6% |
| Fragility | 670 articulation points, 660 bridges, k-core 16, min cut 184 |
| Cascade at 10% | 76.3% (betweenness) vs 82.4% (random) |
| Link prediction | Adamic-Adar AUC 0.6824; 2,787 positives in 228,127 candidates |
| Communities | 546, modularity 0.6234 (GDS) / 0.6927 (NetworkX), 3 silos |
| Reviewers | 1,200 papers, 1,899 reviewers, 3,600 assignments, 0 COI |
| Assignment quality | mean 0.4060 vs random 0.0182; 22.3x lift |

## The one-paragraph pitch

"I built a knowledge graph of Pakistani computer-science research from 26,188
real OpenAlex papers, loaded it into Neo4j with GDS, and analysed it in three
ways: who is structurally critical, where the isolated communities are and which
new collaborations are likely, and how to assign reviewers fairly under capacity
and conflict rules. The frontend exposes each result with the real numbers, and
the whole pipeline is reproducible with one command."

## If the examiner asks...

**"Is this real data?"** Every node and edge comes from OpenAlex (CC0); the
cleaning report shows the raw-to-clean counts, and the API/UI read the generated
result files.

**"Why Neo4j?"** The graph model (authors, papers, institutions, topics,
citations) and GDS algorithms (PageRank, betweenness, k-core, Louvain,
articulation points, bridges) are native there; Python is used only for what GDS
lacks (cascades, null models, matching, evaluation).

**"What is the main finding?"** The network is bridge-heavy but not fragile: many
individual cut vertices, yet a dense core keeps most authors connected even after
targeted removal.

**"What is the weakest part?"** OpenAlex author disambiguation and missing
citations; the critical ranking export is top-100; Louvain in this GDS build has
no seed. All three are stated in the docs rather than hidden.
