Repository: {repo_name}
You are indexing one group of folders: {folders}

Below are the files in this group, with line numbers. For EACH file listed, produce:
- `path`: exactly as shown in the FILE header.
- `role`: one or two sentences on what the file is responsible for and how it fits in.
- `key_symbols`: the important definitions (public functions, classes, methods, routes, constants that drive behaviour), each with the exact name, kind, the 1-based line it is defined on, and a short description. Skip trivial helpers. Up to ~12 per file.
- `internal_imports`: other repo files/modules it depends on.
- `external_imports`: third-party packages it uses (package names, not stdlib unless it is central).

Also give the group's overall `purpose` and any `notes` worth knowing (patterns, oddities, TODO/FIXME, dead code, surprising choices).

{files}
