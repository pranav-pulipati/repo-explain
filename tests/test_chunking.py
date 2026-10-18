from repo2course.pipeline.chunking import build_chunks, file_tokens, number_lines
from repo2course.pipeline.ingest import FileContent


def fc(path: str, chars: int) -> FileContent:
    content = ("x" * 79 + "\n") * (chars // 80)
    return FileContent(path=path, content=content, total_lines=content.count("\n") + 1)


def test_everything_fits_in_one_chunk():
    files = [fc("a.py", 800), fc("src/b.py", 800), fc("src/sub/c.py", 800)]
    chunks = build_chunks(files, budget=10_000)
    assert len(chunks) == 1
    assert [f.path for f in chunks[0].files] == ["a.py", "src/b.py", "src/sub/c.py"]


def test_chunks_respect_budget_and_cover_all_files():
    files = [fc(f"pkg{i}/mod{j}.py", 4000) for i in range(5) for j in range(4)]
    budget = 3 * file_tokens(files[0]) + 10
    chunks = build_chunks(files, budget)
    assert all(c.tokens <= budget for c in chunks)
    seen = [f.path for c in chunks for f in c.files]
    assert sorted(seen) == sorted(f.path for f in files) and len(seen) == len(set(seen))


def test_folders_stay_together_when_possible():
    files = [fc(f"a/{i}.py", 2000) for i in range(3)] + [fc(f"b/{i}.py", 2000) for i in range(3)]
    budget = 3 * file_tokens(files[0]) + 10
    chunks = build_chunks(files, budget)
    assert [c.folders for c in chunks] == [["a"], ["b"]]


def test_small_folders_are_merged():
    files = [fc(f"d{i}/x.py", 400) for i in range(6)]
    budget = 4 * file_tokens(files[0])  # the whole tree doesn't fit, so folders get packed
    chunks = build_chunks(files, budget)
    assert [c.folders for c in chunks] == [["d0", "d1", "d2", "d3"], ["d4", "d5"]]


def test_oversized_file_gets_own_chunk():
    files = [fc("a/small.py", 400), fc("a/huge.py", 40_000), fc("a/small2.py", 400)]
    chunks = build_chunks(files, budget=2_000)
    assert any([f.path for f in c.files] == ["a/huge.py"] for c in chunks)
    assert sum(len(c.files) for c in chunks) == 3


def test_number_lines_alignment():
    assert number_lines("a\nb", start=9) == " 9 | a\n10 | b"
