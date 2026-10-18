"""Provider registry: config name -> implementation class.

Resolution order for `llm.provider: <name>` (same for tts):
  1. a class already registered under that name;
  2. convention: import `repo2course.providers.llm_<name>` (which registers itself);
  3. dotted path `some.module:ClassName` for providers living outside this package.

So adding a provider is: drop `providers/llm_<name>.py` with
`@register_llm("<name>")` on the class, then set `provider: <name>` in config.yaml.
Pipeline code only ever calls `create_llm` / `create_tts`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable, TypeVar

from ..cache import ContentCache
from ..config import Config
from ..usage import UsageTracker
from .base import LLMProvider, ProviderError, TTSProvider

_LLM: dict[str, type[LLMProvider]] = {}
_TTS: dict[str, type[TTSProvider]] = {}

L = TypeVar("L", bound=type[LLMProvider])
S = TypeVar("S", bound=type[TTSProvider])


def register_llm(name: str) -> Callable[[L], L]:
    def deco(cls: L) -> L:
        cls.name = name
        _LLM[name] = cls
        return cls
    return deco


def register_tts(name: str) -> Callable[[S], S]:
    def deco(cls: S) -> S:
        cls.name = name
        _TTS[name] = cls
        return cls
    return deco


class UnknownProviderError(ProviderError):
    pass


def _resolve(kind: str, name: str, table: dict) -> type:
    if name in table:
        return table[name]
    if ":" in name:
        mod_name, _, cls_name = name.partition(":")
        cls = getattr(importlib.import_module(mod_name), cls_name)
        table[name] = cls
        return cls
    mod_name = f"{__package__}.{kind}_{name}"
    try:
        importlib.import_module(mod_name)
    except ModuleNotFoundError as e:
        if e.name == mod_name:
            raise UnknownProviderError(
                f"Unknown {kind.upper()} provider '{name}'. Available: {', '.join(available(kind))}"
            ) from None
        raise ProviderError(
            f"{kind.upper()} provider '{name}' needs the Python package '{e.name}'. "
            f"Install it, e.g. `uv pip install {e.name}`."
        ) from e
    if name not in table:
        raise UnknownProviderError(f"{mod_name} did not register a provider named '{name}'")
    return table[name]


def available(kind: str) -> list[str]:
    """Provider names discoverable by convention (files named <kind>_<name>.py)."""
    here = Path(__file__).parent
    return sorted(p.stem[len(kind) + 1:] for p in here.glob(f"{kind}_*.py"))


def get_llm_class(name: str) -> type[LLMProvider]:
    return _resolve("llm", name, _LLM)


def get_tts_class(name: str) -> type[TTSProvider]:
    return _resolve("tts", name, _TTS)


def create_llm(config: Config, cache: ContentCache | None = None, usage: UsageTracker | None = None,
               **kwargs) -> LLMProvider:
    return get_llm_class(config.llm.provider)(config.llm, cache=cache, usage=usage, **kwargs)


def create_tts(config: Config, cache: ContentCache | None = None, usage: UsageTracker | None = None,
               **kwargs) -> TTSProvider:
    return get_tts_class(config.tts.provider)(config.tts, cache=cache, usage=usage, **kwargs)
