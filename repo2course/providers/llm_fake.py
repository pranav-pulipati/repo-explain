"""Offline fake LLM for tests and wiring checks.

Pass `handler(prompt, system, json_schema) -> str` to script responses;
without one it returns a minimal schema-conforming JSON document.
"""

from __future__ import annotations

import json
from typing import Callable

from .base import LLMProvider, LLMResult
from .registry import register_llm


@register_llm("fake")
class FakeLLM(LLMProvider):
    def __init__(self, config, cache=None, usage=None,
                 handler: Callable[[str, str | None, dict | None], str] | None = None):
        super().__init__(config, cache, usage)
        self.handler = handler
        self.calls: list[dict] = []

    def _complete(self, prompt, system, json_schema):
        self.calls.append({"prompt": prompt, "system": system, "schema": json_schema})
        if self.handler:
            text = self.handler(prompt, system, json_schema)
        elif json_schema:
            text = json.dumps(example_from_schema(json_schema, json_schema))
        else:
            text = "fake response"
        return LLMResult(text=text, input_tokens=len(prompt) // 4, output_tokens=len(text) // 4)


def example_from_schema(node: dict, root: dict) -> object:
    if "$ref" in node:
        ref = node["$ref"].split("/")[-1]
        return example_from_schema(root.get("$defs", {}).get(ref, {}), root)
    for combo in ("anyOf", "oneOf"):
        if combo in node:
            options = [o for o in node[combo] if o.get("type") != "null"] or node[combo]
            return example_from_schema(options[0], root)
    if "default" in node:
        return node["default"]
    if "enum" in node:
        return node["enum"][0]
    t = node.get("type")
    if t == "object":
        return {k: example_from_schema(v, root) for k, v in node.get("properties", {}).items()}
    if t == "array":
        return [example_from_schema(node.get("items", {}), root)]
    return {"string": "example", "integer": 1, "number": 1.0, "boolean": False}.get(t, None)
