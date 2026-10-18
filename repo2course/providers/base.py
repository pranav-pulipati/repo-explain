"""Abstract provider interfaces.

Vendor modules implement only the raw call (`_complete` / `_synthesize`).
Everything cross-cutting lives here, once: content-hash caching, retries
with backoff for rate limits, a concurrency cap, usage accounting, JSON
parsing, schema validation and the one-shot LLM repair retry.
"""

from __future__ import annotations

import json
import logging
import random
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ClassVar, TypeVar

from pydantic import BaseModel, ValidationError

from ..cache import ContentCache, content_hash
from ..config import LLMConfig, RetryConfig, TTSConfig
from ..jsonrepair import JSONParseError, parse_json
from ..usage import UsageTracker

log = logging.getLogger(__name__)

T = TypeVar("T")


class ProviderError(RuntimeError):
    """Non-retryable provider failure (bad key, unknown model, ...)."""


class RetryableError(ProviderError):
    """Transient failure (rate limit, 5xx, timeout). `retry_after` in seconds if known."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LLMOutputError(ProviderError):
    """The model's output could not be parsed/validated even after a repair retry."""


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


def _with_retry(fn: Callable[[], T], retry: RetryConfig, is_retryable: Callable[[BaseException], bool],
                what: str) -> T:
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            if attempt >= retry.attempts or not is_retryable(exc):
                raise
            hint = getattr(exc, "retry_after", None)
            delay = hint if hint else retry.backoff_seconds * (2 ** (attempt - 1))
            delay = min(delay, retry.max_backoff_seconds) * (1 + random.uniform(0, 0.25))
            log.warning("%s failed (%s); retry %d/%d in %.1fs", what, exc, attempt, retry.attempts - 1, delay)
            time.sleep(delay)


def _schema_dict(json_schema: dict | type[BaseModel] | None) -> dict | None:
    if json_schema is None:
        return None
    if isinstance(json_schema, type) and issubclass(json_schema, BaseModel):
        return _strip_titles(json_schema.model_json_schema())
    return json_schema


def _strip_titles(node: Any) -> Any:
    """Pydantic adds a `title` to every field; it's noise in a prompt."""
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items()
                if not (k == "title" and isinstance(v, str))}
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


JSON_INSTRUCTIONS = """

---
Respond with ONLY a single JSON value that conforms to this JSON Schema. No prose, no markdown fences.
JSON Schema:
{schema}"""

REPAIR_PROMPT = """Your previous response could not be used.
Problem: {error}

Return the corrected response as ONLY valid JSON conforming to this JSON Schema (no prose, no fences):
{schema}

Previous response:
{previous}"""


