"""Evaluation harness.

  1. Seeded defects   - recall on the hand-written defects in examples/*/spec_draft.xlsx (answer_key.json)
  2. Mutation testing - inject N random defects of known type into the clean specs, measure per-operator recall
  3. False positives  - findings on the clean specs (should be ~0)
  4. Build accuracy   - cell-level concordance of generated datasets vs independently coded references

Usage:  python eval/run_eval.py [--llm mock|anthropic|openai] [--mutations 40]
Writes eval/RESULTS.md.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from specforge.build.pipeline import read_table, run_build  # noqa: E402
from specforge.llm import get_provider  # noqa: E402
from specforge.models import Finding, Spec, SpecVariable  # noqa: E402
from specforge.qc.pipeline import run_qc  # noqa: E402
from specforge.spec.parser import load_spec  # noqa: E402

EX = ROOT / "examples"


def matches(f: Finding, dataset: str, variable: str, expect: str) -> bool:
    if f.dataset != dataset:
        return False
    if variable != "(dataset)" and f.variable != variable:
        return False
    tags = {f.rule_id, f.category.value, *[m.split(":")[1] for m in f.merged_from]}
    if expect in tags:
        return True
    # LLM agents use generic rule ids; accept category match for agent-level expectations
    return expect in {"clarity", "conformance", "consistency", "completeness", "terminology"} and f.category.value == expect


# ------------------------------------------------------------------ mutations
def _derived(spec: Spec, pred=lambda v: True) -> list[SpecVariable]:
    return [v for v in spec.variables if v.origin.lower() in ("derived", "assigned") and pred(v)]


def m_long_label(spec, rng):
    v = rng.choice(spec.variables)
    v.label = v.label + " as Collected on the Case Report Form Page"  # always > 40
    return v, "GEN-004"


def m_bad_name(spec, rng):
    v = rng.choice([v for v in spec.variables if len(v.variable) <= 6])
    v.variable = v.variable + "_X"
    return v, "GEN-002"


def m_drop_derivation(spec, rng):
    v = rng.choice(_derived(spec))
    v.derivation = ""
    return v, "GEN-007"


def m_bad_type(spec, rng):
    v = rng.choice(spec.variables)
    v.type = rng.choice(["Date", "Integer?", "Text/Num"])
    return v, "GEN-005"


def m_undefined_codelist(spec, rng):
    v = rng.choice([v for v in spec.variables if v.codelist] or spec.variables)
    v.codelist = "CL_" + v.variable + "_V2"
    return v, "GEN-009"


def m_vague(spec, rng):
    v = rng.choice(_derived(spec))
    v.derivation += rng.choice(["; handle exceptions as appropriate", " (TBD for screen failures)", ", etc."])
    return v, "clarity"


def m_drop_else(spec, rng):
    cands = _derived(spec, lambda v: ", else" in v.derivation)
    if not cands:
        return None
    v = rng.choice(cands)
    v.derivation = v.derivation.split(", else")[0]
    return v, "clarity"


def m_bad_literal(spec, rng):
    cands = [v for v in spec.variables if v.codelist in spec.codelists and "set to '" in v.derivation.lower()]
    if not cands:
        return None
    v = rng.choice(cands)
    i = v.derivation.lower().index("set to '") + len("set to '")
    j = v.derivation.index("'", i)
    v.derivation = v.derivation[:i] + v.derivation[i:j].lower() + "x" + v.derivation[j:]
    return v, "GEN-014"


def m_dangling_ref(spec, rng):
    names = set(spec.dataset_names())
    cands = [v for v in spec.variables if any(f"{d}." in v.derivation for d in names if d != v.dataset)]
    if not cands:
        return None
    v = rng.choice(cands)
    d = next(d for d in names if f"{d}." in v.derivation and d != v.dataset)
    k = v.derivation.index(f"{d}.") + len(d) + 1
    v.derivation = v.derivation[:k] + "ZZ" + v.derivation[k:]
    return v, "GEN-013"


def m_duplicate(spec, rng):
    v = rng.choice(spec.variables)
    spec.variables.append(v.model_copy(update={"row": max(x.row for x in spec.variables) + 1}))
    return v, "GEN-001"


OPERATORS = [m_long_label, m_bad_name, m_drop_derivation, m_bad_type, m_undefined_codelist, m_vague, m_drop_else,
             m_bad_literal, m_dangling_ref, m_duplicate]


async def mutation_eval(llm, n: int, seed: int = 7):
    rng = random.Random(seed)
    stats = defaultdict(lambda: [0, 0])
    for i in range(n):
        std = rng.choice(["SDTM", "ADaM"])
        spec = load_spec(EX / std.lower() / "spec_final.xlsx", std)
        op = OPERATORS[i % len(OPERATORS)]
        out = op(spec, rng)
        if out is None:
            continue
        v, expect = out
        res = await run_qc(spec, llm)
        hit = any(matches(f, v.dataset, v.variable, expect) for f in res.findings)
        stats[op.__name__[2:]][0] += hit
        stats[op.__name__[2:]][1] += 1
    return stats


async def main(llm_name: str, n_mut: int):
    llm = get_provider(llm_name)
    key = json.loads((EX / "answer_key.json").read_text())
    lines = [f"# Evaluation results\n", f"LLM provider: `{llm.name}` / `{llm.model}` · generated {time.strftime('%Y-%m-%d')}\n"]

    # 1 + 3 ----------------------------------------------------------------
    lines.append("## 1. Seeded defects (examples/*/spec_draft.xlsx)\n")
    lines.append("| Standard | Dataset.Variable | Expected | Detected |\n|---|---|---|---|")
    tot = hit = extra = 0
    fp = {}
    for std in ("SDTM", "ADaM"):
        res = await run_qc(load_spec(EX / std.lower() / "spec_draft.xlsx", std), llm)
        used = set()
        for d in key[std]:
            m = [f for f in res.findings if matches(f, d["dataset"], d["variable"], d["expect"])]
            used |= {f.id for f in m}
            tot += 1
            hit += bool(m)
            lines.append(f"| {std} | {d['dataset']}.{d['variable']} | {d['expect']} | {'yes' if m else '**no**'} |")
        extra += len([f for f in res.findings if f.id not in used])
        clean = await run_qc(load_spec(EX / std.lower() / "spec_final.xlsx", std), llm)
        fp[std] = len(clean.findings)
    lines.append(f"\n**Recall {hit}/{tot} = {100 * hit / tot:.0f}%**. Additional findings on the drafts not in the "
                 f"answer key: {extra} (review manually; may be real).\n")
    lines.append("## 2. False positives on clean specs\n")
    lines.append("| Standard | Findings on spec_final.xlsx |\n|---|---|")
    lines += [f"| {k} | {v} |" for k, v in fp.items()]

    # 2 ------------------------------------------------------------------
    stats = await mutation_eval(llm, n_mut)
    lines.append(f"\n## 3. Mutation testing ({sum(t for _, t in stats.values())} single-defect mutants)\n")
    lines.append("| Operator | Detected | Recall |\n|---|---|---|")
    th = tt = 0
    for op, (h, t) in stats.items():
        th, tt = th + h, tt + t
        lines.append(f"| {op} | {h}/{t} | {100 * h / t:.0f}% |")
    lines.append(f"| **all** | **{th}/{tt}** | **{100 * th / tt:.0f}%** |")

    # 4 ------------------------------------------------------------------
    lines.append("\n## 4. Build accuracy vs independent reference (blinded)\n")
    lines.append("| Standard | Dataset | Status | Rows | Concordance | Cells |\n|---|---|---|---|---|---|")
    with tempfile.TemporaryDirectory() as tmp:
        for std, inp in (("SDTM", "raw"), ("ADaM", "inputs")):
            spec = load_spec(EX / std.lower() / "spec_final.xlsx", std)
            inputs = {f.stem.upper(): read_table(f) for f in (EX / std.lower() / inp).glob("*.csv")}
            refs = {f.stem.upper(): read_table(f) for f in (EX / std.lower() / "reference").glob("*.csv")}
            r = await run_build(spec, inputs, llm, Path(tmp) / std, references=refs)
            for d in r.datasets:
                c = d.concordance or {}
                lines.append(f"| {std} | {d.dataset} | {d.status} | {d.rows} | {c.get('concordance_pct', '-')}% | "
                             f"{c.get('cells_equal', '-')}/{c.get('cells', '-')} |")

    report = "\n".join(lines) + "\n"
    (ROOT / "eval" / "RESULTS.md").write_text(report)
    print(report)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="mock")
    ap.add_argument("--mutations", type=int, default=60)
    a = ap.parse_args()
    asyncio.run(main(a.llm, a.mutations))
