# Data dictionary

## Dataset

| Field | Value |
|---|---|
| Source | OpenAlex works API — <https://api.openalex.org/works> |
| Licence | **CC0 1.0 Universal** (public domain dedication) |
| Citation | Priem, J., Piwowar, H., & Orr, R. (2022). *OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts.* arXiv:2205.01833 |
| Extracted | 2026-10-20 (see `data/results/cleaning_stats.json`) |
| Scope | Works with at least one **Pakistan**-affiliated institution, primary topic in **Computer Science** (OpenAlex field 17), published **2015–2025**, types `article`, `proceedings-article`, `review`, `book-chapter` |
| Raw cache | `data/raw/page_YYYY_NNNNN.json`, 136 pages, 26,627 works (selected fields, unmodified) |
| Cleaned | 26,188 papers, 42,774 authors, 4,817 institutions, 1,765 topics |

**Why preprints are excluded:** a preprint and its published version usually
describe the same collaboration and would double-count the same edge.

**OpenAlex author ids** are used for identity (not names). This inherits
OpenAlex's disambiguation, including its errors. Authorships without an id are
dropped and counted in the cleaning report.

---

## Node files (`data/cleaned/`)

### `authors.csv` — 42,774 rows

The complete Author node table for Neo4j.

| Column | Type | Description |
|---|---|---|
| `author_id` | string | OpenAlex author id, e.g. `A5032425002` (primary key) |
| `name` | string | Most frequent display name in this dataset |
| `orcid` | string | ORCID URL/id when OpenAlex has one, else empty |
| `works_count` | int | Number of papers **in this dataset** (not OpenAlex's global count) |
| `cited_by_count` | int | Sum of citations of those papers |
| `first_year`, `last_year` | int | First/last publication year in the dataset |
| `pk_affiliated` | 0/1 | 1 if any affiliation is in Pakistan |
| `primary_institution_id` | string | Institution appearing most often for this author |
| `primary_institution` | string | Its display name (empty if unknown) |
| `topics` | string | Up to 3 most frequent topic names, separated by `;` |
| `degree`, `strength` | empty | Filled in `author_nodes.csv`; kept here so both files share a header |

### `papers.csv` — 26,188 rows

| Column | Type | Description |
|---|---|---|
| `paper_id` | string | OpenAlex work id, e.g. `W3159196909` (primary key) |
| `doi` | string | DOI without the `https://doi.org/` prefix; empty if missing |
| `title` | string | Work title |
| `year` | int | Publication year (2015–2025) |
| `type` | string | OpenAlex type |
| `cited_by_count` | int | Citations reported by OpenAlex |
| `is_pk` | 0/1 | 1 if at least one author affiliation is Pakistani |
| `author_count` | int | Authors on the paper (after cleaning) |
| `topic_count` | int | Topics kept for the paper (max 3) |

### `institutions.csv` — 4,817 rows

| Column | Type | Description |
|---|---|---|
| `institution_id` | string | OpenAlex institution id, e.g. `I134276161` |
| `name` | string | Institution display name |
| `country_code` | string | ISO country code (`PK`, `SA`, …); may be empty |
| `type` | string | OpenAlex type (`education`, `company`, …) |

### `topics.csv` — 1,765 rows

| Column | Type | Description |
|---|---|---|
| `topic_id` | string | OpenAlex topic id, e.g. `T10038` |
| `name` | string | Topic display name |
| `subfield_id`, `subfield` | string | Subfield id and name |
| `field_id`, `field` | string | Field id and name (all papers are field 17, Computer Science) |
| `domain_id`, `domain` | string | Domain id and name |

---

## Relationship files (`data/cleaned/`)

### `wrote.csv` — 109,066 rows → `(:Author)-[:WROTE]->(:Paper)`

| Column | Type | Description |
|---|---|---|
| `author_id` | string | Author |
| `paper_id` | string | Paper |
| `position` | string | `first`, `middle`, `last` |
| `is_corresponding` | 0/1 | Corresponding author flag |

### `affiliated_with.csv` — 57,931 rows → `(:Author)-[:AFFILIATED_WITH]->(:Institution)`

| Column | Type | Description |
|---|---|---|
| `author_id` | string | Author |
| `institution_id` | string | Institution |
| `years` | string | Semicolon-separated years in which the affiliation was observed, e.g. `2019;2020` |

### `about.csv` — 78,564 rows → `(:Paper)-[:ABOUT]->(:Topic)`

| Column | Type | Description |
|---|---|---|
| `paper_id` | string | Paper |
| `topic_id` | string | Topic |
| `score` | float | 1.0 for the primary topic, otherwise OpenAlex's topic score (0–1) |

### `cites.csv` — 40,735 rows → `(:Paper)-[:CITES]->(:Paper)`

| Column | Type | Description |
|---|---|---|
| `citing_id` | string | Citing paper |
| `cited_id` | string | Cited paper (must also be in `papers.csv`) |

Only citations where **both** papers are inside this 26k-paper slice are kept.
The raw data had 915,022 references; 95.5% point outside the slice.

---

## Analysis graph files

### Full co-authorship network

- `author_nodes.csv` — 42,774 rows: all Author columns plus `degree` and
  `strength`. `degree` = number of distinct co-authors, `strength` = sum of
  shared-paper counts. Authors with no co-author have degree 0.
- `author_edges.csv` — 170,700 rows: undirected weighted co-authorship edges.
- `graphml/author_graph.graphml` — the same graph, including isolated authors.

| Edge column | Type | Description |
|---|---|---|
| `source`, `target` | string | Author ids (alphabetically ordered, one row per pair) |
| `weight` | int | Number of shared papers |
| `first_year`, `last_year` | int | First/last year of the collaboration |
| `papers` | string | Up to 20 shared paper ids, separated by `;` |

### Core analysis network (used by the three problems)

- `author_nodes_core.csv` — 14,574 authors with **at least 2 papers** and ≥1 co-author.
- `author_edges_core.csv` — 81,793 edges induced by those authors.
- `graphml/author_graph_core.graphml` — the same graph.

| Measure | Full network | Core network |
|---|---:|---:|
| Nodes | 41,247 collaborating (42,774 with isolates) | 14,574 |
| Edges | 170,700 | 81,793 |
| Components | 2,148 | 511 |
| Largest component | 32,879 | 13,493 |
| LCC % of nodes | 79.7% | **92.6%** |

The core network is used for centrality, communities, link prediction and
reviewer assignment because one-off authors cannot show a recurring collaboration
pattern and add noise to those methods. The full network remains the dataset's
knowledge graph and is loaded into Neo4j.

---

## GraphML attributes

Node attributes: `name`, `institution`, `topics`, `degree`, `strength`,
`pk_affiliated`, `first_year`, `last_year`.

Edge attributes: `weight`, `first_year`, `last_year`, `papers`.

---

## Known data-quality issues (all counted in `cleaning_report.md`)

| Issue | Count | Handling |
|---|---:|---|
| Authorship rows without an OpenAlex author id | 10,052 of 119,372 | Dropped (cannot merge safely) |
| Papers left with no usable author | 439 | Dropped |
| Repeated author on the same paper (self-loop) | 254 | Counted once |
| Authorships without an institution | 4,309 | Author kept, no `AFFILIATED_WITH` edge |
| Papers without a DOI | 1,727 | DOI left empty |
| Self-citations | 158 | Dropped |
| Citations pointing outside the dataset | 874,129 | Dropped (documented limitation) |
| Papers with >30 authors | 9 | Skipped in the projection (consortium papers) |
| Single-author papers | 2,085 | No co-authorship edge (author becomes an isolate) |
