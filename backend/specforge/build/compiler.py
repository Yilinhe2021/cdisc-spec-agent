"""Deterministic spec -> Python compiler for a controlled derivation vocabulary.

Strategy: "compiler first, LLM for the long tail". Rows written in a recognised
phrase (copy, constant, concatenate, ISO date, numeric date, study day, age,
sequence, codelist map, if/else) compile to exact code with no model involved —
literals and codelists are copied from the spec verbatim, never re-typed. Rows the
compiler does not understand become explicit TODO stubs that the Coder agent
(LLM) fills in; offline they stay stubs and the Validator reports them.

Supported phrases (case-insensitive):
  DS.VAR [merged by KEY[, KEY]]
  Set to 'X' | Set to 12
  Concatenate A, '-', B
  ISO 8601 date of REF
  Numeric date of REF
  Age in completed years from REF to REF
  Study day of REF relative to REF [merged by KEY]
  Sequence number within A[, B] ordered by C[, D]
  Map REF using codelist CL[; if missing set to 'X']
  Set to VAL if COND, else VAL        (COND: REF op VAL | REF is [not] missing; VAL: 'x' | number | null | REF)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Spec, SpecVariable

REF = r"[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)?"
VAL = r"'[^']*'|-?\d+(?:\.\d+)?|null|missing|" + REF
OPS = {">=": ">=", "<=": "<=", ">": ">", "<": "<", "=": "==", "eq": "==", "ne": "!=", "^=": "!=", "!=": "!=",
       "ge": ">=", "le": "<=", "gt": ">", "lt": "<"}


@dataclass
class Compiled:
    code: str
    compiled: list[str] = field(default_factory=list)
    unresolved: list[SpecVariable] = field(default_factory=list)
    base: str = ""
    deps: list[str] = field(default_factory=list)


class _Ctx:
    def __init__(self, spec: Spec, dataset: str, base: str, inputs: dict[str, list[str]]):
        self.spec, self.dataset, self.base, self.inputs = spec, dataset, base, inputs
        self.own = {v.variable for v in spec.vars_of(dataset)}
        self.deps: set[str] = set()       # own variables this row needs first
        self.sources: set[str] = set()    # other datasets used

    def ref(self, token: str, by: list[str] | None = None) -> str:
        if "." in token:
            ds, var = token.split(".", 1)
            if ds == self.dataset:
                self.deps.add(var)
                return f'df["{var}"]'
            if ds == self.base:
                return f'base["{var}"]'
            self.sources.add(ds)
            keys = by or ["USUBJID"]
            self.deps.update(k for k in keys if k in self.own)
            return f'merge_var(df, src["{ds}"], "{var}", by={keys!r})'
        if token in self.own:
            self.deps.add(token)
            return f'df["{token}"]'
        if token in self.inputs.get(self.base, []):
            return f'base["{token}"]'
        raise KeyError(token)

    def val(self, token: str) -> str:
        token = token.strip()
        if token.startswith("'"):
            return repr(token[1:-1])
        if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            return token
        if token.lower() in ("null", "missing"):
            return "None"
        return self.ref(token)


def _split_args(s: str) -> list[str]:
    return [a.strip() for a in re.findall(r"'[^']*'|[^,]+", s) if a.strip()]


def _keys(s: str | None) -> list[str] | None:
    return [k.strip().upper() for k in re.split(r"[,\s]+(?:and\s+)?", s) if k.strip()] if s else None


def compile_row(v: SpecVariable, c: _Ctx) -> str | None:
    d = re.sub(r"\s+", " ", v.derivation.strip().rstrip("."))
    m = re.fullmatch(r"(?i)(?:set to|assigned?(?: to)?)\s+('[^']*'|-?\d+(?:\.\d+)?)", d)
    if m:
        return f"{c.val(m.group(1))}"
    m = re.fullmatch(rf"({REF}\.{REF})(?:\s+merged by\s+([A-Z, ]+))?", d)
    if m:
        return c.ref(m.group(1), _keys(m.group(2)))
    m = re.fullmatch(r"(?i)concatenat(?:e|ion of)\s+(.+)", d)
    if m:
        return "concat(" + ", ".join(c.val(a) for a in _split_args(m.group(1).replace(" and ", ", "))) + ")"
    m = re.fullmatch(rf"(?i)iso 8601 date of ({REF})", d)
    if m:
        return f"iso_date({c.ref(m.group(1))})"
    m = re.fullmatch(rf"(?i)numeric date of ({REF})(?:\s+merged by\s+([A-Z, ]+))?(?:;.*)?", d)
    if m:
        return f"num_date({c.ref(m.group(1), _keys(m.group(2)))})"
    m = re.fullmatch(rf"(?i)age in completed years from ({REF}) to ({REF})", d)
    if m:
        return f"age_years({c.ref(m.group(1))}, {c.ref(m.group(2))})"
    m = re.match(rf"(?i)study day of ({REF}) relative to ({REF})(?:\s+merged by\s+([A-Z, ]+?))?(?=[:;.,]|$)", d)
    if m:
        return f"study_day({c.ref(m.group(1))}, {c.ref(m.group(2), _keys(m.group(3)))})"
    m = re.fullmatch(r"(?i)sequence number within ([A-Z0-9_, ]+?) ordered by ([A-Z0-9_, ]+)", d)
    if m:
        by, order = _keys(m.group(1)), _keys(m.group(2))
        for k in by + order:
            c.ref(k)
        return f"seq_number(df, by={by!r}, order={order!r})"
    m = re.fullmatch(rf"(?i)map ({REF}) using codelist (\w+)(?:;\s*if missing set to ('[^']*'))?", d)
    if m:
        cl = m.group(2)
        if cl not in c.spec.codelists:
            return None
        expr = f'map_codelist({c.ref(m.group(1))}, CODELISTS[{cl!r}])'
        if m.group(3):
            src = c.ref(m.group(1))
            expr = f"where(is_missing({src}), {c.val(m.group(3))}, {expr})"
        return expr
    m = re.fullmatch(rf"(?i)set to ({VAL}) if ({REF}) (is not missing|is missing|>=|<=|>|<|=|!=|\^=|ne|eq|ge|le|gt|lt) ?({VAL})?,? "
                     rf"(?:else|otherwise),? (?:set to )?({VAL})", d)
    if m:
        then_, lhs, op, rhs, else_ = m.groups()
        left = c.ref(lhs)
        if op.lower() == "is missing":
            cond = f"is_missing({left})"
        elif op.lower() == "is not missing":
            cond = f"not_missing({left})"
        else:
            cond = f"({left} {OPS[op.lower()]} {c.val(rhs)})"
        return f"where({cond}, {c.val(then_)}, {c.val(else_)})"
    return None


def choose_base(spec: Spec, dataset: str, inputs: dict[str, list[str]]) -> str:
    meta = spec.dataset(dataset)
    if meta:
        for s in meta.sources:
            if s in inputs:
                return s
    counts: dict[str, int] = {}
    for v in spec.vars_of(dataset):
        if "merged by" in v.derivation.lower():
            continue
        for ds, _ in re.findall(r"\b([A-Z][A-Z0-9_]*)\.([A-Z][A-Z0-9_]*)", v.derivation):
            if ds in inputs and ds != dataset:
                counts[ds] = counts.get(ds, 0) + 1
    if not counts:
        raise ValueError(f"Cannot determine the source table for {dataset}; list it in the Datasets sheet 'Sources'.")
    return max(counts, key=counts.get)


def compile_dataset(spec: Spec, dataset: str, inputs: dict[str, list[str]], spec_name: str = "") -> Compiled:
    base = choose_base(spec, dataset, inputs)
    rows = spec.vars_of(dataset)
    exprs: dict[str, str | None] = {}
    deps: dict[str, set[str]] = {}
    sources: set[str] = {base}
    for v in rows:
        c = _Ctx(spec, dataset, base, inputs)
        try:
            exprs[v.variable] = compile_row(v, c)
        except KeyError:
            exprs[v.variable] = None
        deps[v.variable] = c.deps - {v.variable}
        sources |= c.sources

    # topological order within the dataset (spec order as tie-breaker)
    order, done = [], set()
    def visit(name: str, stack: tuple = ()):
        if name in done or name in stack or name not in deps:
            return
        for d in sorted(deps[name], key=lambda n: [r.variable for r in rows].index(n) if n in deps else 0):
            visit(d, stack + (name,))
        done.add(name)
        order.append(name)
    for v in rows:
        visit(v.variable)

    used_cl = sorted({m for e in exprs.values() if e for m in re.findall(r"CODELISTS\['(\w+)'\]", e)})
    codelists = {cl: {t.code: t.decode for t in spec.codelists[cl]} for cl in used_cl}
    by_name = {v.variable: v for v in rows}
    lines = []
    compiled, unresolved = [], []
    for name in order:
        v = by_name[name]
        lines.append(f"    # [row {v.row}] {v.variable} ({v.origin or '?'}): {v.derivation.strip() or '(no derivation)'}")
        if exprs[name]:
            expr = exprs[name]
            if v.type.lower().startswith("num") and re.fullmatch(r'(base\[".*?"\]|merge_var\(.*\))', expr):
                expr = f"to_num({expr})"  # inputs read from text files arrive as strings
            lines.append(f'    df["{name}"] = {expr}')
            compiled.append(name)
        else:
            lines.append(f'    df["{name}"] = None  # TODO(coder): not in compiler vocabulary - implement from spec text above')
            unresolved.append(v)

    header = f'''"""SpecForge generated program: {dataset} ({spec.standard})
Spec      : {spec_name or spec.source_name}
Base table: {base}   Other inputs: {sorted(sources - {base}) or "-"}
Compiled  : {len(compiled)}/{len(rows)} variables by the deterministic compiler

Regenerate from the spec instead of editing by hand.
"""
from specforge.runtime.stdlib import *  # noqa: F401,F403

DATASET = {dataset!r}
COLUMNS = {[v.variable for v in rows]!r}
TYPES = {{{", ".join(f"{v.variable!r}: {v.type!r}" for v in rows)}}}
CODELISTS = {codelists!r}


def build(src: dict) -> "pd.DataFrame":
    base = src[{base!r}].copy()
    df = pd.DataFrame(index=base.index)
'''
    code = header + "\n".join(lines) + "\n    return finalize(df, COLUMNS, TYPES)\n"
    return Compiled(code=code, compiled=compiled, unresolved=unresolved, base=base, deps=sorted(sources))
