"""Build agents: spec + source data -> programs + datasets.

  Planner ──> one DatasetBuilder node per target dataset, wired by data dependencies
              (DM -> AE, ADSL -> ADAE ...) so independent datasets build in parallel.

  DatasetBuilder runs a tight loop of sub-agents:
      Coder      deterministic compiler draft  ->  LLM fills TODO rows (long tail)
      Executor   run in sandbox
      Validator  spec conformance (+ blinded reference concordance if provided)
      Repairer   BUILD_BUG / runtime error -> LLM patch -> re-run   (max N attempts)
"""
from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path

import pandas as pd

from ..llm import extract_code, register_mock
from ..models import DatasetBuild, Spec
from ..orchestration import Agent, Context
from ..runtime import stdlib
from .compiler import choose_base, compile_dataset
from .sandbox import run_program
from .validate import check_against_spec, compare_to_reference

MAX_ATTEMPTS = int(os.getenv("SPECFORGE_MAX_REPAIRS", "3"))
SHARE_SAMPLES = os.getenv("SPECFORGE_SHARE_SAMPLES", "1") == "1"  # set 0 to never send data values to the LLM


def profile_tables(tables: dict[str, pd.DataFrame], n: int = 3) -> str:
    out = []
    for name, df in tables.items():
        out.append(f"{name}: {len(df)} rows")
        for c in df.columns:
            ex = df[c].dropna().astype(str).unique()[:n].tolist() if SHARE_SAMPLES else []
            out.append(f"  {c} ({df[c].dtype}){' e.g. ' + json.dumps(ex) if ex else ''}")
    return "\n".join(out)


def stdlib_doc() -> str:
    lines = []
    for name in stdlib.__all__:
        fn = getattr(stdlib, name)
        if callable(fn) and inspect.isfunction(fn):
            lines.append(f"{name}{inspect.signature(fn)}: {(inspect.getdoc(fn) or '').splitlines()[0]}")
    return "\n".join(lines)


# ---------------------------------------------------------------------- planner
class PlannerAgent(Agent):
    name = "Planner"
    description = "Resolve dataset dependencies and build order"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        inputs: dict[str, pd.DataFrame] = ctx.state["inputs"]
        targets = ctx.state.get("targets") or spec.dataset_names()
        cols = {k: list(v.columns) for k, v in inputs.items()}
        cols.update({t: [v.variable for v in spec.vars_of(t)] for t in targets})  # targets become inputs downstream
        plan = []
        for t in targets:
            refs = {ds for v in spec.vars_of(t) for ds in re.findall(r"\b([A-Z][A-Z0-9_]*)\.[A-Z]", v.derivation)}
            meta = spec.dataset(t)
            refs |= set(meta.sources if meta else [])
            refs.discard(t)
            needs = sorted(r for r in refs if r in targets)
            missing = sorted(r for r in refs if r not in targets and r not in inputs)
            try:
                base = choose_base(spec, t, cols)
            except ValueError as e:
                base, missing = "", missing + [str(e)]
            plan.append({"dataset": t, "base": base, "needs": needs, "inputs": sorted(refs - set(needs) - set(missing)),
                         "missing": missing, "status": "blocked" if missing else "ready"})
        # levels for display
        level = {}
        def lv(name, seen=()):
            if name in level:
                return level[name]
            p = next(p for p in plan if p["dataset"] == name)
            level[name] = 1 + max((lv(n, seen + (name,)) for n in p["needs"] if n not in seen), default=-1)
            return level[name]
        for p in plan:
            p["level"] = lv(p["dataset"])
        plan.sort(key=lambda p: (p["level"], p["dataset"]))
        for p in plan:
            self.log(ctx, f"{p['dataset']}: level {p['level']}, base {p['base'] or '?'}, needs {p['needs'] or '-'}"
                          + (f", MISSING {p['missing']}" if p["missing"] else ""), "result")
        ctx.state["plan"] = plan
        return plan


# ------------------------------------------------------------------- prompts
CODER_SYSTEM = """You are an expert clinical programmer writing Python (pandas) that builds the {standard} dataset {dataset}
exactly as its specification says. A deterministic compiler already produced a draft; rows marked TODO(coder) are
not implemented. Complete them.

Hard rules:
- Keep the module structure: constants, `build(src: dict) -> pd.DataFrame`, return finalize(df, COLUMNS, TYPES).
- Implement each TODO row from its spec text only. Copy literals, labels and codelist values from the spec
  text character-for-character; never retype or "fix" them.
- If a row is genuinely ambiguous, implement the most literal reading and add a comment starting with
  `# AMBIGUITY:` describing the assumption. Never guess silently.
- Only use pandas/numpy and the helper library below (already imported). No file, network or OS access.
- Do not touch rows the compiler already implemented unless they raise an error.

Helper library:
{stdlib}

Return the complete Python module in one ```python block."""

REPAIR_SYSTEM = """The program below failed validation or crashed. Fix the program so it satisfies the spec.
Only BUILD_BUG issues and runtime errors are yours to fix; SPEC_GAP / DATA_ISSUE must not be "fixed" by inventing
rules — leave them and add an `# AMBIGUITY:` comment. Same hard rules as before. Return the full module in one
```python block."""


@register_mock("codegen")
def offline_codegen(ctx: dict) -> str:
    return ctx["draft"]  # offline: keep compiler output; TODO rows stay visible to the validator


@register_mock("repair")
def offline_repair(ctx: dict) -> str:
    return ctx["code"]


