"""Ollama (fully local) via its HTTP API.

config.yaml:
  llm: {provider: ollama, model: qwen2.5-coder:14b}
  # optional: host (default $OLLAMA_HOST or http://localhost:11434), num_ctx (default 32768)
Use a model with a large context window; analysis prompts are big.
"""

from __future__ import annotations

import os

import httpx

from .base import LLMProvider, LLMResult, ProviderError, RetryableError
from .registry import register_llm


@register_llm("ollama")
class OllamaLLM(LLMProvider):
    def __init__(self, config, cache=None, usage=None):
        super().__init__(config, cache, usage)
        self.host = config.extra("host") or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        if not self.host.startswith("http"):
            self.host = "http://" + self.host
        self.client = httpx.Client(base_url=self.host, timeout=config.timeout_seconds)

    def _complete(self, prompt, system, json_schema):
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}]
        body = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.config.temperature,
                        "num_ctx": int(self.config.extra("num_ctx", 32768))},
        }
        if json_schema:
            body["format"] = json_schema  # constrained decoding
        try:
            r = self.client.post("/api/chat", json=body)
        except httpx.ConnectError as e:
            raise ProviderError(f"Cannot reach Ollama at {self.host}. Is `ollama serve` running?") from e
        except httpx.TimeoutException as e:
            raise RetryableError(f"Ollama timeout: {e}") from e
        if r.status_code >= 500:
            raise RetryableError(f"Ollama {r.status_code}: {r.text[:300]}")
        if r.status_code != 200:
            raise ProviderError(f"Ollama {r.status_code}: {r.text[:300]}")
        data = r.json()
        return LLMResult(text=data.get("message", {}).get("content", ""),
                         input_tokens=data.get("prompt_eval_count", 0),
                         output_tokens=data.get("eval_count", 0))
