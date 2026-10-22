"""Command line wrapper for the three analysis stages.

The scripts can always be run directly (``python -m analysis.p1_fragility``);
this module adds the installed ``rn-analysis`` command used by ``run_all``:

Usage:
  python -m analysis.cli p1 [--skip-null]
  python -m analysis.cli p2
  python -m analysis.cli p3
  python -m analysis.cli all [--skip-null]

Requirements:
  * p1 and p2 need Neo4j + GDS running and the Stage 2 projections loaded.
  * p3 reads only the submitted CSV files.
"""

from __future__ import annotations

import argparse

from analysis.p1_fragility import main as run_p1
from analysis.p2_silos_linkpred import main as run_p2
from analysis.p3_reviewers import main as run_p3


def main() -> None:
    """Parse the stage name and call the matching analysis entry point."""
    parser = argparse.ArgumentParser(description="Run the Problem 1-3 analyses")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("p1", help="Problem 1: fragility and critical authors")
    p1.add_argument("--skip-null", action="store_true", help="skip the rewiring null model")

    sub.add_parser("p2", help="Problem 2: silos and collaboration prediction")
    sub.add_parser("p3", help="Problem 3: reviewer assignment")

    all_stages = sub.add_parser("all", help="run p1, then p2, then p3")
    all_stages.add_argument(
        "--skip-null", action="store_true", help="skip the p1 rewiring null model"
    )

    args = parser.parse_args()

    if args.command in ("p1", "all"):
        run_p1(["--skip-null"] if args.skip_null else [])

    if args.command in ("p2", "all"):
        run_p2()

    if args.command in ("p3", "all"):
        run_p3()


if __name__ == "__main__":
    main()
