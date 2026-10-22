# Data cleaning report

Generated: 2026-10-21T09:41:22+00:00

## Source

- **Dataset:** OpenAlex works API, <https://api.openalex.org/works>
- **Licence:** CC0 1.0 Universal (public domain dedication)
- **Scope:** at least one institution in Pakistan (`institutions.country_code:PK`),
  primary topic in Computer Science (`fields/17`), publication years 2015-2025,
  types `article`, `proceedings-article`, `review`, `book-chapter`.
- **Raw cache:** 136 pages, 26627 work records.
  Raw pages are stored unchanged (the selected fields only) in `data/raw/`.
- Preprints are excluded on purpose: they often duplicate a later published paper,
  which would double-count the same collaboration.

## Before / after

### Works (papers)

| Rule | Before (rows) | After (rows) |
|---|---:|---:|
| Raw work records fetched | 26627 | 26627 |
| Duplicate OpenAlex work ids removed | 0 | 0 |
| Missing work id removed | 0 | 0 |
| Missing title removed | 0 | 0 |
| Missing publication year removed | 0 | 0 |
| No authorships removed | 0 | 0 |
| No usable author id removed | 439 | 0 |
| Final papers | 26627 | 26188 |

Total removed: **439** works.

### Authorships (becomes `WROTE` edges)

| Rule | Before (rows) | After (rows) |
|---|---:|---:|
| Authorship rows in raw data | 119372 | 119372 |
| Authorship without OpenAlex author id | 119372 | 109320 |
| Duplicate author on the same paper (self-loop) | 119372 | 109066 |
| Final WROTE edges | 119372 | 109066 |

### Citations (becomes `CITES` edges)

| Rule | Before (rows) | After (rows) |
|---|---:|---:|
| Referenced-work entries | 915022 | 915022 |
| Paper citing itself (self-loop) | 915022 | 914864 |
| Cited paper outside this dataset | 915022 | 40735 |
| Duplicate citation pairs | 915022 | 40735 |
| Final CITES edges | 915022 | 40735 |

## Final node and edge counts

| Table | Rows |
|---|---:|
| Authors | 42774 |
| Papers | 26188 |
| Institutions | 4817 |
| Topics | 1765 |
| WROTE | 109066 |
| AFFILIATED_WITH | 57931 |
| ABOUT | 78564 |
| CITES | 40735 |

## Missing values (not imputed)

| Field | Missing count |
|---|---:|
| Papers without DOI | 1727 |
| Authorships without ORCID | 21803 |
| Authorships without an institution | 4309 |
| Papers without a topic | 0 |
| Authors without a display name | 0 |

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
