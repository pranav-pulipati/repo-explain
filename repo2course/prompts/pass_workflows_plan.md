Analysis pass 4a of 7: CHOOSE WORKFLOWS TO TRACE.

Repository: {repo_name}

Architecture:
{architecture}

Per-file digest:
{digest}

Pick the 2-3 most representative end-to-end flows in this codebase — the ones that, once understood, explain how everything else works. Examples: a request lifecycle from route to response, a CLI command from argument parsing to output, a build/compile step, a main loop / event loop iteration, a job from enqueue to completion. Prefer flows that cross several components.

For each flow, give: a name, the trigger (what starts it), why it is representative, and the list of files (repo paths, in call order) whose code is needed to trace it step by step. Keep each list to the files that matter (usually 3-8).
