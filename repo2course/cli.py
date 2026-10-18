"""Typer CLI: `repo2course build|analyze|script|render`."""

from __future__ import annotations

import logging
from pathlib import Path

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import Config, load_config
from .pipeline.runner import Pipeline, Workspace
from .providers.base import ProviderError

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Turn a GitHub repo into a narrated video course.")
console = Console()

ConfigOpt = typer.Option(Path("config.yaml"), "--config", "-c", help="Path to config.yaml")
NoCacheOpt = typer.Option(False, "--no-cache", help="Ignore cached LLM/TTS results")
VerboseOpt = typer.Option(False, "--verbose", "-v")


def _setup(config_path: Path, verbose: bool) -> Config:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.WARNING, format="%(message)s",
                        handlers=[RichHandler(console=console, show_path=False, show_time=False)])
    for noisy in ("httpx", "httpcore", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if config_path != Path("config.yaml") and not config_path.exists():
        raise typer.BadParameter(f"config file {config_path} not found")
    return load_config(config_path)


def _event(stage: str, msg: str) -> None:
    console.print(f"[bold cyan]{stage:>10}[/] {msg}")


def _usage_table(pipe: Pipeline) -> None:
    if not pipe.usage.stages:
        return
    t = Table(title="Usage", show_lines=False)
    for col in ("stage", "calls", "cached", "in tokens", "out tokens", "tts chars"):
        t.add_column(col, justify="right" if col != "stage" else "left")
    for name, s in [*pipe.usage.stages.items(), ("TOTAL", pipe.usage.totals())]:
        t.add_row(name, str(s.calls), str(s.cached_calls), f"{s.input_tokens:,}", f"{s.output_tokens:,}",
                  f"{s.tts_chars:,}")
    console.print(t)


def _run(fn):
    try:
        return fn()
    except (ProviderError, FileNotFoundError, RuntimeError) as e:
        console.print(f"[bold red]error:[/] {e}")
        raise typer.Exit(1)


@app.command()
def analyze(url: str = typer.Argument(..., help="GitHub URL or local repo path"),
            config: Path = ConfigOpt, no_cache: bool = NoCacheOpt, verbose: bool = VerboseOpt):
    """Ingest + chunk + 7 analysis passes; writes output/<repo>/analysis.json."""
    cfg = _setup(config, verbose)
    pipe = Pipeline(cfg, use_cache=not no_cache, on_event=_event)
    ws, results = _run(lambda: pipe.analyze(url))
    _usage_table(pipe)
    issues = results.get("_grounding", [])
    console.print(f"\n[green]Analysis written to[/] {ws.analysis}"
                  + (f"  ([yellow]{len(issues)} grounding fixes[/], see _grounding)" if issues else ""))


@app.command()
def script(repo: str = typer.Argument(..., help="Repo URL/name or output dir with analysis.json"),
           config: Path = ConfigOpt, no_cache: bool = NoCacheOpt, verbose: bool = VerboseOpt,
           dry_run: bool = typer.Option(False, "--dry-run", help="Print the scene list and durations")):
    """Curriculum + scene script from a saved analysis. (Build step 4.)"""
    _setup(config, verbose)
    console.print("[yellow]`script` arrives in build step 4.[/]")
    raise typer.Exit(2)


@app.command()
def render(repo: str = typer.Argument(..., help="Repo URL/name or output dir with script.json"),
           config: Path = ConfigOpt, no_cache: bool = NoCacheOpt, verbose: bool = VerboseOpt):
    """Visuals + TTS + ffmpeg assembly from a saved script. (Build step 5.)"""
    _setup(config, verbose)
    console.print("[yellow]`render` arrives in build step 5.[/]")
    raise typer.Exit(2)


@app.command()
def build(url: str = typer.Argument(..., help="GitHub URL or local repo path"),
          config: Path = ConfigOpt, no_cache: bool = NoCacheOpt, verbose: bool = VerboseOpt,
          dry_run: bool = typer.Option(False, "--dry-run", help="Skip TTS/render; print scene list")):
    """Full pipeline: analyze -> script -> render."""
    analyze(url, config, no_cache, verbose)
    console.print("[yellow]script/render stages arrive in build steps 4-5.[/]")


if __name__ == "__main__":
    app()
