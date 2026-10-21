"""Runtime AI settings. Defaults come from .env; changes made on the Settings page are stored in SQLite."""
from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.core import metadb

KEYS = ("enabled", "provider", "base_url", "model", "api_key", "temperature", "context_tokens")


def init() -> None:
    metadb.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    metadb.execute("""CREATE TABLE IF NOT EXISTS ai_explanations (
                        doc_id TEXT NOT NULL, model TEXT NOT NULL, created_at REAL, text TEXT, sources TEXT, meta TEXT,
                        PRIMARY KEY (doc_id, model))""")


def _defaults() -> dict[str, Any]:
    s = get_settings()
    return {"enabled": s.ai_enabled, "provider": s.ai_provider,
            "base_url": s.ollama_url if s.ai_provider == "ollama" else s.llm_base_url,
            "model": s.ai_model or s.llm_model, "api_key": s.llm_api_key,
            "temperature": s.ai_temperature, "context_tokens": s.ai_context_tokens}


def get() -> dict[str, Any]:
    out = _defaults()
    for r in metadb.q("SELECT key, value FROM app_settings WHERE key LIKE 'ai.%'"):
        k = r["key"][3:]
        if k in KEYS:
            out[k] = json.loads(r["value"])
    out["base_url"] = (out["base_url"] or "").rstrip("/")
    return out


def update(changes: dict[str, Any]) -> dict[str, Any]:
    with metadb.tx() as c:
        for k, v in changes.items():
            if k in KEYS and v is not None:
                c.execute("INSERT OR REPLACE INTO app_settings(key, value) VALUES (?, ?)", (f"ai.{k}", json.dumps(v)))
    return get()


def public(cfg: dict[str, Any]) -> dict[str, Any]:
    """Settings safe to send to the browser (API key masked)."""
    return {**cfg, "api_key": "****" if cfg.get("api_key") else ""}
