"""Download works from OpenAlex with per-year page pagination and a resumable cache.

Why per-year pages instead of one cursor?
  OpenAlex (2026) requires a free API key for cursor paging past the first page,
  but plain `page=` paging still works. A single query is also limited to 10,000
  results, so we issue one query per publication year. Each year is well below
  that limit (2,000-4,000 works), and the year is useful metadata anyway.

Each page is stored as JSON in data/raw/page_YYYY_NNNNN.json and manifest.json
records the position. Re-running `fetch` continues where it stopped.

Set OPENALEX_API_KEY in .env to use the key (higher daily budget). Without it,
the request uses OpenAlex's shared anonymous budget.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from crawler.config import (
    FIELD_ID,
    RAW_DIR,
    WORK_SELECT,
    WORK_TYPES,
    ensure_dirs,
    get_settings,
)

API_URL = "https://api.openalex.org/works"
MANIFEST = RAW_DIR / "manifest.json"
RETRY_STATUS = {429, 500, 502, 503, 504}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _headers(email: str) -> dict[str, str]:
    """Identify the client; OpenAlex asks for a contact address (polite pool)."""
    agent = "researchers-network/0.1 (semester project)"
    if email:
        agent += f" (mailto:{email})"
    return {"User-Agent": agent, "Accept": "application/json"}


def _year_filter(year: int) -> str:
    """Filter for one year. Kept as a separate function so the scope is explicit."""
    types = "|".join(WORK_TYPES)
    return (
        f"institutions.country_code:PK,"
        f"primary_topic.field.id:{FIELD_ID},"
        f"publication_year:{year},"
        f"type:{types}"
    )


def _year_list(years: str) -> list[int]:
    """Parse '2015-2025' (or '2019,2020') into an ordered list of years."""
    if "-" in years and "," not in years:
        start, end = years.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return sorted(int(part) for part in years.split(",") if part.strip())


def _page_path(year: int, page: int) -> Any:
    return RAW_DIR / f"page_{year}_{page:05d}.json"


def _load_manifest() -> dict[str, Any] | None:
    if not MANIFEST.exists():
        return None
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _save_manifest(manifest: dict[str, Any]) -> None:
    """Write atomically so an interrupted run cannot leave a broken manifest."""
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST)


def _request_page(
    client: httpx.Client, year: int, page: int, per_page: int, email: str, api_key: str
) -> dict[str, Any]:
    """Fetch one page, retrying temporary failures with exponential backoff."""
    params: dict[str, Any] = {
        "filter": _year_filter(year),
        "per-page": per_page,
        "page": page,
        "select": WORK_SELECT,
    }
    # Only a real address goes into the query. Sending the .env.example
    # placeholder makes OpenAlex answer 401.
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key

    last_error: Exception | None = None
    for attempt in range(1, 6):
        try:
            response = client.get(API_URL, params=params)
            if response.status_code == 200:
                return response.json()
            if response.status_code in RETRY_STATUS:
                wait = int(response.headers.get("Retry-After", 2**attempt))
                print(f"  HTTP {response.status_code}; waiting {wait}s (attempt {attempt}/5)")
                time.sleep(wait)
                last_error = RuntimeError(f"HTTP {response.status_code}")
                continue
            # 401/403 usually means the daily budget or the API key is the problem.
            detail = response.text[:250]
            raise RuntimeError(f"OpenAlex HTTP {response.status_code}: {detail}")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            wait = 2**attempt
            print(f"  network error ({exc}); waiting {wait}s (attempt {attempt}/5)")
            time.sleep(wait)
    raise RuntimeError(f"OpenAlex request failed after 5 attempts: {last_error}")


def fetch_all(limit: int | None = None, reset: bool = False, delay: float = 0.2) -> dict[str, Any]:
    """Download all pages in the configured scope (one query per year).

    limit: optional cap on saved works, useful for a smoke test.
    reset: delete the existing cache and start again.
    """
    ensure_dirs()
    settings = get_settings()
    years = _year_list(settings.years)
    api_key = os.getenv("OPENALEX_API_KEY", "").strip()

    if reset:
        for old in RAW_DIR.glob("page_*.json"):
            old.unlink()
        if MANIFEST.exists():
            MANIFEST.unlink()
        print("Raw cache cleared.")

    manifest = _load_manifest()
    if manifest and manifest.get("mode") != "year-page":
        raise SystemExit(
            "The raw cache was built by an older crawler version. "
            "Run `python -m crawler.cli fetch --reset` to rebuild it."
        )
    if manifest and manifest.get("years") != years:
        raise SystemExit(
            "The saved cache covers different years. "
            "Run `python -m crawler.cli fetch --reset` to rebuild it."
        )

    if manifest and manifest.get("done"):
        print(f"Cache already complete: {manifest['works_saved']} works in {manifest['pages_saved']} pages.")
        return manifest

    if manifest is None:
        manifest = {
            "mode": "year-page",
            "years": years,
            "year_index": 0,
            "page": 1,
            "pages_saved": 0,
            "works_saved": 0,
            "counts_by_year": {},
            "done": False,
            "started_at": _now(),
        }

    print(f"Polite pool: {'yes' if settings.usable_email else 'NO (set OPENALEX_EMAIL in .env)'}")
    print(f"API key: {'set' if api_key else 'not set (shared anonymous budget)'}")
    print(f"Years: {years}")

    contact = settings.email if settings.usable_email else ""

    with httpx.Client(headers=_headers(contact), timeout=120.0, follow_redirects=True) as client:
        while manifest["year_index"] < len(years):
            year = years[manifest["year_index"]]
            page = manifest["page"]

            print(f"Year {year}, page {page}...", flush=True)
            payload = _request_page(
                client, year, page, settings.per_page, contact, api_key
            )
            results = payload.get("results", [])
            meta = payload.get("meta", {})
            total_for_year = meta.get("count")
            manifest["counts_by_year"][str(year)] = total_for_year

            # Store the page, then update the manifest. A crash at worst
            # re-downloads the current page, never loses a saved page.
            (_page_path(year, page)).write_text(
                json.dumps({"meta": meta, "results": results}, ensure_ascii=False),
                encoding="utf-8",
            )
            manifest["pages_saved"] += 1
            manifest["works_saved"] += len(results)
            manifest["updated_at"] = _now()

            if limit is not None and manifest["works_saved"] >= limit:
                manifest["done"] = True
                manifest["partial"] = True
                _save_manifest(manifest)
                print(f"Stopped at the requested limit of {limit} works.")
                break

            # A short page (or an empty one) means this year is finished.
            if len(results) < settings.per_page:
                print(f"  year {year}: {total_for_year} works reported, finished.")
                manifest["year_index"] += 1
                manifest["page"] = 1
            else:
                manifest["page"] += 1

            _save_manifest(manifest)
            time.sleep(delay)  # stay well below OpenAlex's rate limit

        else:
            manifest["done"] = True
            manifest["partial"] = False
            _save_manifest(manifest)
            print(f"Download complete: {manifest['works_saved']} works.")

    return manifest


def raw_files() -> list[str]:
    """Return the cached page files in download order (used by the cleaner)."""
    return sorted(path.name for path in RAW_DIR.glob("page_*.json"))


def cache_summary() -> dict[str, Any]:
    """Small helper for humans: what is in the cache right now?"""
    manifest = _load_manifest() or {}
    pages = len(list(RAW_DIR.glob("page_*.json")))
    size_mb = sum(p.stat().st_size for p in RAW_DIR.glob("page_*.json")) / (1024 * 1024)
    return {
        "pages": pages,
        "works_saved": manifest.get("works_saved", 0),
        "counts_by_year": manifest.get("counts_by_year", {}),
        "done": manifest.get("done", False),
        "size_mb": round(size_mb, 1),
    }


def clear_cache() -> None:
    """Delete only the crawler cache (never touching cleaned data or results)."""
    for path in RAW_DIR.glob("page_*.json"):
        path.unlink()
    if MANIFEST.exists():
        MANIFEST.unlink()
