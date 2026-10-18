"""Content-hash cache for LLM and TTS calls.

Keys are sha256 over everything that affects the output (provider, model,
prompt, voice...). Reruns hit the cache, so an interrupted build resumes for
free and re-rendering never re-bills an API.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


def content_hash(*parts: Any) -> str:
    h = hashlib.sha256()
    for part in parts:
        if not isinstance(part, (str, bytes)):
            part = json.dumps(part, sort_keys=True, default=str)
        if isinstance(part, str):
            part = part.encode("utf-8")
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


class ContentCache:
    def __init__(self, root: str | Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled

    def _path(self, namespace: str, key: str, suffix: str) -> Path:
        return self.root / namespace / key[:2] / f"{key}{suffix}"

    # JSON values (LLM responses)
    def get_json(self, namespace: str, key: str) -> Any | None:
        if not self.enabled:
            return None
        p = self._path(namespace, key, ".json")
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            return None

    def set_json(self, namespace: str, key: str, value: Any) -> None:
        if not self.enabled:
            return
        p = self._path(namespace, key, ".json")
        _atomic_write(p, json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8"))

    # Binary files (TTS audio)
    def get_file(self, namespace: str, key: str, suffix: str) -> Path | None:
        if not self.enabled:
            return None
        p = self._path(namespace, key, suffix)
        return p if p.exists() and p.stat().st_size > 0 else None

    def put_file(self, namespace: str, key: str, src: Path) -> Path:
        dst = self._path(namespace, key, src.suffix)
        if self.enabled:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        return dst


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
