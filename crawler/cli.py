"""Command line entry point for the data stage.

Usage:
  python -m crawler.cli fetch [--limit N] [--reset]
  python -m crawler.cli clean
  python -m crawler.cli build
  python -m crawler.cli all
  python -m crawler.cli status
"""

from __future__ import annotations

import argparse
import sys

from crawler.build_graph import build_graph
from crawler.clean import clean_dataset, write_cleaning_report
from crawler.fetch_openalex import cache_summary, fetch_all
from crawler.validate import print_validation, validate


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAlex crawler and graph builder")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="download works from OpenAlex (resumable)")
    fetch.add_argument("--limit", type=int, default=None, help="stop after N works (smoke test)")
    fetch.add_argument("--reset", action="store_true", help="delete the raw cache first")

    sub.add_parser("clean", help="turn raw JSON into clean CSV node/edge tables")
    sub.add_parser("build", help="build the author collaboration graph and GraphML")
    sub.add_parser("all", help="fetch + clean + build")
    sub.add_parser("status", help="show what is currently cached")
    sub.add_parser("validate", help="check the dataset against the grading requirements")

    args = parser.parse_args()

    if args.command == "status":
        print(cache_summary())
        return

    if args.command in ("fetch", "all"):
        fetch_all(limit=getattr(args, "limit", None), reset=getattr(args, "reset", False))

    if args.command in ("clean", "all"):
        summary = clean_dataset()
        write_cleaning_report(summary)
        print(
            "Cleaned: "
            f"{summary['nodes']['authors']} authors, {summary['nodes']['papers']} papers, "
            f"{summary['edges']['wrote']} WROTE edges."
        )

    if args.command in ("build", "all"):
        stats = build_graph()
        print(
            "Graph: "
            f"{stats['nodes']['authors_collaborating']} collaborating authors, "
            f"{stats['edges']['coauthor_edges']} edges, "
            f"LCC {stats['connectivity']['lcc_pct_of_collaborating']}%."
        )

    if args.command == "validate":
        print_validation(validate())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted.")
