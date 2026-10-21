"""Chat client for a local model server.

* provider "ollama": native Ollama API (/api/chat, /api/tags, /api/pull) - lets us raise the context window (num_ctx),
  which matters for retrieval-augmented prompts (Ollama's default context is small).
* provider "openai": any OpenAI-compatible server (/v1/chat/completions), e.g. LM Studio, llama.cpp server, vLLM.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator

import httpx

from app.config import get_settings
from app.llm import settings as ai_settings


class LLMError(RuntimeError):
    pass


def _cfg() -> dict[str, Any]:
    return ai_settings.get()


def _openai_base(url: str) -> str:
    return url if url.rstrip("/").endswith("/v1") else url.rstrip("/") + "/v1"


def _ollama_root(url: str) -> str:
    return url[:-3] if url.rstrip("/").endswith("/v1") else url


def list_models(cfg: dict | None = None, timeout: float = 3.0) -> list[dict]:
    cfg = cfg or _cfg()
    try:
        if cfg["provider"] == "ollama":
            r = httpx.get(_ollama_root(cfg["base_url"]) + "/api/tags", timeout=timeout)
            r.raise_for_status()
            return [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                     "parameters": (m.get("details") or {}).get("parameter_size"), "family": (m.get("details") or {}).get("family")}
                    for m in r.json().get("models", [])]
        headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
        r = httpx.get(_openai_base(cfg["base_url"]) + "/models", headers=headers, timeout=timeout)
        r.raise_for_status()
        return [{"name": m["id"]} for m in r.json().get("data", [])]
    except Exception as e:  # noqa: BLE001 - surfaced to the UI as "not reachable"
        raise LLMError(f"Model server not reachable at {cfg['base_url']} ({type(e).__name__})") from e


def status() -> dict[str, Any]:
    cfg = _cfg()
    out = {"settings": ai_settings.public(cfg), "enabled": cfg["enabled"], "reachable": False, "models": [], "model_available": False, "error": None}
    try:
        out["models"] = list_models(cfg)
        out["reachable"] = True
        names = {m["name"].lower() for m in out["models"]}
        out["model_available"] = cfg["model"].lower() in names or (cfg["provider"] == "ollama" and f"{cfg['model'].lower()}:latest" in names)
        if not out["model_available"]:
            out["error"] = f"Model '{cfg['model']}' is not installed on the server. Choose another model or download it on the Settings page."
    except LLMError as e:
        out["error"] = str(e)
    out["ready"] = bool(out["enabled"] and out["reachable"] and out["model_available"])
    return out


def chat(messages: list[dict], *, json_mode: bool = False, temperature: float | None = None, max_tokens: int | None = None) -> str:
    """Single (non-streaming) completion."""
    return "".join(stream_chat(messages, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens))


def stream_chat(messages: list[dict], *, json_mode: bool = False, temperature: float | None = None, max_tokens: int | None = None) -> Iterator[str]:
    cfg = _cfg()
    if not cfg["enabled"]:
        raise LLMError("Local AI is switched off (Settings > Local AI).")
    temp = cfg["temperature"] if temperature is None else temperature
    timeout = httpx.Timeout(get_settings().ai_timeout_s, connect=5.0)
    try:
        if cfg["provider"] == "ollama":
            body: dict[str, Any] = {"model": cfg["model"], "messages": messages, "stream": True, "keep_alive": "15m",
                                    "options": {"temperature": temp, "num_ctx": int(cfg["context_tokens"])}}
            if max_tokens:
                body["options"]["num_predict"] = max_tokens
            if json_mode:
                body["format"] = "json"
            with httpx.stream("POST", _ollama_root(cfg["base_url"]) + "/api/chat", json=body, timeout=timeout) as r:
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(f"Model server error {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    j = json.loads(line)
                    if j.get("error"):
                        raise LLMError(j["error"])
                    piece = (j.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if j.get("done"):
                        break
        else:
            headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
            body = {"model": cfg["model"], "messages": messages, "stream": True, "temperature": temp}
            if max_tokens:
                body["max_tokens"] = max_tokens
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            with httpx.stream("POST", _openai_base(cfg["base_url"]) + "/chat/completions", json=body, headers=headers, timeout=timeout) as r:
                if r.status_code >= 400:
                    r.read()
                    raise LLMError(f"Model server error {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    j = json.loads(data)
                    delta = (j.get("choices") or [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
    except httpx.HTTPError as e:
        raise LLMError(f"Could not reach the model server at {cfg['base_url']}: {type(e).__name__}") from e


def pull(model: str) -> Iterator[dict]:
    """Download a model through Ollama, yielding progress events."""
    cfg = _cfg()
    if cfg["provider"] != "ollama":
        raise LLMError("Downloading models is only available for Ollama.")
    with httpx.stream("POST", _ollama_root(cfg["base_url"]) + "/api/pull", json={"model": model, "stream": True},
                      timeout=httpx.Timeout(None, connect=5.0)) as r:
        if r.status_code >= 400:
            r.read()
            raise LLMError(f"Pull failed {r.status_code}: {r.text[:300]}")
        for line in r.iter_lines():
            if line:
                yield json.loads(line)


def test() -> dict[str, Any]:
    t0 = time.time()
    text = chat([{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=8, temperature=0)
    return {"reply": text.strip()[:60], "latency_ms": round((time.time() - t0) * 1000)}
