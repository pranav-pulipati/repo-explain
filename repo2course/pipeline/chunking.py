"""Stage 2: per-folder summarization so big repos fit in context.

Files are grouped by directory into chunks of at most `limits.chunk_tokens`
(oversized folders are split by subfolder; small neighbours are merged), each
chunk is summarized by the LLM into a structured file/symbol index, and the
summaries are concatenated into a compact "digest" that every analysis pass
can afford to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from .. import prompting
from ..concurrency import parallel_map
from ..providers.base import LLMProvider
from .ingest import FileContent, RepoSnapshot


def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1


def number_lines(content: str, start: int = 1) -> str:
    lines = content.split("\n")
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{i:>{width}} | {line}" for i, line in enumerate(lines, start))


def format_file(f: FileContent, numbered: bool = True) -> str:
    note = " (truncated)" if f.truncated else ""
    header = f"===== FILE: {f.path} ({f.total_lines} lines{note}) ====="
    return f"{header}\n{number_lines(f.content) if numbered else f.content}\n"


def file_tokens(f: FileContent) -> int:
    # Line-number gutter adds ~7 chars per line.
    return estimate_tokens(f.content) + f.total_lines * 2 + 20


@dataclass
class Chunk:
    id: int
    folders: list[str]
    files: list[FileContent] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(file_tokens(f) for f in self.files)

    @property
    def label(self) -> str:
        return ", ".join(self.folders)


def _dir_of(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "" if parent == "." else parent


def build_chunks(files: list[FileContent], budget: int) -> list[Chunk]:
    """Pack files into chunks <= budget tokens, keeping folders together where possible.

    1. Recursively split the folder tree until each unit fits the budget
       (a folder's own files form one unit; a single over-budget file stands alone).
    2. Greedily merge consecutive units (in path order) while they fit.
    """
    units: list[tuple[str, list[FileContent]]] = []

    def split(folder: str, members: list[FileContent]) -> None:
        if sum(file_tokens(f) for f in members) <= budget:
            units.append((folder or ".", members))
            return
        direct = [f for f in members if _dir_of(f.path) == folder]
        children: dict[str, list[FileContent]] = {}
        for f in members:
            d = _dir_of(f.path)
            if d == folder:
                continue
            rel = d[len(folder) + 1:] if folder else d
            child = (folder + "/" if folder else "") + rel.split("/")[0]
            children.setdefault(child, []).append(f)
        if direct:
            # Pack the folder's own files into budget-sized runs.
            run: list[FileContent] = []
            for f in direct:
                if run and sum(file_tokens(x) for x in run) + file_tokens(f) > budget:
                    units.append((folder or ".", run))
                    run = []
                run.append(f)
            if run:
                units.append((folder or ".", run))
        for child in sorted(children):
            split(child, children[child])

    split("", sorted(files, key=lambda f: f.path))

    chunks: list[Chunk] = []
    for folder, members in units:
        size = sum(file_tokens(f) for f in members)
        if chunks and chunks[-1].tokens + size <= budget:
            chunks[-1].files.extend(members)
            if folder not in chunks[-1].folders:
                chunks[-1].folders.append(folder)
        else:
            chunks.append(Chunk(id=len(chunks) + 1, folders=[folder], files=list(members)))
    return chunks


# ---- LLM summaries -----------------------------------------------------------

class Symbol(BaseModel):
    name: str = Field(description="Exact identifier as written in the code")
    kind: str = Field(description="function | class | method | const | type | route | other")
    line: int | None = Field(default=None, description="1-based line where it is defined")
    description: str = ""


class FileSummary(BaseModel):
    path: str
    role: str = Field(description="One or two sentences: what this file is responsible for")
    key_symbols: list[Symbol] = Field(default_factory=list)
    internal_imports: list[str] = Field(default_factory=list, description="Repo paths/modules it uses")
    external_imports: list[str] = Field(default_factory=list, description="Third-party packages it uses")


class ChunkSummary(BaseModel):
    purpose: str = Field(description="What this group of folders does as a whole")
    files: list[FileSummary] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, description="Notable patterns, oddities, TODOs")


class Digest(BaseModel):
    chunks: list[dict]  # {"folders": [...], "summary": ChunkSummary}

    def all_files(self) -> list[dict]:
        return [f for c in self.chunks for f in c["summary"]["files"]]

    def to_text(self) -> str:
        out = []
        for c in self.chunks:
            s = c["summary"]
            out.append(f"## Folder group: {', '.join(c['folders'])}\nPurpose: {s['purpose']}")
            for f in s["files"]:
                syms = "; ".join(
                    f"{x['name']} ({x['kind']}{', L' + str(x['line']) if x.get('line') else ''})"
                    + (f": {x['description']}" if x.get("description") else "")
                    for x in f["key_symbols"])
                line = f"- {f['path']}: {f['role']}"
                if syms:
                    line += f"\n    symbols: {syms}"
                if f["external_imports"]:
                    line += f"\n    uses packages: {', '.join(f['external_imports'])}"
                if f["internal_imports"]:
                    line += f"\n    uses internal: {', '.join(f['internal_imports'])}"
                out.append(line)
            if s["notes"]:
                out.append("Notes: " + " | ".join(s["notes"]))
            out.append("")
        return "\n".join(out)


def summarize_chunks(snapshot: RepoSnapshot, llm: LLMProvider, budget: int) -> Digest:
    chunks = build_chunks(snapshot.files, budget)
    system = prompting.load("system_analyst")
    real_paths = {f.path for f in snapshot.files}

    def one(chunk: Chunk) -> dict:
        prompt = prompting.render(
            "chunk_summary", repo_name=snapshot.name, folders=chunk.label,
            files="\n".join(format_file(f) for f in chunk.files))
        summary = llm.generate(prompt, system=system, json_schema=ChunkSummary)
        # Drop hallucinated paths; the model must only describe files it was shown.
        chunk_paths = {f.path for f in chunk.files}
        summary["files"] = [f for f in summary["files"] if f["path"] in chunk_paths & real_paths]
        return {"folders": chunk.folders, "summary": summary}

    return Digest(chunks=parallel_map(one, chunks, llm.config.max_concurrency))
