"""Shared configuration: paths, environment variables and the OpenAlex scope.

Every script imports paths from here so that the project can be moved without
editing hard-coded strings. Secrets (and the user's email) come only from .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Repository root = the folder that contains crawler/, analysis/, data/ ...
ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
IMPORT_DIR = DATA_DIR / "import"
RESULTS_DIR = DATA_DIR / "results"
GRAPHML_DIR = CLEANED_DIR / "graphml"
FIGURES_DIR = ROOT / "report" / "figures"
SCREENSHOTS_DIR = ROOT / "report" / "screenshots"

# .env is optional: the project must still run with plain environment variables.
load_dotenv(ROOT / ".env")

# --- OpenAlex scope ---------------------------------------------------------
# Computer Science = OpenAlex field 17. We keep the main scholarly types and
# exclude preprints so that a preprint and its published version do not create
# duplicate collaboration edges.
FIELD_ID = "fields/17"
WORK_TYPES = ("article", "proceedings-article", "review", "book-chapter")
MAX_AUTHORS_PER_PAPER = 30  # larger author lists are consortium papers; see build_graph

# Fields we ask OpenAlex for. `select` keeps the raw cache small.
WORK_SELECT = (
    "id,doi,title,publication_year,publication_date,type,cited_by_count,"
    "authorships,primary_topic,topics,referenced_works"
)


@dataclass(frozen=True)
class Settings:
    """Values that may change between machines or runs."""

    email: str
    years: str
    per_page: int

    @property
    def usable_email(self) -> bool:
        """True when a real contact address was configured (not the placeholder)."""
        email = self.email.strip().lower()
        if not email or "@" not in email:
            return False
        return not (email.startswith("you@") or email.endswith("example.com"))


def get_settings() -> Settings:
    """Read settings from the environment, with safe defaults."""
    email = os.getenv("OPENALEX_EMAIL", "").strip()
    years = os.getenv("OPENALEX_YEARS", "2015-2025").strip()
    per_page = int(os.getenv("OPENALEX_PER_PAGE", "200"))
    # OpenAlex accepts at most 200 works per page.
    per_page = max(1, min(per_page, 200))
    return Settings(email=email, years=years, per_page=per_page)


def openalex_filter(years: str | None = None) -> str:
    """Build the OpenAlex filter string for the project scope.

    Example output:
      institutions.country_code:PK,primary_topic.field.id:fields/17,
      publication_year:2015-2025,type:article|proceedings-article|...
    """
    years = years or get_settings().years
    types = "|".join(WORK_TYPES)
    return (
        f"institutions.country_code:PK,"
        f"primary_topic.field.id:{FIELD_ID},"
        f"publication_year:{years},"
        f"type:{types}"
    )


def ensure_dirs() -> None:
    """Create every output folder once, so scripts never fail on a missing dir."""
    for path in (
        RAW_DIR,
        CLEANED_DIR,
        IMPORT_DIR,
        RESULTS_DIR,
        GRAPHML_DIR,
        FIGURES_DIR,
        SCREENSHOTS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
