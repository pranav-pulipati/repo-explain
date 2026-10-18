import json

from repo2course.pipeline.grounding import Grounder
from repo2course.pipeline.ingest import ingest, render_tree, repo_name_from_source
from repo2course.pipeline.runner import Pipeline
from repo2course.prompting import render


def test_repo_name_from_url():
    assert repo_name_from_source("https://github.com/psf/requests") == "psf-requests"
    assert repo_name_from_source("https://github.com/psf/requests.git/") == "psf-requests"
    assert repo_name_from_source("git@github.com:psf/requests.git") == "psf-requests"


def test_ingest_skips_noise(sample_repo, config, tmp_path):
    snap = ingest(str(sample_repo), tmp_path / "ws", config.limits)
    paths = {e.path for e in snap.tree}
    assert "src/app/main.py" in paths
    assert not any(p.startswith("node_modules") for p in paths)
    assert "package-lock.json" not in paths and "logo.png" not in paths
    assert snap.readme.startswith("# Sample") and "pyproject.toml" in snap.manifests
    assert snap.git_log[0].subject == "Initial todo API"
    assert snap.languages["Python"] > 0
    assert snap.file("src/app/main.py") is not None


def test_ingest_respects_file_caps(sample_repo, config, tmp_path):
    config.limits.max_files_read = 2
    snap = ingest(str(sample_repo), tmp_path / "ws", config.limits)
    assert len(snap.files) == 2
    assert "tests/test_main.py" not in {f.path for f in snap.files}  # tests are deprioritized


def test_render_tree():
    out = render_tree(["a/b.py", "a/c/d.py", "e.txt"])
    assert out.splitlines() == ["├── a/", "│   ├── c/", "│   │   └── d.py", "│   └── b.py", "└── e.txt"]


def test_grounder_fixes_lines_and_drops_unknown(sample_repo, config, tmp_path):
    g = Grounder(ingest(str(sample_repo), tmp_path / "ws", config.limits))
    ref = g.ground_ref({"path": "./src/app/store.py", "symbol": "Store.all", "start_line": 40, "end_line": 44}, "t")
    assert ref["path"] == "src/app/store.py" and ref["start_line"] == 5 and ref["end_line"] <= 6
    assert g.ground_ref({"path": "src/nope.py", "symbol": "x"}, "t") is None
    assert g.filter_paths(["sample/src/app", "made/up.py"], "t") == ["src/app"]
    assert any("made/up.py" in i for i in g.issues)


def test_prompts_render_with_literal_braces():
    text = render("chunk_summary", repo_name="r", folders="src", files="def f(): return {'a': 1}")
    assert "{'a': 1}" in text and "{files}" not in text


def test_full_analyze_offline(sample_repo, config):
    pipe = Pipeline(config)
    ws, results = pipe.analyze(str(sample_repo))
    for key in ("overview", "architecture", "dependencies", "workflows", "decisions", "concepts", "rebuild"):
        assert key in results
        assert (ws.analysis_dir).glob(f"*_{key}.json")
    saved = json.loads(ws.analysis.read_text())
    assert saved["_meta"]["llm"] == "fake/gemini-2.5-flash"
    usage = json.loads(ws.usage.read_text())
    assert "analyze:overview" in usage["stages"]
    # Rerun is fully cached.
    pipe2 = Pipeline(config)
    pipe2.analyze(str(sample_repo))
    assert pipe2.usage.totals().calls == pipe2.usage.totals().cached_calls


def test_ingest_excludes_own_output_inside_repo_only(sample_repo, config, tmp_path):
    (sample_repo / "output" / "x").mkdir(parents=True)
    (sample_repo / "output" / "x" / "analysis.json").write_text("{}")
    snap = ingest(str(sample_repo), tmp_path / "ws", config.limits, exclude=[sample_repo / "output"])
    assert not any(e.path.startswith("output/") for e in snap.tree)
    # A clone that lives under the output dir must still be read.
    snap2 = ingest(str(sample_repo), tmp_path / "ws", config.limits, exclude=[sample_repo.parent])
    assert snap2.files