class LLMProvider(ABC):
    name: ClassVar[str] = "base"
    # True if `_complete` enforces `json_schema` itself (then we don't paste
    # the schema into the prompt).
    native_json_schema: ClassVar[bool] = False

    def __init__(self, config: LLMConfig, cache: ContentCache | None = None,
                 usage: UsageTracker | None = None):
        self.config = config
        self.cache = cache
        self.usage = usage or UsageTracker()
        self._sem = threading.Semaphore(max(1, config.max_concurrency))

    # ---- implemented by vendors -------------------------------------------
    @abstractmethod
    def _complete(self, prompt: str, system: str | None, json_schema: dict | None) -> LLMResult:
        """One raw model call. Raise RetryableError for transient failures."""

    def is_retryable(self, exc: BaseException) -> bool:
        return isinstance(exc, (RetryableError, TimeoutError, ConnectionError))

    # ---- public API ---------------------------------------------------------
    def generate(self, prompt: str, system: str | None = None,
                 json_schema: dict | type[BaseModel] | None = None, *, use_cache: bool = True) -> str | dict:
        """Generate text, or JSON when `json_schema` is given.

        `json_schema` may be a JSON-schema dict or a pydantic model class; with
        a model class the result is validated and returned as a plain dict.
        """
        schema = _schema_dict(json_schema)
        model_cls = json_schema if isinstance(json_schema, type) else None
        key = content_hash("llm-v1", self.name, self.config.model, self.config.temperature,
                           system or "", prompt, schema or "")
        if use_cache and self.cache:
            hit = self.cache.get_json("llm", key)
            if hit is not None:
                self.usage.record_llm(cached=True)
                return hit["value"]

        full_prompt = prompt
        if schema is not None and not self.native_json_schema:
            full_prompt += JSON_INSTRUCTIONS.format(schema=json.dumps(schema, separators=(",", ":")))

        result = self._call(full_prompt, system, schema)
        if schema is None:
            value: Any = result.text
        else:
            try:
                value = self._parse_and_validate(result.text, model_cls)
            except (JSONParseError, ValidationError) as err:
                log.info("JSON invalid (%s); asking model to repair", _short(err))
                repair = REPAIR_PROMPT.format(error=_short(err, 1500),
                                              schema=json.dumps(schema, separators=(",", ":")),
                                              previous=result.text[-20000:])
                result2 = self._call(repair, system, schema)
                try:
                    value = self._parse_and_validate(result2.text, model_cls)
                except (JSONParseError, ValidationError) as err2:
                    raise LLMOutputError(f"{self.name}: invalid JSON after repair retry: {_short(err2)}") from err2

        if use_cache and self.cache:
            self.cache.set_json("llm", key, {"value": value, "model": self.config.model})
        return value

    # ---- internals ------------------------------------------------------------
    def _call(self, prompt: str, system: str | None, schema: dict | None) -> LLMResult:
        def once() -> LLMResult:
            with self._sem:
                return self._complete(prompt, system, schema)

        res = _with_retry(once, self.config.retry, self.is_retryable, f"{self.name} LLM call")
        self.usage.record_llm(res.input_tokens, res.output_tokens)
        return res

    @staticmethod
    def _parse_and_validate(text: str, model_cls: type[BaseModel] | None) -> Any:
        data = parse_json(text)
        if model_cls is not None:
            # Models sometimes wrap a single object in a list.
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                data = data[0]
            return model_cls.model_validate(data).model_dump(mode="json")
        return data


def _short(err: BaseException, limit: int = 600) -> str:
    s = str(err)
    return s if len(s) <= limit else s[:limit] + "..."


class TTSProvider(ABC):
    name: ClassVar[str] = "base"
    # Longest text the engine accepts reliably in one request; audio.py splits above it.
    max_chars: ClassVar[int] = 3000
    output_suffix: ClassVar[str] = ".mp3"

    def __init__(self, config: TTSConfig, cache: ContentCache | None = None,
                 usage: UsageTracker | None = None):
        self.config = config
        self.cache = cache
        self.usage = usage or UsageTracker()
        self._sem = threading.Semaphore(max(1, config.max_concurrency))

    @abstractmethod
    def _synthesize(self, text: str, out_path: Path) -> Path:
        """Write audio for `text` to `out_path` (suffix = output_suffix)."""

    def voice_identity(self) -> dict:
        """Everything that changes the produced audio; part of the cache key."""
        return {"voice": self.config.voice, "rate": self.config.rate, **(self.config.model_extra or {})}

    def is_retryable(self, exc: BaseException) -> bool:
        return isinstance(exc, (RetryableError, TimeoutError, ConnectionError))

    def synthesize(self, text: str, out_path: str | Path) -> Path:
        out_path = Path(out_path).with_suffix(self.output_suffix)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        key = content_hash("tts-v1", self.name, self.voice_identity(), text)
        if self.cache:
            hit = self.cache.get_file("tts", key, self.output_suffix)
            if hit:
                out_path.write_bytes(hit.read_bytes())
                self.usage.record_tts(len(text), cached=True)
                return out_path

        def once() -> Path:
            with self._sem, tempfile.TemporaryDirectory() as td:
                tmp = Path(td) / f"tts{self.output_suffix}"
                self._synthesize(text, tmp)
                if not tmp.exists() or tmp.stat().st_size == 0:
                    raise RetryableError(f"{self.name} produced no audio")
                out_path.write_bytes(tmp.read_bytes())
                return out_path

        _with_retry(once, self.config.retry, self.is_retryable, f"{self.name} TTS")
        self.usage.record_tts(len(text))
        if self.cache:
            self.cache.put_file("tts", key, out_path)
        return out_path
