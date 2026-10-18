"""Prompt templates live in repo2course/prompts/*.md with {placeholders}.

Only `{identifier}` tokens are substituted, so literal braces in JSON
examples or code are left alone.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@lru_cache(maxsize=None)
def load(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def render(name: str, **values: object) -> str:
    template = load(name)
    missing = {m for m in _PLACEHOLDER.findall(template) if m not in values}
    if missing:
        raise KeyError(f"prompt '{name}' needs values for: {', '.join(sorted(missing))}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), template)
