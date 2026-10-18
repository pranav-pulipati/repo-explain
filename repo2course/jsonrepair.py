"""Robust extraction of JSON from LLM output.

Models wrap JSON in prose or code fences, leave trailing commas, emit Python
literals, or get truncated mid-object. `parse_json` tries progressively more
aggressive local repairs before giving up; the provider layer then does one
LLM-assisted repair retry.
"""

from __future__ import annotations

import json
import re
from typing import Any


class JSONParseError(ValueError):
    pass


_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)


def parse_json(text: str) -> Any:
    if text is None:
        raise JSONParseError("empty response")
    text = text.strip().lstrip("\ufeff")
    if not text:
        raise JSONParseError("empty response")

    candidates: list[str] = []
    for m in _FENCE_RE.finditer(text):
        candidates.append(m.group(1).strip())
    candidates.append(text)
    span = _outermost_span(text)
    if span:
        candidates.append(span)
    # Unterminated fence (truncated output)
    if text.startswith("```"):
        candidates.append(text.split("\n", 1)[1] if "\n" in text else "")

    last_err: Exception | None = None
    for cand in candidates:
        for fixer in (lambda s: s, _light_repair, lambda s: _close_truncated(_light_repair(s))):
            try:
                return json.loads(fixer(cand))
            except (json.JSONDecodeError, ValueError) as e:
                last_err = e
    raise JSONParseError(f"could not parse JSON: {last_err}")


def _outermost_span(text: str) -> str | None:
    """Return the first balanced {...} or [...] span, respecting strings."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
    stack: list[str] = []
    in_str = False
    esc = False
    pairs = {"{": "}", "[": "]"}
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    return text[start : i + 1]
    return text[start:]  # unbalanced: likely truncated


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _light_repair(s: str) -> str:
    s = s.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    s = _strip_comments(s)
    s = _TRAILING_COMMA_RE.sub(r"\1", s)
    s = _replace_outside_strings(s, {"True": "true", "False": "false", "None": "null"})
    return s


def _strip_comments(s: str) -> str:
    out = []
    i, n = 0, len(s)
    in_str = esc = False
    while i < n:
        ch = s[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j == -1 else j
        elif s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _replace_outside_strings(s: str, mapping: dict[str, str]) -> str:
    pattern = re.compile(r'"(?:\\.|[^"\\])*"|\b(' + "|".join(map(re.escape, mapping)) + r")\b")
    return pattern.sub(lambda m: mapping[m.group(1)] if m.group(1) else m.group(0), s)


def _close_truncated(s: str) -> str:
    """Close an output that was cut off: terminate an open string, drop a
    dangling key/comma, and close open brackets."""
    stack: list[str] = []
    in_str = esc = False
    pairs = {"{": "}", "[": "]"}
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "}]" and stack and stack[-1] == ch:
            stack.pop()
    if not stack and not in_str:
        return s
    if in_str:
        s += '"'
    s = s.rstrip()
    # Drop incomplete trailing members: `, "key":` / `, "key"` / `,`
    s = re.sub(r',\s*"[^"]*"\s*:\s*$', "", s)
    s = re.sub(r'[,:]\s*$', "", s)
    s = _TRAILING_COMMA_RE.sub(r"\1", s)
    return s + "".join(reversed(stack))
