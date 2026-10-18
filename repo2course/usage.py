"""Per-stage token/char usage accounting."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from pathlib import Path

_current_stage: ContextVar[str] = ContextVar("repo2course_stage", default="unscoped")


@dataclass
class StageUsage:
    calls: int = 0
    cached_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tts_chars: int = 0


@dataclass
class UsageTracker:
    stages: dict[str, StageUsage] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @contextmanager
    def stage(self, name: str):
        token = _current_stage.set(name)
        try:
            yield
        finally:
            _current_stage.reset(token)

    @staticmethod
    def current_stage() -> str:
        return _current_stage.get()

    def record_llm(self, input_tokens: int = 0, output_tokens: int = 0, cached: bool = False,
                   stage: str | None = None) -> None:
        with self._lock:
            s = self.stages.setdefault(stage or self.current_stage(), StageUsage())
            s.calls += 1
            s.cached_calls += int(cached)
            s.input_tokens += input_tokens
            s.output_tokens += output_tokens

    def record_tts(self, chars: int, cached: bool = False, stage: str | None = None) -> None:
        with self._lock:
            s = self.stages.setdefault(stage or self.current_stage(), StageUsage())
            s.calls += 1
            s.cached_calls += int(cached)
            s.tts_chars += 0 if cached else chars

    def totals(self) -> StageUsage:
        t = StageUsage()
        for s in self.stages.values():
            for k, v in asdict(s).items():
                setattr(t, k, getattr(t, k) + v)
        return t

    def to_dict(self) -> dict:
        return {"stages": {k: asdict(v) for k, v in self.stages.items()}, "total": asdict(self.totals())}

    def save(self, path: Path) -> None:
        """Merge into an existing usage file so separate stage commands accumulate."""
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text()).get("stages", {})
            except json.JSONDecodeError:
                existing = {}
        existing.update({k: asdict(v) for k, v in self.stages.items()})
        merged = UsageTracker(stages={k: StageUsage(**v) for k, v in existing.items()})
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(merged.to_dict(), indent=2))
