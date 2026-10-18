"""Orchestrates stages and their on-disk artifacts.

UI-agnostic: progress is reported through an `on_event(stage, message)`
callback, so the CLI renders it with Rich and a future FastAPI layer can
stream it. Every stage reads its inputs from and writes its outputs to
output/<repo-name>/, so any stage can be rerun alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ..cache import ContentCache
from ..config import Config
from ..providers.base import LLMProvider
from ..providers.registry import create_llm
from ..usage import UsageTracker
from .analyze import Analyzer
from .chunking import Digest, build_chunks, summarize_chunks
from .ingest import RepoSnapshot, ingest, repo_name_from_source

EventFn = Callable[[str, str], None]


class Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.snapshot = root / "snapshot.json"
        self.digest = root / "digest.json"
        self.analysis_dir = root / "analysis"
        self.analysis = root / "analysis.json"
        self.curriculum = root / "curriculum.json"
        self.script = root / "script.json"
        self.usage = root / "usage.json"

    @classmethod
    def for_source(cls, config: Config, source: str) -> "Workspace":
        """`source` may be a URL, a local repo path, a repo name, or an output dir."""
        out = config.paths.output_dir
        p = Path(source)
        if p.is_dir() and (p / "snapshot.json").exists():
            return cls(p)
        is_bare_name = "/" not in source and ":" not in source and "\\" not in source
        if is_bare_name and (out / source).is_dir():
            return cls(out / source)
        return cls(out / repo_name_from_source(source))

    def write(self, path: Path, data: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="json")
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    def read(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found — run the earlier stage first.")
        return json.loads(path.read_text())


class Pipeline:
    def __init__(self, config: Config, *, use_cache: bool = True, on_event: EventFn | None = None,
                 llm: LLMProvider | None = None):
        self.config = config
        self.cache = ContentCache(config.paths.cache_dir, enabled=use_cache)
        self.usage = UsageTracker()
        self.on_event = on_event or (lambda stage, msg: None)
        self._llm = llm

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = create_llm(self.config, cache=self.cache, usage=self.usage)
        return self._llm

    def _save_usage(self, ws: Workspace) -> None:
        self.usage.save(ws.usage)

    # ---- stages --------------------------------------------------------------------
    def ingest(self, source: str) -> tuple[Workspace, RepoSnapshot]:
        ws = Workspace.for_source(self.config, source)
        self.on_event("ingest", f"cloning/reading {source}")
        snap = ingest(source, ws.root, self.config.limits,
                      exclude=[self.config.paths.output_dir, self.config.paths.cache_dir])
        ws.write(ws.snapshot, snap)
        self.on_event("ingest", f"{len(snap.tree)} files in tree, {len(snap.files)} read, "
                                f"{snap.skipped_count} skipped, {len(snap.git_log)} commits")
        return ws, snap

    def chunk(self, ws: Workspace, snap: RepoSnapshot) -> Digest:
        budget = self.config.limits.chunk_tokens
        n = len(build_chunks(snap.files, budget))
        self.on_event("chunking", f"summarizing {n} folder chunk(s)")
        with self.usage.stage("chunking"):
            digest = summarize_chunks(snap, self.llm, budget)
        ws.write(ws.digest, digest)
        return digest

    def analyze(self, source: str) -> tuple[Workspace, dict]:
        ws, snap = self.ingest(source)
        try:
            digest = self.chunk(ws, snap)
            analyzer = Analyzer(snap, digest, self.llm, self.config.limits)
            if analyzer.raw_source is None:
                self.on_event("analyze", "source exceeds raw_context_tokens; passes use the digest only")
            for i, name in enumerate(Analyzer.PASSES, 1):
                self.on_event("analyze", f"pass {i}/{len(Analyzer.PASSES)}: {name}")
                with self.usage.stage(f"analyze:{name}"):
                    getattr(analyzer, f"pass_{name}")()
                ws.write(ws.analysis_dir / f"{i:02d}_{name}.json", analyzer.results[name])
            analyzer.results["_grounding"] = analyzer.grounder.issues
            analyzer.results["_meta"] = {"repo": snap.name, "source": snap.source, "commit": snap.commit,
                                         "llm": f"{self.config.llm.provider}/{self.config.llm.model}"}
            ws.write(ws.analysis, analyzer.results)
            return ws, analyzer.results
        finally:
            self._save_usage(ws)
