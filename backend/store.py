"""Read-only access to the analysis outputs in `data/results/`.

The API never recomputes an analysis: it serves the JSON/CSV files produced by
the scripts in `analysis/`. Files are loaded once and cached, so repeated
requests are cheap. A missing file raises `FileNotFoundError`, which `main.py`
converts into a clear 503 response.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from backend.config import RESULTS_DIR

# Files the API expects. Used by /api/health to show what is available.
EXPECTED_JSON = (
    "stage1_stats",
    "neo4j_verification",
    "p1_fragility",
    "p2_silos_linkprediction",
    "p3_reviewers",
)
EXPECTED_CSV = (
    "p1_critical_authors",
    "p2_top_recommendations",
    "p3_reviewer_assignments",
    "p3_method_comparison",
)


def _as_int(value: str) -> int:
    """CSV numbers are text; return 0 for an empty cell instead of crashing."""
    return int(float(value)) if value not in ("", None) else 0


def _as_float(value: str) -> float:
    """Same idea for floats: an empty cell becomes 0.0."""
    return float(value) if value not in ("", None) else 0.0


class ResultStore:
    """Lazy, cached view of the analysis result files."""

    def __init__(self, results_dir: Path = RESULTS_DIR) -> None:
        self.results_dir = Path(results_dir)
        self._json_cache: dict[str, dict[str, Any]] = {}
        self._assignments: list[dict[str, Any]] | None = None
        self._critical: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------ JSON
    def json(self, name: str) -> dict[str, Any]:
        """Return one result JSON document (cached)."""
        if name not in self._json_cache:
            path = self.results_dir / f"{name}.json"
            if not path.exists():
                raise FileNotFoundError(path.name)
            self._json_cache[name] = json.loads(path.read_text(encoding="utf-8"))
        return self._json_cache[name]

    # ------------------------------------------------------------------- CSV
    def assignments(self) -> list[dict[str, Any]]:
        """Reviewer assignments (Problem 3), typed and cached."""
        if self._assignments is None:
            path = self.results_dir / "p3_reviewer_assignments.csv"
            if not path.exists():
                raise FileNotFoundError(path.name)
            rows: list[dict[str, Any]] = []
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    rows.append(
                        {
                            "paper_id": row["paper_id"],
                            "paper_title": row["paper_title"],
                            "paper_year": _as_int(row["paper_year"]),
                            "reviewer_rank": _as_int(row["reviewer_rank"]),
                            "reviewer_id": row["reviewer_id"],
                            "reviewer_name": row["reviewer_name"],
                            "reviewer_institution": row["reviewer_institution"],
                            "combined_score": _as_float(row["combined_score"]),
                        }
                    )
            self._assignments = rows
        return self._assignments

    def critical_authors(self) -> list[dict[str, Any]]:
        """Critical-author ranking from Problem 1, typed and cached."""
        if self._critical is None:
            path = self.results_dir / "p1_critical_authors.csv"
            if not path.exists():
                raise FileNotFoundError(path.name)
            rows: list[dict[str, Any]] = []
            with path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    rows.append(
                        {
                            "author_id": row["author_id"],
                            "name": row["name"],
                            "institution": row["institution"],
                            "betweenness": _as_float(row["betweenness"]),
                            "pagerank": _as_float(row["pagerank"]),
                            "degree": _as_int(row["degree"]),
                            "strength": _as_int(row["strength"]),
                            "kcore": _as_int(row["kcore"]),
                            "is_articulation": row["is_articulation"].strip().lower() == "true",
                        }
                    )
            self._critical = rows
        return self._critical

    # ---------------------------------------------------------------- status
    def status(self) -> dict[str, bool]:
        """Which expected result files exist (used by /api/health)."""
        status = {
            name: (self.results_dir / f"{name}.json").exists() for name in EXPECTED_JSON
        }
        status.update(
            {name: (self.results_dir / f"{name}.csv").exists() for name in EXPECTED_CSV}
        )
        return status

    def assignment_count(self) -> int:
        """Number of assignment rows, or 0 when the file is absent."""
        try:
            return len(self.assignments())
        except FileNotFoundError:
            return 0
