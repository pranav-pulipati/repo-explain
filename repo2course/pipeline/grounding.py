"""Grounding checks: keep the analysis honest against the real checkout.

- Paths that don't exist are dropped (and logged in `_grounding`).
- Symbols referenced in code refs are located in the real file; line ranges
  are snapped to the definition when the model's numbers are off.
- Refs whose symbol can't be found are marked uncertain.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from .ingest import RepoSnapshot


class Grounder:
    def __init__(self, snapshot: RepoSnapshot):
        self.snapshot = snapshot
        self.repo_dir = Path(snapshot.repo_dir)
        self.issues: list[str] = []
        self._paths = {e.path for e in snapshot.tree}

    def normalize(self, path: str | None) -> str | None:
        if not path:
            return None
        p = path.strip().strip("`").removeprefix("./").strip("/")
        if p in self._paths or self.snapshot.has_path(p):
            return p
        # Tolerate a leading repo-name segment ("myrepo/src/x.py").
        tail = p.split("/", 1)[1] if "/" in p else None
        if tail and (tail in self._paths or self.snapshot.has_path(tail)):
            return tail
        return None

    def filter_paths(self, paths: list[str], where: str) -> list[str]:
        out = []
        for p in paths:
            n = self.normalize(p)
            if n:
                if n not in out:
                    out.append(n)
            else:
                self.issues.append(f"{where}: dropped unknown path '{p}'")
        return out

    @lru_cache(maxsize=512)
    def lines(self, path: str) -> tuple[str, ...]:
        try:
            text = (self.repo_dir / path).read_text(errors="replace")
            return tuple(text.removesuffix("\n").split("\n"))
        except (OSError, IsADirectoryError):
            return ()

    def find_symbol(self, path: str, symbol: str) -> int | None:
        """1-based line of the symbol's definition (or first mention) in `path`."""
        name = symbol.split(".")[-1].split("(")[0].strip()
        if not name:
            return None
        lines = self.lines(path)
        word = re.escape(name)
        patterns = [
            # Keyword definitions (Python, JS/TS, Go, Rust, Ruby, Kotlin, Swift, ...)
            rf"\b(def|class|function\*?|func|fn|fun|const|let|var|type|interface|struct|enum|trait|impl|module|"
            rf"object|record)\s+(\([^)]*\)\s*)?{word}\b",
            # JS/TS assignments and object/class members: `name = (...) =>`, `name: function`, `async name(`
            rf"\b{word}\s*[:=]\s*(async\s+)?(function\b|\([^)]*\)\s*=>|[A-Za-z_]\w*\s*=>)",
            rf"^\s*(async\s+|static\s+|get\s+|set\s+)*{word}\s*\([^)]*\)\s*\{{",
            # C-family method signatures: `public Foo bar(` (no trailing `;`)
            rf"^\s*(?:[\w<>\[\],.*&]+\s+)+\**{word}\s*\([^;]*$",
            rf"\b{word}\b",  # any mention
        ]
        for pat in patterns:
            rx = re.compile(pat)
            for i, line in enumerate(lines, 1):
                if rx.search(line) and not line.lstrip().startswith(("return ", "#", "//")):
                    return i
        return None

    def ground_ref(self, ref: dict, where: str, span_default: int = 12, max_span: int = 40) -> dict | None:
        """Validate/repair a {path, symbol?, start_line?, end_line?} dict in place.
        Returns None if the path is unknown."""
        path = self.normalize(ref.get("path"))
        if not path or not self.lines(path):
            self.issues.append(f"{where}: dropped ref to unknown file '{ref.get('path')}'")
            return None
        ref["path"] = path
        n = len(self.lines(path))
        start, end = ref.get("start_line"), ref.get("end_line")
        symbol = (ref.get("symbol") or "").strip()
        if symbol:
            found = self.find_symbol(path, symbol)
            if found is None:
                ref["uncertain"] = True
                self.issues.append(f"{where}: symbol '{symbol}' not found in {path}")
            elif not (isinstance(start, int) and start <= found <= (end or start) + 2):
                # Model's lines don't contain the definition: snap to it.
                span = (end - start) if isinstance(start, int) and isinstance(end, int) and end > start else span_default
                start, end = found, found + min(span, max_span)
        if not isinstance(start, int) or start < 1:
            start = 1
        if not isinstance(end, int) or end < start:
            end = start + span_default
        ref["start_line"] = min(start, n)
        ref["end_line"] = min(end, n, start + max_span)
        return ref
