"""Central configuration. Values come from environment variables or the project-root .env file."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Neo4j -------------------------------------------------------------
    neo4j_uri: str = "neo4j://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "ctpip"
    # Optional least-privilege account used for every query-time read. If empty the
    # admin account is used, but always through read-only transactions.
    neo4j_read_user: str = ""
    neo4j_read_password: str = ""
    query_timeout_s: float = 15.0
    query_result_limit: int = 400

    # --- Storage -------------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    # Folder that the "import dataset folder" action reads from (server-side only).
    import_dir: Path = PROJECT_ROOT
    max_upload_mb: int = 200

    # --- Ingestion -------------------------------------------------------------
    ingest_workers: int = 4
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 40
    table_detection: bool = True

    # --- Model providers (optional; core features never need them) ----------------
    # "rules" (default, deterministic) or "openai_compatible" (e.g. a local Ollama server)
    extraction_provider: str = "rules"
    # "none" (deterministic evidence summary) or "openai_compatible"
    answer_provider: str = "none"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_model: str = ""
    llm_api_key: str = ""

    # --- Local AI assistant (explanations, protocol study, RAG chat, agent) ----------
    # Defaults only; the Settings page stores overrides in the metadata database.
    ai_enabled: bool = True
    ai_provider: str = "ollama"               # "ollama" (native API) or "openai" (any OpenAI-compatible server)
    ollama_url: str = "http://127.0.0.1:11434"
    ai_model: str = "qwen2.5:3b"              # 4 GB GPUs; qwen2.5:7b / llama3.1:8b give richer answers on bigger GPUs
    ai_temperature: float = 0.2
    ai_context_tokens: int = 8192
    ai_timeout_s: float = 240.0

    # --- First start on a new computer --------------------------------------------------
    # When the document store is empty, queue every dataset PDF found under IMPORT_DIR automatically.
    auto_import_on_empty: bool = True

    # --- Server ------------------------------------------------------------------
    api_token: str = ""  # if set, every /api request needs header "X-API-Token"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"])

    @property
    def pdf_dir(self) -> Path:
        return self.data_dir / "pdfs"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def sqlite_path(self) -> Path:
        return self.data_dir / "ctpip.sqlite3"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    for p in (s.data_dir, s.pdf_dir, s.artifact_dir):
        p.mkdir(parents=True, exist_ok=True)
    return s
