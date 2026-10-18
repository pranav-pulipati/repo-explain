"""Stage 3: multi-pass analysis. Each pass is a separate prompt with a pydantic
schema; later passes receive earlier outputs. After each pass, grounding
drops invented paths and fixes code line ranges against the real checkout.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from .. import prompting
from ..config import LimitsConfig
from ..providers.base import LLMProvider
from .chunking import Digest, estimate_tokens, file_tokens, format_file
from .grounding import Grounder
from .ingest import RepoSnapshot



# ---- schemas -------------------------------------------------------------------

class Flagged(BaseModel):
    uncertain: bool = Field(default=False, description="true if this is inferred rather than directly evidenced")
    uncertainty_note: str = Field(default="", description="Why it is uncertain, if uncertain")


class TechItem(BaseModel):
    name: str
    role: str


class Overview(BaseModel):
    project_name: str
    one_liner: str
    purpose: str
    problem_solved: str
    audience: str
    tech_stack: list[TechItem]
    key_features: list[str]
    maturity: str = Field(description="e.g. prototype, library, production service, CLI tool, framework")
    uncertain_points: list[str] = Field(default_factory=list)


class Component(Flagged):
    name: str
    responsibility: str
    paths: list[str] = Field(description="Real repo paths (files or folders) that make up this component")
    depends_on: list[str] = Field(default_factory=list, description="Names of other components it calls")
    interfaces: list[str] = Field(default_factory=list,
                                  description="Key public functions/classes/endpoints, exact identifiers")


class EntryPoint(BaseModel):
    path: str
    symbol: str = ""
    kind: str = Field(description="cli | http | main | library-api | job | ui | test | other")
    description: str


class Architecture(BaseModel):
    summary: str
    style: str = Field(description="Architectural style, e.g. layered, pipeline, MVC, plugin, event-driven")
    components: list[Component]
    entry_points: list[EntryPoint]
    boundaries: list[str] = Field(description="Important boundaries: process, network, module, trust, persistence")
    data_flow: list[str] = Field(description="Ordered steps describing how data moves through the system")
    dot: str = Field(description="Graphviz DOT digraph of components and data flow")


class DepUsage(BaseModel):
    path: str
    how: str


class Dependency(Flagged):
    name: str
    kind: str = Field(description="runtime | dev | build | system | external-service")
    version: str = ""
    what_it_is: str
    how_it_works: str = Field(description="Concept-level explanation of its internals")
    why_chosen: str
    alternatives: list[str] = Field(default_factory=list)
    used_in: list[DepUsage] = Field(default_factory=list)
    significance: int = Field(ge=1, le=5, description="5 = the project is built around it")


class Dependencies(BaseModel):
    dependencies: list[Dependency]


class FlowPlan(BaseModel):
    name: str
    trigger: str
    why_representative: str
    files: list[str] = Field(description="Files (in call order) needed to trace this flow")


class WorkflowPlan(BaseModel):
    flows: list[FlowPlan]


class TraceStep(Flagged):
    order: int
    path: str
    symbol: str = Field(description="Exact function/method/class name at this step")
    start_line: int
    end_line: int
    what_happens: str
    data_out: str = Field(default="", description="What data/state is handed to the next step")


class Workflow(Flagged):
    name: str
    trigger: str
    why_representative: str
    steps: list[TraceStep]
    outcome: str


class Workflows(BaseModel):
    workflows: list[Workflow]


class Evidence(BaseModel):
    kind: Literal["commit", "structure", "config", "code", "docs", "dependency"]
    ref: str = Field(description="Commit sha, file path, or package name")
    detail: str


class Decision(Flagged):
    title: str
    decision: str
    context: str
    alternatives: list[str]
    benefits: list[str]
    costs: list[str]
    evidence: list[Evidence]


class Decisions(BaseModel):
    decisions: list[Decision]


class Concept(BaseModel):
    name: str
    level: Literal["basic", "intermediate", "advanced"]
    explanation: str
    why_it_matters_here: str
    where_in_repo: list[str] = Field(default_factory=list)


class Concepts(BaseModel):
    concepts: list[Concept]


class RebuildStep(BaseModel):
    order: int
    title: str
    goal: str
    details: str
    files: list[str] = Field(default_factory=list, description="Real repo files this step produces")
    verify: str = Field(description="How you know this step works before moving on")
    depends_on: list[int] = Field(default_factory=list)


class Rebuild(BaseModel):
    steps: list[RebuildStep]
    closing_advice: str


# ---- context building ------------------------------------------------------------

def _clip(text: str | None, chars: int) -> str:
    if not text:
        return "(none)"
    return text if len(text) <= chars else text[:chars] + "\n...[truncated]"


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


class Analyzer:
    PASSES = ["overview", "architecture", "dependencies", "workflows", "decisions", "concepts", "rebuild"]

    def __init__(self, snapshot: RepoSnapshot, digest: Digest, llm: LLMProvider, limits: LimitsConfig):
        self.s = snapshot
        self.digest = digest
        self.llm = llm
        self.limits = limits
        self.system = prompting.load("system_analyst")
        self.grounder = Grounder(snapshot)
        self.results: dict = {}
        raw = "\n".join(format_file(f) for f in snapshot.files)
        self.raw_source = raw if estimate_tokens(raw) <= limits.raw_context_tokens else None

    # shared prompt variables
    def base_vars(self) -> dict:
        langs = ", ".join(f"{k} {v // 1024}KB" for k, v in list(self.s.languages.items())[:10])
        log_lines = "\n".join(f"{c.sha} {c.date} {c.subject}" for c in self.s.git_log) or "(no history)"
        manifests = "\n\n".join(f"--- {p} ---\n{_clip(t, 6000)}" for p, t in self.s.manifests.items()) or "(none)"
        return {
            "repo_name": self.s.name,
            "languages": langs or "(unknown)",
            "tree": self.s.tree_text(400),
            "readme": _clip(self.s.readme, 12000),
            "manifests": manifests,
            "git_log": log_lines,
            "digest": self.digest.to_text(),
            "source": self.raw_source or "(Source too large to include in full; rely on the digest.)",
        }

    def _gen(self, template: str, schema: type[BaseModel], **extra) -> dict:
        prompt = prompting.render(template, **{**self.base_vars(), **extra})
        return self.llm.generate(prompt, system=self.system, json_schema=schema)

    # ---- passes ---------------------------------------------------------------------
    def pass_overview(self):
        self.results["overview"] = self._gen("pass_overview", Overview)

    def pass_architecture(self):
        out = self._gen("pass_architecture", Architecture, overview=_dump(self.results["overview"]))
        g = self.grounder
        for c in out["components"]:
            c["paths"] = g.filter_paths(c["paths"], f"component {c['name']}")
            if not c["paths"]:
                c["uncertain"] = True
        entry_points = []
        for e in out["entry_points"]:
            path = g.normalize(e["path"])
            if path:
                entry_points.append({**e, "path": path})
            else:
                g.issues.append(f"entry point: dropped unknown path '{e['path']}'")
        out["entry_points"] = entry_points
        self.results["architecture"] = out

    def pass_dependencies(self):
        out = self._gen("pass_dependencies", Dependencies,
                        overview=_dump(self.results["overview"]),
                        architecture=_dump(_arch_brief(self.results["architecture"])))
        for d in out["dependencies"]:
            kept = []
            for u in d["used_in"]:
                n = self.grounder.normalize(u["path"])
                if n:
                    kept.append({**u, "path": n})
                else:
                    self.grounder.issues.append(f"dependency {d['name']}: dropped unknown path '{u['path']}'")
            d["used_in"] = kept
        out["dependencies"].sort(key=lambda d: -d["significance"])
        self.results["dependencies"] = out

    def pass_workflows(self):
        arch = _dump(_arch_brief(self.results["architecture"]))
        plan = self._gen("pass_workflows_plan", WorkflowPlan, architecture=arch)
        # Raw code for the files the flows touch, within budget.
        wanted: list[str] = []
        for flow in plan["flows"][:3]:
            for p in self.grounder.filter_paths(flow["files"], f"flow plan {flow['name']}"):
                if p not in wanted:
                    wanted.append(p)
        files, budget = [], self.limits.raw_context_tokens
        for p in wanted:
            f = self.s.file(p)
            if f and file_tokens(f) <= budget:
                files.append(f)
                budget -= file_tokens(f)
        code = "\n".join(format_file(f) for f in files) or "(no files)"
        out = self._gen("pass_workflows_trace", Workflows, architecture=arch,
                        plan=_dump(plan), code=code)
        g = self.grounder
        for wf in out["workflows"]:
            steps = []
            for st in wf["steps"]:
                if g.ground_ref(st, f"workflow {wf['name']} step {st['order']}"):
                    steps.append(st)
            wf["steps"] = sorted(steps, key=lambda s: s["order"])
            if any(s.get("uncertain") for s in steps):
                wf["uncertain"] = True
        self.results["workflows"] = out

    def pass_decisions(self):
        out = self._gen("pass_decisions", Decisions,
                        overview=_dump(self.results["overview"]),
                        architecture=_dump(_arch_brief(self.results["architecture"])),
                        dependencies=_dump(_deps_brief(self.results["dependencies"])))
        for d in out["decisions"]:
            for e in d["evidence"]:
                if e["kind"] in {"structure", "config", "code", "docs"} and not self.grounder.normalize(e["ref"]):
                    e["unverified"] = True
            if not d["evidence"] or all(e.get("unverified") for e in d["evidence"]):
                d["uncertain"] = True
        self.results["decisions"] = out

    def pass_concepts(self):
        out = self._gen("pass_concepts", Concepts,
                        overview=_dump(self.results["overview"]),
                        architecture=_dump(_arch_brief(self.results["architecture"])),
                        dependencies=_dump(_deps_brief(self.results["dependencies"])))
        for c in out["concepts"]:
            c["where_in_repo"] = self.grounder.filter_paths(c["where_in_repo"], f"concept {c['name']}")
        self.results["concepts"] = out

    def pass_rebuild(self):
        prior = {k: self.results[k] for k in ("overview", "decisions", "concepts")}
        prior["architecture"] = _arch_brief(self.results["architecture"])
        prior["dependencies"] = _deps_brief(self.results["dependencies"])
        prior["workflows"] = [{"name": w["name"], "steps": [f"{s['path']}:{s['symbol']}" for s in w["steps"]]}
                              for w in self.results["workflows"]["workflows"]]
        out = self._gen("pass_rebuild", Rebuild, prior=_dump(prior))
        for st in out["steps"]:
            st["files"] = self.grounder.filter_paths(st["files"], f"rebuild step {st['order']}")
        self.results["rebuild"] = out


def _arch_brief(a: dict) -> dict:
    return {k: a[k] for k in ("summary", "style", "components", "entry_points", "data_flow")}


def _deps_brief(d: dict) -> list[dict]:
    return [{"name": x["name"], "kind": x["kind"], "why_chosen": x["why_chosen"],
             "significance": x["significance"]} for x in d["dependencies"]]
