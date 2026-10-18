Analysis pass 3 of 7: DEPENDENCIES.

Repository: {repo_name}

Overview:
{overview}

Architecture:
{architecture}

Manifests / build files:
{manifests}

Per-file digest (see "uses packages" lines for where each package is used):
{digest}

For every SIGNIFICANT dependency (runtime libraries/frameworks the code is built on, important dev/build tools, required system tools or external services) — skip trivial ones like type stubs or linters unless they shape the workflow — explain:
- `what_it_is`: one sentence.
- `how_it_works`: how it works internally at a concept level, enough that a viewer understands what is happening under the hood when this repo calls it (e.g. for an ORM: identity map, unit of work, SQL generation; for a web framework: routing table, middleware chain, request lifecycle).
- `why_chosen`: why this repo likely uses it rather than the alternatives, tied to this repo's needs. This is usually inference: set `uncertain: true` unless the README/commits say why.
- `alternatives`: realistic alternatives.
- `used_in`: real file paths where it is used and how.
- `significance`: 1-5.
- `version`: from the manifest if pinned.
Order by significance, most significant first. Aim for 5-15 dependencies.
