"""Google Gemini via the google-genai SDK (free tier friendly).

config.yaml:
  llm: {provider: gemini, model: gemini-2.5-flash}
  # optional: api_key_env (default GEMINI_API_KEY, falls back to GOOGLE_API_KEY),
  #           max_output_tokens, thinking_budget
"""

from __future__ import annotations

import os
import re

from google import genai
from google.genai import errors, types

from .base import LLMProvider, LLMResult, ProviderError, RetryableError
from .registry import register_llm

_RETRY_DELAY_RE = re.compile(r"retryDelay['\"]?\s*:\s*['\"]?(\d+(?:\.\d+)?)s")


@register_llm("gemini")
class GeminiLLM(LLMProvider):
    def __init__(self, config, cache=None, usage=None):
        super().__init__(config, cache, usage)
        env = config.extra("api_key_env", "GEMINI_API_KEY")
        key = os.environ.get(env) or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise ProviderError(
                f"Gemini API key not found. Set {env} in .env (free key: https://aistudio.google.com/apikey)."
            )
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=int(config.timeout_seconds * 1000)))

    def _complete(self, prompt, system, json_schema):
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.config.temperature,
            max_output_tokens=self.config.extra("max_output_tokens", 65536),
            response_mime_type="application/json" if json_schema else None,
        )
        budget = self.config.extra("thinking_budget")
        if budget is not None:
            cfg.thinking_config = types.ThinkingConfig(thinking_budget=int(budget))
        try:
            resp = self.client.models.generate_content(model=self.config.model, contents=prompt, config=cfg)
        except errors.APIError as e:
            if e.code in (408, 429, 500, 502, 503, 504):
                m = _RETRY_DELAY_RE.search(str(e))
                raise RetryableError(f"Gemini {e.code}: {e.message}",
                                     retry_after=float(m.group(1)) + 1 if m else None) from e
            raise ProviderError(f"Gemini {e.code}: {e.message}") from e

        text = resp.text or ""
        if not text:
            reason = resp.candidates[0].finish_reason if resp.candidates else "no candidates"
            raise RetryableError(f"Gemini returned empty text (finish_reason={reason})")
        um = resp.usage_metadata
        out_tokens = (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)
        return LLMResult(text=text, input_tokens=getattr(um, "prompt_token_count", 0) or 0,
                         output_tokens=out_tokens)
