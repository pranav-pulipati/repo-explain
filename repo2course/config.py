"""Configuration: config.yaml + .env, validated with pydantic.

Provider sections allow extra keys so a new provider can read its own options
(e.g. `tts.stability` for ElevenLabs) without touching this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


class RetryConfig(BaseModel):
    attempts: int = 5
    backoff_seconds: float = 4.0
    max_backoff_seconds: float = 90.0


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = "gemini"
    model: str = "gemini-2.5-flash"
    max_concurrency: int = 2
    temperature: float = 0.3
    timeout_seconds: float = 300.0
    retry: RetryConfig = Field(default_factory=RetryConfig)

    def extra(self, key: str, default=None):
        return (self.model_extra or {}).get(key, default)


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str = "edge"
    voice: str = "en-US-AndrewNeural"
    rate: str = "+0%"
    max_concurrency: int = 4
    retry: RetryConfig = Field(default_factory=lambda: RetryConfig(attempts=3, backoff_seconds=2))

    def extra(self, key: str, default=None):
        return (self.model_extra or {}).get(key, default)


class VideoConfig(BaseModel):
    resolution: tuple[int, int] = (1920, 1080)
    fps: int = 24
    theme: Literal["dark", "light"] = "dark"
    subtitles: Literal["sidecar", "burned", "both", "none"] = "sidecar"
    fade_seconds: float = 0.4
    scene_padding_seconds: float = 0.6


class LimitsConfig(BaseModel):
    max_files_read: int = 150
    max_file_bytes: int = 60_000
    max_total_bytes: int = 2_500_000
    target_minutes: float = 15
    words_per_minute: int = 150
    chunk_tokens: int = 60_000
    # If all selected source fits under this, analysis passes also see raw code
    # (more accurate than summaries alone). Workflow tracing always gets raw code.
    raw_context_tokens: int = 80_000
    git_log_depth: int = 50


class PathsConfig(BaseModel):
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")


class Config(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_config(path: str | Path | None = "config.yaml", env_file: str | Path | None = ".env") -> Config:
    """Load .env (if present) into the process env, then parse config.yaml.

    A missing config file yields defaults, so `repo2course build <url>` works
    out of the box once GEMINI_API_KEY is set.
    """
    if env_file and Path(env_file).exists():
        load_dotenv(env_file)
    data: dict = {}
    if path and Path(path).exists():
        data = yaml.safe_load(Path(path).read_text()) or {}
    return Config.model_validate(data)
