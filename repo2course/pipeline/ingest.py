"""Stage 1: clone a repo and build a size-capped snapshot of what matters.

Produces `RepoSnapshot`: full file tree (paths + sizes), README, manifests,
recent git log, language stats, and the contents of up to
`limits.max_files_read` prioritized source files. The clone stays in
output/<name>/repo so later stages can pull real line ranges for code slides.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..config import LimitsConfig

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "third_party", "third-party", "dist", "build", "out", "target",
    ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", ".next", ".nuxt",
    ".cache", "coverage", ".idea", ".vscode", "bower_components", "Pods", ".gradle", ".terraform",
    "site-packages", ".eggs", "htmlcov", ".svelte-kit", ".turbo"
}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "Cargo.lock",
    "Gemfile.lock", "composer.lock", "go.sum", "uv.lock", "bun.lockb", "mix.lock", "pubspec.lock",
    "packages.lock.json", "flake.lock",
}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svg", ".pdf", ".zip", ".gz", ".tar",
    ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war", ".class", ".so", ".dll", ".dylib", ".exe",
    ".bin", ".o", ".a", ".pyc", ".pyo", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp3", ".mp4",
    ".wav", ".ogg", ".webm", ".mov", ".avi", ".db", ".sqlite", ".sqlite3", ".parquet", ".pkl",
    ".npy", ".npz", ".onnx", ".pt", ".pth", ".h5", ".ckpt", ".safetensors", ".psd", ".ai", ".sketch",
    ".fig", ".wasm", ".map",
}
SKIP_GLOBS = ["*.min.js", "*.min.css", "*.bundle.js", "*.chunk.js", "*.snap", "*.pb.go", "*_pb2.py",
              "*.generated.*", "*.lock"]

# Listed in the tree but never worth sending to the LLM.
NO_READ_GLOBS = ["LICENSE*", "LICENCE*", "COPYING*", "NOTICE*", "CODE_OF_CONDUCT*", ".editorconfig",
                 ".gitignore", ".gitattributes", ".dockerignore", "*.bat", ".github/ISSUE_TEMPLATE/*",
                 ".github/pull_request_template.md", ".github/FUNDING.yml", "*.csv", "*.tsv", "*.txt.gz"]

MANIFESTS = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-dev.txt",
    "Pipfile", "go.mod", "Cargo.toml", "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "mix.exs", "pubspec.yaml", "Package.swift", "CMakeLists.txt", "Makefile",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yaml", "deno.json",
    "tsconfig.json", "environment.yml", "*.csproj", "*.gemspec", "*.cabal", "build.zig", "Justfile",
    "vite.config.ts", "vite.config.js", "next.config.js", "next.config.mjs", "webpack.config.js",
}

LANGS = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".kts": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++",
    ".hpp": "C++", ".cs": "C#", ".swift": "Swift", ".m": "Objective-C", ".scala": "Scala", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".lua": "Lua", ".dart": "Dart", ".r": "R",
    ".jl": "Julia", ".zig": "Zig", ".vue": "Vue", ".svelte": "Svelte", ".sh": "Shell", ".bash": "Shell",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".md": "Markdown", ".rst": "reST",
    ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".json": "JSON", ".proto": "Protobuf",
    ".tf": "Terraform", ".clj": "Clojure", ".ml": "OCaml", ".nim": "Nim", ".sol": "Solidity",
}
CODE_LANGS = set(LANGS.values()) - {"Markdown", "reST", "YAML", "TOML", "JSON", "HTML", "CSS", "SCSS"}

ENTRY_NAMES = re.compile(
    r"^(main|app|index|server|cli|__main__|manage|wsgi|asgi|run|start|bootstrap|program|lib|mod|init|"
    r"api|routes|router|urls|handler|worker|core|engine|application)\.", re.I)


class FileEntry(BaseModel):
    path: str
    size: int
    language: str | None = None
    lines: int | None = None


class FileContent(BaseModel):
    path: str
    language: str | None = None
    content: str
    truncated: bool = False
    total_lines: int


class Commit(BaseModel):
    sha: str
    date: str
    author: str
    subject: str


class RepoSnapshot(BaseModel):
    name: str
    source: str
    commit: str | None = None
    repo_dir: str
    tree: list[FileEntry]
    readme: str | None = None
    readme_path: str | None = None
    manifests: dict[str, str] = Field(default_factory=dict)
    git_log: list[Commit] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)  # bytes per language
    files: list[FileContent] = Field(default_factory=list)
    skipped_count: int = 0

    def file(self, path: str) -> FileContent | None:
        return next((f for f in self.files if f.path == path), None)

    def has_path(self, path: str) -> bool:
        p = path.strip("/")
        return any(e.path == p or e.path.startswith(p + "/") for e in self.tree)

    def tree_text(self, max_entries: int = 600) -> str:
        return render_tree([e.path for e in self.tree], max_entries=max_entries)


def repo_name_from_source(source: str) -> str:
    if Path(source).exists():
        return Path(source).resolve().name
    path = urlparse(source).path if "://" in source else source.split(":", 1)[-1]
    parts = [p for p in path.rstrip("/").removesuffix(".git").split("/") if p]
    name = "-".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "repo")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name)


def clone(source: str, dest: Path, depth: int) -> Path:
    """Shallow-clone `source` into dest (reused if already present). Local paths are used in place."""
    if Path(source).exists():
        return Path(source).resolve()
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", str(depth), "--single-branch", "--no-tags", source, str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {proc.stderr.strip()}")
    return dest


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _is_skipped_dir(rel_parts: tuple[str, ...]) -> bool:
    return any(p in SKIP_DIRS or (p.startswith(".") and p not in {".github"}) for p in rel_parts)


def _is_skipped_file(rel: PurePosixPath) -> bool:
    name = rel.name
    if name in LOCKFILES or rel.suffix.lower() in BINARY_EXT:
        return True
    return any(fnmatch.fnmatch(name, g) for g in SKIP_GLOBS)


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return True
    return b"\x00" in chunk


def _is_manifest(name: str) -> bool:
    return any(fnmatch.fnmatch(name, m) for m in MANIFESTS)


def _priority(entry: FileEntry) -> float:
    """Higher = read first. Favours entry points, shallow source, manifests; demotes tests/docs/fixtures."""
    p = PurePosixPath(entry.path)
    parts = [x.lower() for x in p.parts]
    score = 0.0
    if _is_manifest(p.name):
        score += 50
    if ENTRY_NAMES.match(p.name):
        score += 25
    if entry.language in CODE_LANGS:
        score += 30
    elif entry.language in {"YAML", "TOML", "JSON"}:
        score += 8
    score -= 4 * (len(parts) - 1)
    if any(x in {"src", "lib", "app", "pkg", "internal", "cmd", "core", "server", "api"} for x in parts[:-1]):
        score += 10
    if any(x in {"test", "tests", "__tests__", "spec", "specs", "testing"} for x in parts) or \
            re.search(r"(^test_|_test\.|\.test\.|\.spec\.)", p.name):
        score -= 25
    if any(x in {"docs", "doc", "examples", "example", "samples", "fixtures", "testdata", "benchmarks",
                 "scripts", "migrations"} for x in parts):
        score -= 18
    if p.name in {"__init__.py"} and entry.size < 200:
        score -= 30
    if entry.size > 40_000:
        score -= 10
    if entry.size < 50:
        score -= 20
    return score


def ingest(source: str, workdir: Path, limits: LimitsConfig, exclude: list[Path] = ()) -> RepoSnapshot:
    """`exclude`: directories to ignore if they sit inside the repo (our own output/cache)."""
    name = repo_name_from_source(source)
    repo_dir = clone(source, workdir / "repo", limits.git_log_depth)
    # Only dirs *inside* the repo (e.g. analyzing "." with ./output present);
    # remote clones themselves live under output/.
    excluded = [p for e in exclude if (p := Path(e).resolve()).is_relative_to(repo_dir.resolve())
                and p != repo_dir.resolve()]

    tree: list[FileEntry] = []
    skipped = 0
    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = PurePosixPath(path.relative_to(repo_dir).as_posix())
        if _is_skipped_dir(rel.parts[:-1]) or _is_skipped_file(rel) or \
                any(path.resolve().is_relative_to(e) for e in excluded):
            skipped += 1
            continue
        size = path.stat().st_size
        tree.append(FileEntry(path=str(rel), size=size, language=LANGS.get(rel.suffix.lower())))

    languages: Counter[str] = Counter()
    for e in tree:
        if e.language:
            languages[e.language] += e.size

    readme_path = next((e.path for e in tree if "/" not in e.path and e.path.lower().startswith("readme")), None)
    readme = _read_text(repo_dir / readme_path, limits.max_file_bytes)[0] if readme_path else None

    manifests: dict[str, str] = {}
    for e in tree:
        if _is_manifest(PurePosixPath(e.path).name) and e.path.count("/") <= 2 and len(manifests) < 25:
            manifests[e.path] = _read_text(repo_dir / e.path, 20_000)[0]

    files: list[FileContent] = []
    total = 0
    for e in sorted(tree, key=_priority, reverse=True):
        if len(files) >= limits.max_files_read or total >= limits.max_total_bytes:
            break
        if e.path == readme_path or e.size == 0 or \
                any(fnmatch.fnmatch(e.path, g) or fnmatch.fnmatch(PurePosixPath(e.path).name, g) for g in NO_READ_GLOBS):
            continue
        full = repo_dir / e.path
        if _looks_binary(full):
            continue
        text, truncated = _read_text(full, limits.max_file_bytes)
        n_lines = text.count("\n") + 1
        e.lines = n_lines if not truncated else None
        files.append(FileContent(path=e.path, language=e.language, content=text, truncated=truncated,
                                 total_lines=n_lines))
        total += len(text)
    files.sort(key=lambda f: f.path)

    git_log = []
    for line in _git(repo_dir, "log", f"-n{limits.git_log_depth}", "--date=short",
                     "--pretty=format:%h\x1f%ad\x1f%an\x1f%s").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            git_log.append(Commit(sha=parts[0], date=parts[1], author=parts[2], subject=parts[3]))

    return RepoSnapshot(
        name=name, source=source, commit=_git(repo_dir, "rev-parse", "HEAD").strip() or None,
        repo_dir=str(repo_dir), tree=tree, readme=readme, readme_path=readme_path, manifests=manifests,
        git_log=git_log, languages=dict(languages.most_common()), files=files, skipped_count=skipped,
    )


def _read_text(path: Path, max_bytes: int) -> tuple[str, bool]:
    data = path.read_bytes()
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
        cut = data.rfind(b"\n")
        if cut > 0:
            data = data[:cut]
    return data.decode("utf-8", errors="replace"), truncated


def render_tree(paths: list[str], max_entries: int = 600) -> str:
    """ASCII tree. Collapses directories when there are too many entries."""
    root: dict = {}
    for p in paths:
        node = root
        for part in p.split("/"):
            node = node.setdefault(part, {})

    lines: list[str] = []

    def count(node: dict) -> int:
        return sum(1 + count(c) for c in node.values())

    def walk(node: dict, prefix: str, depth: int) -> None:
        items = sorted(node.items(), key=lambda kv: (not kv[1], kv[0].lower()))
        for i, (name, child) in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            if child:
                n = count(child)
                if len(lines) + n > max_entries and depth > 0:
                    lines.append(f"{prefix}{branch}{name}/  ({n} entries)")
                    continue
                lines.append(f"{prefix}{branch}{name}/")
                walk(child, prefix + ("    " if last else "│   "), depth + 1)
            else:
                lines.append(f"{prefix}{branch}{name}")

    walk(root, "", 0)
    return "\n".join(lines)
