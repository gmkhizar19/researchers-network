"""Consistent Matplotlib settings for every figure in the report.

Using the non-interactive Agg backend means figures can be generated on a
headless machine (and inside CI) without opening a window.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)

from crawler.config import FIGURES_DIR  # noqa: E402

# A small, colour-blind-friendly palette used across all figures.
BLUE = "#2563eb"
ORANGE = "#ea580c"
GREEN = "#16a34a"
RED = "#dc2626"
GREY = "#6b7280"
PURPLE = "#7c3aed"

plt.rcParams.update(
    {
        "figure.dpi": 110,
        "savefig.dpi": 170,
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "legend.frameon": False,
    }
)


def save(fig, filename: str, tight: bool = True) -> Path:
    """Save a figure to report/figures and close it (prevents memory leaks)."""
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / filename
    fig.savefig(path, bbox_inches="tight" if tight else None, facecolor="white")
    plt.close(fig)
    return path
