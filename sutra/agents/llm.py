"""Ollama LLM client (local, zero cost) — spec 16.1.

Rules:
  * Every LLM request goes to Ollama on localhost (http://localhost:11434).
  * If Ollama is down, Sutra reports "model unavailable" — it does NOT crash
    and does NOT fake output (test scenario 9).
  * `tokens_used` is tracked per execution (for capacity, not billing).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("sutra.llm")

DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"


class ModelUnavailableError(RuntimeError):
    """Raised when the local model cannot be reached or errors out."""


class OllamaClient:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT, model: str = DEFAULT_MODEL,
                 timeout: float = 120.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        """Cheap liveness check (GET /api/tags)."""
        try:
            r = httpx.get(f"{self.endpoint}/api/tags", timeout=3.0)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.2,
             num_predict: int = 1024) -> dict[str, Any]:
        """Run a chat completion. Returns {"text", "tokens_used", "model"}.

        Raises ModelUnavailableError when Ollama is down or the model is
        missing — callers must report "model unavailable", never fabricate.
        """
        if not self.is_available():
            raise ModelUnavailableError(
                f"Ollama not reachable at {self.endpoint} — model unavailable."
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        try:
            r = httpx.post(f"{self.endpoint}/api/chat", json=payload, timeout=self.timeout)
            if r.status_code != 200:
                raise ModelUnavailableError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
        except httpx.HTTPError as exc:
            raise ModelUnavailableError(f"Ollama request failed: {exc}") from exc

        text = data.get("message", {}).get("content", "")
        tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        if not text.strip():
            raise ModelUnavailableError("Model returned an empty response — treating as unavailable.")
        return {"text": text, "tokens_used": int(tokens), "model": self.model}

    def generate(self, system_prompt: str, user_prompt: str, **kw) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.chat(messages, **kw)