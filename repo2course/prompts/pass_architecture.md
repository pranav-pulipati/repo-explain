Analysis pass 2 of 7: ARCHITECTURE.

Repository: {repo_name}

Overview from pass 1:
{overview}

File tree:
{tree}

Per-file digest:
{digest}

Source code:
{source}

Describe the architecture as the engineer who built it would explain it to a new teammate:
- `summary`: 3-5 sentences on how the system is put together.
- `style`: the architectural style(s).
- `components`: the 4-10 meaningful components (not one per file). For each: responsibility, the real paths that make it up, which other components it depends on, and its key interfaces (exact identifiers).
- `entry_points`: where execution starts (CLI commands, HTTP servers, main functions, exported library API, scheduled jobs), with path and symbol.
- `boundaries`: process/network/persistence/trust/module boundaries that shape the design.
- `data_flow`: an ordered list of steps describing how data moves through the system for its primary use case.
- `dot`: a Graphviz DOT `digraph` showing components (as nodes, labelled with the component name) and data flow (labelled edges). Rules for DOT: start with `digraph G {`, use `rankdir=LR;`, quote all IDs and labels, no HTML labels, no subgraph styling beyond `subgraph cluster_x { label="..."; }`, at most ~14 nodes. External systems (databases, APIs, user) may appear as nodes with `shape=cylinder` or `shape=box, style=dashed`.
