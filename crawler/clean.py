"""Turn the raw OpenAlex cache into clean node and edge CSV files.

Cleaning rules (all counted in data/cleaning_report.md):
  1. works are de-duplicated by OpenAlex work id;
  2. works without id, title, year or authors are dropped;
  3. authorships without an OpenAlex author id are dropped (cannot be linked);
  4. a repeated author on the same paper is counted once (this is the self-loop
     of a co-authorship graph);
  5. citations are kept only when BOTH papers are in the dataset, and a paper
     citing itself is removed;
  6. missing optional values (DOI, ORCID, institution, topic) are left empty and
     counted, never invented.

Outputs (data/cleaned):
  authors.csv, papers.csv, institutions.csv, topics.csv,
  wrote.csv, affiliated_with.csv, about.csv, cites.csv
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Iterator

from crawler.config import CLEANED_DIR, RAW_DIR, RESULTS_DIR, ensure_dirs

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def short_id(value: str | None) -> str:
    """OpenAlex returns URLs like https://openalex.org/W123; we store W123."""
    if not value:
        return ""
    return value.rstrip("/").split("/")[-1]


def clean_text(value: Any) -> str:
    """Collapse whitespace so names/titles compare reliably."""
    return " ".join(str(value or "").split())


def iter_raw_works() -> Iterator[dict[str, Any]]:
    """Yield every work from the cached pages, in download order."""
    for path in sorted(RAW_DIR.glob("page_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for work in payload.get("results", []):
            yield work


def write_csv(filename: str, header: list[str], rows: list[list[Any]]) -> None:
    """Write a CSV with UTF-8 and Unix line endings (predictable on every OS)."""
    path = CLEANED_DIR / filename
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  wrote {filename}: {len(rows)} rows")


# ---------------------------------------------------------------------------
# Main cleaning pass
# ---------------------------------------------------------------------------


def clean_dataset() -> dict[str, Any]:
    ensure_dirs()

    # Node tables. Dictionaries guarantee one row per OpenAlex id.
    papers: dict[str, dict[str, Any]] = {}
    authors: dict[str, dict[str, Any]] = {}
    institutions: dict[str, dict[str, Any]] = {}
    topics: dict[str, dict[str, Any]] = {}

    # Edge tables.
    wrote: list[tuple[str, str, str, int]] = []
    affiliation_years: dict[tuple[str, str], set[int]] = defaultdict(set)
    about_pairs: set[tuple[str, str, float]] = set()
    raw_citations: list[tuple[str, str]] = []
    seen_author_paper: set[tuple[str, str]] = set()

    # Counters for the before/after report.
    counts: Counter[str] = Counter()
    missing: Counter[str] = Counter()

    for work in iter_raw_works():
        counts["raw_works"] += 1

        paper_id = short_id(work.get("id"))
        if not paper_id:
            counts["dropped_missing_work_id"] += 1
            continue
        if paper_id in papers:
            counts["dropped_duplicate_work"] += 1
            continue

        title = clean_text(work.get("title"))
        year = work.get("publication_year")
        authorships = work.get("authorships") or []
        if not title:
            counts["dropped_missing_title"] += 1
            continue
        if not year:
            counts["dropped_missing_year"] += 1
            continue
        if not authorships:
            counts["dropped_no_authors"] += 1
            continue

        doi = clean_text(work.get("doi")).replace("https://doi.org/", "")
        if not doi:
            missing["papers_without_doi"] += 1

        # --- authors and their institutions ---------------------------------
        paper_authors: list[str] = []
        paper_is_pk = False
        for authorship in authorships:
            counts["authorship_rows"] += 1
            person = authorship.get("author") or {}
            author_id = short_id(person.get("id"))
            if not author_id:
                # No OpenAlex id means we cannot merge this person reliably.
                counts["dropped_authorship_without_author_id"] += 1
                continue

            # The co-authorship self-loop: the same author listed twice on a paper.
            if (paper_id, author_id) in seen_author_paper:
                counts["dropped_duplicate_author_on_paper"] += 1
                continue
            seen_author_paper.add((paper_id, author_id))

            name = clean_text(person.get("display_name") or authorship.get("raw_author_name"))
            if not name:
                name = "Unknown author"
                missing["authors_without_name"] += 1

            orcid = clean_text(person.get("orcid")) or ""
            if not orcid:
                missing["authorships_without_orcid"] += 1

            author = authors.setdefault(
                author_id,
                {
                    "author_id": author_id,
                    "names": Counter(),
                    "orcid": "",
                    "works_count": 0,
                    "cited_by_count": 0,
                    "first_year": int(year),
                    "last_year": int(year),
                    "pk_affiliated": 0,
                    "institution_counts": Counter(),
                    "topic_counts": Counter(),
                },
            )
            author["names"][name] += 1
            author["works_count"] += 1
            author["cited_by_count"] += int(work.get("cited_by_count") or 0)
            author["first_year"] = min(author["first_year"], int(year))
            author["last_year"] = max(author["last_year"], int(year))
            if orcid and not author["orcid"]:
                author["orcid"] = orcid

            # OpenAlex can put the same institution twice on one authorship.
            author_institutions = {
                short_id(inst.get("id"))
                for inst in (authorship.get("institutions") or [])
                if inst.get("id")
            }
            if not author_institutions:
                missing["authorships_without_institution"] += 1
            for inst_id in author_institutions:
                institutions.setdefault(
                    inst_id,
                    {
                        "institution_id": inst_id,
                        "name": "",
                        "country_code": "",
                        "type": "",
                    },
                )
                # Fill names/country from this authorship when still empty.
                source = next(
                    inst
                    for inst in authorship["institutions"]
                    if short_id(inst.get("id")) == inst_id
                )
                inst = institutions[inst_id]
                inst["name"] = inst["name"] or clean_text(source.get("display_name"))
                inst["country_code"] = inst["country_code"] or clean_text(source.get("country_code"))
                inst["type"] = inst["type"] or clean_text(source.get("type"))

                affiliation_years[(author_id, inst_id)].add(int(year))
                author["institution_counts"][inst_id] += 1
                if inst["country_code"] == "PK":
                    paper_is_pk = True
                    author["pk_affiliated"] = 1

            # `countries` also contains PK when the institution metadata is weak.
            if "PK" in (authorship.get("countries") or []):
                paper_is_pk = True

            position = authorship.get("author_position") or "middle"
            is_corresponding = 1 if authorship.get("is_corresponding") else 0
            wrote.append((author_id, paper_id, position, is_corresponding))
            paper_authors.append(author_id)

        if not paper_authors:
            # All authorships were unusable: the paper has no edges and is dropped.
            counts["dropped_no_valid_authors"] += 1
            # It may already be in `papers` only if we added it earlier; we have not.
            continue

        # --- topics ----------------------------------------------------------
        primary = work.get("primary_topic") or {}
        topic_list = list(work.get("topics") or [])
        if primary:
            # Put the primary topic first and remove its duplicate from `topics`.
            primary_id = short_id(primary.get("id"))
            topic_list = [primary] + [
                topic for topic in topic_list if short_id(topic.get("id")) != primary_id
            ]

        kept_topics: set[str] = set()
        for index, topic in enumerate(topic_list):
            topic_id = short_id(topic.get("id"))
            if not topic_id or topic_id in kept_topics:
                continue
            kept_topics.add(topic_id)
            subfield = topic.get("subfield") or {}
            field = topic.get("field") or {}
            domain = topic.get("domain") or {}
            topics.setdefault(
                topic_id,
                {
                    "topic_id": topic_id,
                    "name": clean_text(topic.get("display_name")),
                    "subfield_id": short_id(subfield.get("id")),
                    "subfield": clean_text(subfield.get("display_name")),
                    "field_id": short_id(field.get("id")),
                    "field": clean_text(field.get("display_name")),
                    "domain_id": short_id(domain.get("id")),
                    "domain": clean_text(domain.get("display_name")),
                },
            )
            score = 1.0 if index == 0 else round(float(topic.get("score") or 0.0), 4)
            about_pairs.add((paper_id, topic_id, score))
            if index == 2:  # keep the three strongest topics per paper
                break
        if not kept_topics:
            missing["papers_without_topic"] += 1

        # Credit each topic to every author of this paper. Without this the
        # author `topics` column (and reviewer profiles) would be empty.
        for author_id in paper_authors:
            for topic_id in kept_topics:
                authors[author_id]["topic_counts"][topic_id] += 1

        # Cited works are filtered after all papers are known (next phase).
        for ref in work.get("referenced_works") or []:
            raw_citations.append((paper_id, short_id(ref)))

        papers[paper_id] = {
            "paper_id": paper_id,
            "doi": doi,
            "title": title,
            "year": int(year),
            "type": clean_text(work.get("type")),
            "cited_by_count": int(work.get("cited_by_count") or 0),
            "is_pk": int(paper_is_pk),
            "author_count": len(paper_authors),
            "topic_count": len(kept_topics),
        }
        counts["kept_papers"] += 1

    # --- citations: both ends must be in the dataset -------------------------
    citations: set[tuple[str, str]] = set()
    for source, target in raw_citations:
        counts["citation_refs"] += 1
        if not target:
            counts["dropped_citation_without_target"] += 1
        elif source == target:
            counts["dropped_self_citation"] += 1
        elif target not in papers:
            counts["dropped_citation_outside_dataset"] += 1
        elif (source, target) in citations:
            counts["dropped_duplicate_citation"] += 1
        else:
            citations.add((source, target))

    # --- finalise author rows -------------------------------------------------
    author_rows: list[list[Any]] = []
    for author_id, author in authors.items():
        if not author["works_count"]:
            continue
        name = author["names"].most_common(1)[0][0] if author["names"] else "Unknown author"
        primary_institution_id = ""
        primary_institution = ""
        if author["institution_counts"]:
            primary_institution_id = author["institution_counts"].most_common(1)[0][0]
            primary_institution = institutions[primary_institution_id]["name"]
        topic_names = [
            topics[topic_id]["name"]
            for topic_id, _ in author["topic_counts"].most_common(3)
            if topic_id in topics
        ]
        author_rows.append(
            [
                author_id,
                name,
                author["orcid"],
                author["works_count"],
                author["cited_by_count"],
                author["first_year"],
                author["last_year"],
                author["pk_affiliated"],
                primary_institution_id,
                primary_institution,
                ";".join(topic_names),
                "",  # degree, filled by build_graph.py
                "",  # strength, filled by build_graph.py
            ]
        )

    # --- write node CSVs ------------------------------------------------------
    author_rows.sort(key=lambda row: (-int(row[3]), row[1].lower()))
    write_csv(
        "authors.csv",
        [
            "author_id", "name", "orcid", "works_count", "cited_by_count",
            "first_year", "last_year", "pk_affiliated", "primary_institution_id",
            "primary_institution", "topics", "degree", "strength",
        ],
        author_rows,
    )

    paper_rows = [
        [
            p["paper_id"], p["doi"], p["title"], p["year"], p["type"],
            p["cited_by_count"], p["is_pk"], p["author_count"], p["topic_count"],
        ]
        for p in sorted(papers.values(), key=lambda p: (-p["year"], p["paper_id"]))
    ]
    write_csv(
        "papers.csv",
        ["paper_id", "doi", "title", "year", "type", "cited_by_count",
         "is_pk", "author_count", "topic_count"],
        paper_rows,
    )

    institution_rows = [
        [i["institution_id"], i["name"], i["country_code"], i["type"]]
        for i in sorted(institutions.values(), key=lambda i: i["name"].lower())
    ]
    write_csv(
        "institutions.csv",
        ["institution_id", "name", "country_code", "type"],
        institution_rows,
    )

    topic_rows = [
        [t["topic_id"], t["name"], t["subfield_id"], t["subfield"],
         t["field_id"], t["field"], t["domain_id"], t["domain"]]
        for t in sorted(topics.values(), key=lambda t: t["name"].lower())
    ]
    write_csv(
        "topics.csv",
        ["topic_id", "name", "subfield_id", "subfield", "field_id", "field",
         "domain_id", "domain"],
        topic_rows,
    )

    # --- write edge CSVs ------------------------------------------------------
    wrote.sort(key=lambda row: (row[1], row[0]))
    write_csv(
        "wrote.csv",
        ["author_id", "paper_id", "position", "is_corresponding"],
        [list(row) for row in wrote],
    )

    affiliation_rows = [
        [author_id, inst_id, ";".join(str(y) for y in sorted(years))]
        for (author_id, inst_id), years in sorted(affiliation_years.items())
    ]
    write_csv(
        "affiliated_with.csv",
        ["author_id", "institution_id", "years"],
        affiliation_rows,
    )

    about_rows = [
        [paper_id, topic_id, score]
        for paper_id, topic_id, score in sorted(about_pairs)
    ]
    write_csv("about.csv", ["paper_id", "topic_id", "score"], about_rows)

    write_csv(
        "cites.csv",
        ["citing_id", "cited_id"],
        [list(pair) for pair in sorted(citations)],
    )

    # --- before/after summary -------------------------------------------------
    summary: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw": {
            "pages": len(list(RAW_DIR.glob("page_*.json"))),
            "works_fetched": counts["raw_works"],
            "works_kept": len(papers),
        },
        "cleaning": {
            "duplicate_works_removed": counts["dropped_duplicate_work"],
            "works_missing_id_removed": counts["dropped_missing_work_id"],
            "works_missing_title_removed": counts["dropped_missing_title"],
            "works_missing_year_removed": counts["dropped_missing_year"],
            "works_without_authors_removed": counts["dropped_no_authors"],
            "works_without_valid_authors_removed": counts["dropped_no_valid_authors"],
            "authorship_rows": counts["authorship_rows"],
            "authorships_without_author_id_removed": counts["dropped_authorship_without_author_id"],
            "duplicate_authors_on_same_paper_removed": counts["dropped_duplicate_author_on_paper"],
            "citation_refs": counts["citation_refs"],
            "self_citations_removed": counts["dropped_self_citation"],
            "citations_outside_dataset_removed": counts["dropped_citation_outside_dataset"],
            "duplicate_citations_removed": counts["dropped_duplicate_citation"],
        },
        "missing_values": dict(missing),
        "nodes": {
            "authors": len(author_rows),
            "papers": len(paper_rows),
            "institutions": len(institution_rows),
            "topics": len(topic_rows),
        },
        "edges": {
            "wrote": len(wrote),
            "affiliated_with": len(affiliation_rows),
            "about": len(about_rows),
            "cites": len(citations),
        },
    }
    (RESULTS_DIR / "cleaning_stats.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def write_cleaning_report(summary: dict[str, Any]) -> None:
    """Human-readable before/after report required by the grading guidelines."""
    raw = summary["raw"]
    cleaning = summary["cleaning"]
    missing = summary["missing_values"]
    nodes = summary["nodes"]
    edges = summary["edges"]

    def table(rows: list[tuple[str, Any, Any]], headers: tuple[str, str, str]) -> str:
        lines = [f"| {headers[0]} | {headers[1]} | {headers[2]} |", "|---|---:|---:|"]
        lines += [f"| {name} | {before} | {after} |" for name, before, after in rows]
        return "\n".join(lines)

    works_removed = (
        cleaning["duplicate_works_removed"]
        + cleaning["works_missing_id_removed"]
        + cleaning["works_missing_title_removed"]
        + cleaning["works_missing_year_removed"]
        + cleaning["works_without_authors_removed"]
        + cleaning["works_without_valid_authors_removed"]
    )

    text = f"""# Data cleaning report

Generated: {summary['generated_at']}

## Source

- **Dataset:** OpenAlex works API, <https://api.openalex.org/works>
- **Licence:** CC0 1.0 Universal (public domain dedication)
- **Scope:** at least one institution in Pakistan (`institutions.country_code:PK`),
  primary topic in Computer Science (`fields/17`), publication years 2015-2025,
  types `article`, `proceedings-article`, `review`, `book-chapter`.
- **Raw cache:** {raw['pages']} pages, {raw['works_fetched']} work records.
  Raw pages are stored unchanged (the selected fields only) in `data/raw/`.
- Preprints are excluded on purpose: they often duplicate a later published paper,
  which would double-count the same collaboration.

## Before / after

### Works (papers)

{table([
    ('Raw work records fetched', raw['works_fetched'], raw['works_fetched']),
    ('Duplicate OpenAlex work ids removed', cleaning['duplicate_works_removed'], 0),
    ('Missing work id removed', cleaning['works_missing_id_removed'], 0),
    ('Missing title removed', cleaning['works_missing_title_removed'], 0),
    ('Missing publication year removed', cleaning['works_missing_year_removed'], 0),
    ('No authorships removed', cleaning['works_without_authors_removed'], 0),
    ('No usable author id removed', cleaning['works_without_valid_authors_removed'], 0),
    ('Final papers', raw['works_fetched'], nodes['papers']),
], ('Rule', 'Before (rows)', 'After (rows)'))}

Total removed: **{works_removed}** works.

### Authorships (becomes `WROTE` edges)

{table([
    ('Authorship rows in raw data', cleaning['authorship_rows'], cleaning['authorship_rows']),
    ('Authorship without OpenAlex author id', cleaning['authorship_rows'], cleaning['authorship_rows'] - cleaning['authorships_without_author_id_removed']),
    ('Duplicate author on the same paper (self-loop)', cleaning['authorship_rows'], cleaning['authorship_rows'] - cleaning['authorships_without_author_id_removed'] - cleaning['duplicate_authors_on_same_paper_removed']),
    ('Final WROTE edges', cleaning['authorship_rows'], edges['wrote']),
], ('Rule', 'Before (rows)', 'After (rows)'))}

### Citations (becomes `CITES` edges)

{table([
    ('Referenced-work entries', cleaning['citation_refs'], cleaning['citation_refs']),
    ('Paper citing itself (self-loop)', cleaning['citation_refs'], cleaning['citation_refs'] - cleaning['self_citations_removed']),
    ('Cited paper outside this dataset', cleaning['citation_refs'], cleaning['citation_refs'] - cleaning['self_citations_removed'] - cleaning['citations_outside_dataset_removed']),
    ('Duplicate citation pairs', cleaning['citation_refs'], cleaning['citation_refs'] - cleaning['self_citations_removed'] - cleaning['citations_outside_dataset_removed'] - cleaning['duplicate_citations_removed']),
    ('Final CITES edges', cleaning['citation_refs'], edges['cites']),
], ('Rule', 'Before (rows)', 'After (rows)'))}

## Final node and edge counts

| Table | Rows |
|---|---:|
| Authors | {nodes['authors']} |
| Papers | {nodes['papers']} |
| Institutions | {nodes['institutions']} |
| Topics | {nodes['topics']} |
| WROTE | {edges['wrote']} |
| AFFILIATED_WITH | {edges['affiliated_with']} |
| ABOUT | {edges['about']} |
| CITES | {edges['cites']} |

## Missing values (not imputed)

| Field | Missing count |
|---|---:|
| Papers without DOI | {missing.get('papers_without_doi', 0)} |
| Authorships without ORCID | {missing.get('authorships_without_orcid', 0)} |
| Authorships without an institution | {missing.get('authorships_without_institution', 0)} |
| Papers without a topic | {missing.get('papers_without_topic', 0)} |
| Authors without a display name | {missing.get('authors_without_name', 0)} |

Missing optional values are left empty on purpose. Imputing them would invent
information; every analysis that needs the field states how it handles blanks.

## Notes and limitations

- Author identity comes from **OpenAlex author ids**, not names. This avoids most
  name-collision problems but inherits OpenAlex's own disambiguation errors.
- OpenAlex sometimes returns an authorship without an author id (one was observed
  during development). Those authorship rows cannot be merged safely and are
  dropped, with the count above.
- The scope requires a Pakistani institution, so the graph also contains foreign
  co-authors. That is intentional: international collaborators are part of the
  collaboration network and matter for the fragility and silo analyses.
- `CITES` only covers citations where the cited paper is inside this 26k-paper
  slice, so it is a subset of the full citation graph. This is stated again in the
  analysis docs.
"""
    path = CLEANED_DIR.parent / "cleaning_report.md"
    path.write_text(text, encoding="utf-8")
    print(f"  wrote {path.name}")
