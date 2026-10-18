Analysis pass 5 of 7: DESIGN DECISIONS AND TRADE-OFFS.

Repository: {repo_name}

Overview:
{overview}

Architecture:
{architecture}

Dependencies:
{dependencies}

Recent commit history (sha date subject):
{git_log}

Manifests / config:
{manifests}

File tree:
{tree}

Per-file digest:
{digest}

Identify 4-8 design decisions the author evidently made — choices where a reasonable engineer could have gone another way (e.g. sync vs async, monolith vs packages, ORM vs raw SQL, config format, state location, error-handling strategy, plugin mechanism, what NOT to build). For each:
- `decision`: what was chosen; `context`: the forces that made it a decision.
- `alternatives`, `benefits`, `costs`: be concrete about the trade-off.
- `evidence`: concrete support — commit sha + subject, file paths, config entries, dependency choices. `ref` must be a real sha, path or package name from the material above.
If the evidence is circumstantial, set `uncertain: true`.
