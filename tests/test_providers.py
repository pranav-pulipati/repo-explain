import json
import wave

import pytest
from pydantic import BaseModel

from repo2course.cache import ContentCache
from repo2course.providers import registry
from repo2course.providers.base import LLMOutputError, RetryableError
from repo2course.providers.registry import UnknownProviderError, create_llm, create_tts
from repo2course.usage import UsageTracker


class Item(BaseModel):
    name: str
    count: int


def test_registry_resolves_by_convention(config):
    llm = create_llm(config)
    tts = create_tts(config)
    assert type(llm).__name__ == "FakeLLM" and llm.name == "fake"
    assert type(tts).__name__ == "FakeTTS" and tts.name == "fake"


def test_registry_lists_providers():
    llms = registry.available("llm")
    assert {"gemini", "ollama", "fake", "anthropic", "openai"} <= set(llms)
    assert {"edge", "piper", "fake", "elevenlabs"} <= set(registry.available("tts"))


def test_unknown_provider_error_lists_available(config):
    config.llm.provider = "nope"
    with pytest.raises(UnknownProviderError, match="Available: .*gemini"):
        create_llm(config)


def test_dotted_path_provider(config):
    config.llm.provider = "repo2course.providers.llm_fake:FakeLLM"
    assert type(create_llm(config)).__name__ == "FakeLLM"


def test_stub_provider_fails_clearly(config):
    config.llm.provider = "anthropic"
    with pytest.raises(Exception, match="stub"):
        create_llm(config)


def test_generate_validates_schema(config):
    llm = create_llm(config, handler=lambda p, s, j: '```json\n{"name": "x", "count": 3}\n```')
    assert llm.generate("hi", json_schema=Item) == {"name": "x", "count": 3}
    assert "JSON Schema" in llm.calls[0]["prompt"]


def test_generate_repairs_once(config):
    replies = iter(['{"name": "x"}', '{"name": "x", "count": 2}'])  # first misses a field
    llm = create_llm(config, handler=lambda p, s, j: next(replies))
    assert llm.generate("hi", json_schema=Item) == {"name": "x", "count": 2}
    assert len(llm.calls) == 2 and "could not be used" in llm.calls[1]["prompt"]


def test_generate_gives_up_after_repair(config):
    llm = create_llm(config, handler=lambda p, s, j: "not json")
    with pytest.raises(LLMOutputError):
        llm.generate("hi", json_schema=Item)
    assert len(llm.calls) == 2


def test_retry_on_retryable_errors(config):
    state = {"n": 0}

    def flaky(p, s, j):
        state["n"] += 1
        if state["n"] < 3:
            raise RetryableError("429", retry_after=0.001)
        return "done"

    llm = create_llm(config, handler=flaky)
    assert llm.generate("hi") == "done" and state["n"] == 3


def test_llm_cache_hit_skips_call(config, tmp_path):
    cache, usage = ContentCache(tmp_path / "c"), UsageTracker()
    llm = create_llm(config, cache=cache, usage=usage, handler=lambda p, s, j: json.dumps({"name": "a", "count": 1}))
    with usage.stage("s1"):
        a = llm.generate("same", json_schema=Item)
        b = llm.generate("same", json_schema=Item)
    assert a == b and len(llm.calls) == 1
    assert usage.stages["s1"].calls == 2 and usage.stages["s1"].cached_calls == 1


def test_default_fake_output_matches_schema(config):
    from repo2course.pipeline.analyze import Architecture
    out = create_llm(config).generate("x", json_schema=Architecture)
    Architecture.model_validate(out)


def test_fake_tts_and_cache(config, tmp_path):
    tts = create_tts(config, cache=ContentCache(tmp_path / "c"))
    p1 = tts.synthesize("one two three four five", tmp_path / "a")
    p2 = tts.synthesize("one two three four five", tmp_path / "b")
    assert p1.suffix == ".wav" and len(tts.calls) == 1
    with wave.open(str(p2)) as w:
        assert abs(w.getnframes() / w.getframerate() - 2.0) < 0.01