# --------------------------------------------------------------- dataset node
class DatasetBuilder(Agent):
    description = "Code -> run -> validate -> repair"

    def __init__(self, dataset: str) -> None:
        self.dataset = dataset
        self.name = f"Build[{dataset}]"

    def sub(self, ctx: Context, role: str, msg: str, kind: str = "info", **data):
        ctx.tracer.emit(f"{role}[{self.dataset}]", msg, kind, **data)

    async def run(self, ctx: Context) -> DatasetBuild:
        spec: Spec = ctx.state["spec"]
        ds = self.dataset
        res = DatasetBuild(dataset=ds)
        p = next(p for p in ctx.state["plan"] if p["dataset"] == ds)
        if p["status"] == "blocked" or any(ctx.state["built"].get(n) is None for n in p["needs"]):
            res.status = "failed"
            res.issues.append({"check": "plan", "class": "DATA_ISSUE", "severity": "error",
                               "message": f"Blocked: missing inputs {p['missing'] or p['needs']}", "variable": "",
                               "count": 0, "examples": []})
            self.sub(ctx, "Planner", "skipped: inputs missing", "warning")
            return res

        tables = {**ctx.state["inputs"], **{k: v for k, v in ctx.state["built"].items() if v is not None}}
        tables_for_job = {k: tables[k] for k in [p["base"], *p["inputs"], *p["needs"]] if k in tables}
        cols = {k: list(v.columns) for k, v in tables_for_job.items()}

        # ---- Coder
        comp = compile_dataset(spec, ds, cols, spec.source_name)
        self.sub(ctx, "Coder", f"compiler implemented {len(comp.compiled)}/{len(spec.vars_of(ds))} variables"
                 + (f"; {len(comp.unresolved)} left for the LLM: {[v.variable for v in comp.unresolved]}" if comp.unresolved else ""),
                 "tool")
        code = comp.code
        unresolved = {v.variable for v in comp.unresolved}
        if comp.unresolved and not ctx.llm.offline:
            rows = "\n".join(f"[row {v.row}] {v.variable} | {v.label} | {v.type} | {v.origin} | {v.codelist} | {v.derivation}"
                             for v in spec.vars_of(ds))
            user = f"Spec rows for {ds}:\n{rows}\n\nInput tables:\n{profile_tables(tables_for_job)}\n\nDraft:\n```python\n{code}```"
            out = await ctx.llm.complete(CODER_SYSTEM.format(standard=spec.standard, dataset=ds, stdlib=stdlib_doc()),
                                         user, task="codegen", context={"draft": code}, max_tokens=8000)
            code = extract_code(out)
            unresolved = {v for v in unresolved if f'df["{v}"] = None  # TODO' in code}
            self.sub(ctx, "Coder", f"LLM completed the draft ({len(comp.unresolved) - len(unresolved)} TODO rows filled)", "llm")

        # ---- Execute / validate / repair loop
        workdir: Path = ctx.state["workdir"] / "programs"
        issues: list[dict] = []
        out_df = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            res.attempts = attempt
            run = run_program(code, tables_for_job, workdir, ds)
            if run.ok:
                out_df = run.output
                issues = check_against_spec(out_df, spec, ds, unresolved)
                self.sub(ctx, "Executor", f"attempt {attempt}: {len(out_df)} rows x {out_df.shape[1]} cols", "tool")
                bugs = [i for i in issues if i["class"] == "BUILD_BUG" and i["severity"] == "error"]
                self.sub(ctx, "Validator", f"{len(issues)} issues ({len(bugs)} build bugs)",
                         "warning" if issues else "result", issues=issues)
                if not bugs:
                    break
                feedback = json.dumps(bugs, indent=1)
            else:
                self.sub(ctx, "Executor", f"attempt {attempt} crashed: {run.stderr.strip().splitlines()[-1] if run.stderr.strip() else '?'}", "error")
                issues = [{"check": "runtime", "class": "BUILD_BUG", "severity": "error", "variable": "",
                           "message": run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "crash",
                           "count": 0, "examples": [run.stderr[-1500:]]}]
                feedback = run.stderr[-3000:]
            if attempt == MAX_ATTEMPTS:
                break
            new = await ctx.llm.complete(REPAIR_SYSTEM, f"Program:\n```python\n{code}```\n\nProblems:\n{feedback}",
                                         task="repair", context={"code": code}, max_tokens=8000)
            new = extract_code(new)
            if new.strip() == code.strip():
                self.sub(ctx, "Repairer", "no automatic repair available" + (" (offline mode)" if ctx.llm.offline else ""), "warning")
                break
            code = new
            self.sub(ctx, "Repairer", f"patched program, re-running (attempt {attempt + 1})", "llm")

        (workdir / f"{ds.lower()}.py").write_text(code, encoding="utf-8")
        res.program = code
        res.issues = issues
        if out_df is None:
            res.status = "failed"
            ctx.state["built"][ds] = None
            return res

        outdir: Path = ctx.state["workdir"] / "datasets"
        outdir.mkdir(parents=True, exist_ok=True)
        out_df.to_csv(outdir / f"{ds.lower()}.csv", index=False)
        ctx.state["built"][ds] = out_df
        res.rows, res.columns = len(out_df), list(out_df.columns)
        res.preview = json.loads(out_df.head(25).to_json(orient="records", date_format="iso"))
        errors = [i for i in issues if i["severity"] == "error"]
        res.status = "failed" if any(i["class"] == "BUILD_BUG" for i in errors) else "warnings" if issues else "ok"

        # ---- blinded reference comparison (Validator only)
        ref = ctx.state.get("references", {}).get(ds)
        if ref is not None:
            meta = spec.dataset(ds)
            res.concordance = compare_to_reference(out_df, ref, meta.keys if meta else [])
            self.sub(ctx, "Validator", f"reference concordance {res.concordance['concordance_pct']}% "
                     f"({res.concordance['cells_equal']}/{res.concordance['cells']} cells)", "result")
        return res
