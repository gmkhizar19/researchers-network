"""Backend settings.

Every value comes from the environment or from the untracked `.env` file.
Nothing secret is written in the source code: the password default is empty and
the real value is supplied by `NEO4J_PASSWORD` at run time.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "data" / "results"


class Settings(BaseSettings):
    """Application settings, read case-insensitively from env / `.env`."""

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # crawler variables (OPENALEX_*) are irrelevant here
    )

    # Neo4j connection (no credentials in code).
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    # React dev server origin(s), comma-separated.
    cors_origins: str = "http://localhost:5173"

    # Folder with the analysis outputs.
    results_dir: Path = RESULTS_DIR

    @property
    def allowed_origins(self) -> list[str]:
        """CORS origins as a clean list (empty entries ignored)."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
