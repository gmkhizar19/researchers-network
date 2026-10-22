"""FastAPI backend for Pakistan's Researchers Network.

The API is a thin, read-only layer: analyses are computed once by the scripts
in `analysis/`, stored in `data/results/`, and served here (plus live graph
queries against Neo4j). No number is calculated on the fly.
"""

__version__ = "0.1.0"
