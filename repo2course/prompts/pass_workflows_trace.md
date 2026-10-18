Analysis pass 4b of 7: TRACE WORKFLOWS.

Repository: {repo_name}

Architecture:
{architecture}

Flows chosen:
{plan}

Source code of the files involved (with line numbers):
{code}

Trace each flow file by file, function by function, in execution order. For each step give:
- `path` and `symbol`: the exact file and function/method/class where this step happens.
- `start_line` / `end_line`: the line range (from the numbers shown) of the code most worth showing on screen for this step — usually the function body or its key 5-25 lines. Keep ranges under 30 lines.
- `what_happens`: what the code does here and why, in plain words.
- `data_out`: what data/state it hands to the next step.
Typically 4-10 steps per flow. Only use code you can see above; if a step happens in a file not shown, describe it, set `uncertain: true`, and still give the path and symbol you believe it is in. Finish each flow with its `outcome`.
