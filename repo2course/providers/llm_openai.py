"""OpenAI provider — STUB.

TODO: implement with the `openai` SDK:
  - __init__: `openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])`
    (support an optional `base_url` extra for OpenAI-compatible servers).
  - _complete: `client.chat.completions.create(model=..., messages=[system?, user],
    temperature=..., response_format={"type": "json_object"} if json_schema else None)`;
    usage from `resp.usage.prompt_tokens` / `completion_tokens`.
  - Map `openai.RateLimitError`, `APITimeoutError`, 5xx to RetryableError.
"""

from __future__ import annotations

from .base import LLMProvider, ProviderError
from .registry import register_llm


@register_llm("openai")
class OpenAILLM(LLMProvider):
    def __init__(self, config, cache=None, usage=None):
        raise ProviderError("The OpenAI provider is a stub; see providers/llm_openai.py.")

    def _complete(self, prompt, system, json_schema):  # pragma: no cover
        raise NotImplementedError
