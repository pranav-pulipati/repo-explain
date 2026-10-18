import subprocess
from pathlib import Path

import pytest

from repo2course.config import Config


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config()
    cfg.llm.provider = "fake"
    cfg.llm.retry.backoff_seconds = 0
    cfg.tts.provider = "fake"
    cfg.paths.output_dir = tmp_path / "output"
    cfg.paths.cache_dir = tmp_path / "cache"
    return cfg


@pytest.fixture
def sample_repo(tmp_path) -> Path:
    """A tiny git repo with source, tests, a lockfile, node_modules and a binary."""
    root = tmp_path / "sample"
    files = {
        "README.md": "# Sample\nA tiny todo API.\n",
        "pyproject.toml": '[project]\nname = "sample"\ndependencies = ["fastapi"]\n',
        "src/app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.get('/todos')\ndef list_todos():\n    return store.all()\n",
        "src/app/store.py": "class Store:\n    def __init__(self):\n        self.items = []\n\n    def all(self):\n        return list(self.items)\n",
        "tests/test_main.py": "def test_ok():\n    assert True\n",
        "package-lock.json": "{}",
        "node_modules/left-pad/index.js": "module.exports = 1",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x00")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    run("init", "-q")
    run("-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "Initial todo API")
    return root
