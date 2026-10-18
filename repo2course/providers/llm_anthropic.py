"""Anthropic Claude provider — STUB.

TODO: implement with the `anthropic` SDK:
  - __init__: read key from env `ANTHROPIC_API_KEY` (or `api_key_env` extra),
    create `anthropic.Anthropic(api_key=...)`.
  - _complete: `client.messages.create(model=self.config.model, system=system or "",
    max_tokens=..., temperature=self.config.temperature,
    messages=[{"role": "user", "content": prompt}])`; join text blocks;
    usage from `resp.usage.input_tokens` / `resp.usage.output_tokens`.
  - Map `anthropic.RateLimitError` / `APIStatusError` 429/5xx/529 to RetryableError
    (honour the `retry-after` header).
Then set `llm.provider: anthropic` and `llm.model: claude-sonnet-5-5` in config.yaml.
"""

from __future__ import annotations

from .base import LLMProvider, ProviderError
from .registry import register_llm


@register_llm("anthropic")
class AnthropicLLM(LLMProvider):
    def __init__(self, config, cache=None, usage=None):
        raise ProviderError("The Anthropic provider is a stub; see providers/llm_anthropic.py.")

    def _complete(self, prompt, system, json_schema):  # pragma: no cover
        raise NotImplementedError
