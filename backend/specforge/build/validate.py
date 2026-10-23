"""Validation of a generated dataset.

1. `check_against_spec` — conformance of the output to its own spec (always runs).
2. `compare_to_reference` — blinded double-programming check: cell-by-cell
   concordance against an independently produced reference dataset. Only the
   Validator ever sees reference data; the Coder never does.

Every issue is classified so the repair loop knows what to do with it:
  BUILD_BUG       the program is wrong -> send back to the Coder
  SPEC_GAP        the spec does not say enough -> report to the user, do not "fix" by guessing
  DATA_ISSUE      the input data does not fit the spec (e.g. unmapped codelist value)
"""
from __future__ import annotations

import unicodedata
from typing import Any

import numpy as np
import pandas as pd

from ..models import Spec
from ..runtime.stdlib import is_missing


def _issue(check: str, kind: str, severity: str, message: str, variable: str = "", count: int = 0,
           examples: list | None = None) -> dict[str, Any]:
    return {"check": check, "class": kind, "severity": severity, "variable": variable, "message": message,
            "count": int(count), "examples": [str(e) for e in (examples or [])][:5]}


def check_against_spec(df: pd.DataFrame, spec: Spec, dataset: str, unresolved: set[str] | None = None) -> list[dict]:
    issues: list[dict] = []
    unresolved = unresolved or set()
    rows = spec.vars_of(dataset)
    expected = [v.variable for v in rows]
    missing = [c for c in expected if c not in df.columns]
    extra = [c for c in df.columns if c not in expected]
    if missing:
        issues.append(_issue("columns", "BUILD_BUG", "error", f"Missing columns: {missing}", count=len(missing)))
    if extra:
        issues.append(_issue("columns", "BUILD_BUG", "warning", f"Columns not in spec: {extra}", count=len(extra)))
    if len(df) == 0:
        issues.append(_issue("rows", "BUILD_BUG", "error", "Dataset has 0 rows"))
        return issues

    for v in rows:
        if v.variable not in df.columns:
            continue
        col = df[v.variable]
        miss = is_missing(col)
        if v.variable in unresolved:
            issues.append(_issue("derivation", "SPEC_GAP", "error",
                                 f"{v.variable}: derivation could not be implemented from the spec text", v.variable,
                                 count=len(df)))
            continue
        if miss.all() and v.core.lower().startswith(("req", "exp")):
            issues.append(_issue("populated", "BUILD_BUG", "error", f"{v.variable} is entirely empty", v.variable,
                                 count=len(df)))
        if v.core.lower().startswith("req") and miss.any() and not miss.all():
            issues.append(_issue("required", "DATA_ISSUE", "warning", f"Required {v.variable} is missing in {int(miss.sum())} rows",
                                 v.variable, int(miss.sum())))
        is_num_type = v.type.lower().startswith("num")
        if is_num_type and not (pd.api.types.is_numeric_dtype(col) or pd.api.types.is_datetime64_any_dtype(col)):
            issues.append(_issue("type", "BUILD_BUG", "error", f"{v.variable} should be numeric, got {col.dtype}", v.variable))
        if not is_num_type and v.length:
            too_long = col.astype(str).str.len() > v.length
            if too_long.any():
                issues.append(_issue("length", "DATA_ISSUE", "warning",
                                     f"{v.variable}: {int(too_long.sum())} values exceed length {v.length}",
                                     v.variable, int(too_long.sum()), col[too_long].unique().tolist()))
        terms = spec.codelists.get(v.codelist)
        if terms and not is_num_type:
            allowed = {t.code for t in terms}
            bad = ~miss & ~col.astype(str).isin(allowed)
            if bad.any():
                issues.append(_issue("codelist", "BUILD_BUG", "error",
                                     f"{v.variable}: {int(bad.sum())} values not in codelist {v.codelist}",
                                     v.variable, int(bad.sum()), col[bad].unique().tolist()))

    meta = spec.dataset(dataset)
    keys = [k for k in (meta.keys if meta else []) if k in df.columns]
    if keys:
        dup = df.duplicated(keys, keep=False)
        if dup.any():
            issues.append(_issue("keys", "BUILD_BUG", "error", f"Keys {keys} are not unique ({int(dup.sum())} rows)",
                                 count=int(dup.sum())))
    return issues


# ------------------------------------------------------------------ concordance
def _norm(x: Any) -> Any:
    # pd.NA (nullable Int64/Float64) must count as missing too: str(pd.NA) == "<NA>" would never match ""
    if x is None or x is pd.NA or x is pd.NaT or (isinstance(x, float) and np.isnan(x)):
        return ""
    if isinstance(x, pd.Timestamp):
        return x.strftime("%Y-%m-%d")
    if isinstance(x, (int, float, np.integer, np.floating)):
        return round(float(x), 8)
    s = unicodedata.normalize("NFKC", str(x)).replace("\xa0", " ").strip()
    try:
        return round(float(s), 8) if s and s.replace(".", "", 1).lstrip("-").isdigit() else s
    except ValueError:
        return s


def compare_to_reference(out: pd.DataFrame, ref: pd.DataFrame, keys: list[str]) -> dict[str, Any]:
    keys = [k for k in keys if k in out.columns and k in ref.columns]
    common = [c for c in ref.columns if c in out.columns]
    a = out[common].map(_norm)
    b = ref[common].map(_norm)
    if keys:
        a, b = a.set_index(keys), b.set_index(keys)
        if a.index.has_duplicates or b.index.has_duplicates:
            keys = []
            a, b = out[common].map(_norm).reset_index(drop=True), ref[common].map(_norm).reset_index(drop=True)
    only_out = a.index.difference(b.index)
    only_ref = b.index.difference(a.index)
    idx = a.index.intersection(b.index)
    a, b = a.loc[idx], b.loc[idx]
    per_var, mismatches, total, equal = {}, [], 0, 0
    for c in a.columns:
        eq = (a[c] == b[c])
        per_var[c] = round(100 * eq.mean(), 3) if len(eq) else 100.0
        total += len(eq)
        equal += int(eq.sum())
        for k in eq[~eq].index[:3]:
            mismatches.append({"key": str(k), "variable": c, "generated": str(a.at[k, c]), "reference": str(b.at[k, c])})
    return {
        "keys": keys, "matched_rows": len(idx), "rows_only_in_generated": len(only_out),
        "rows_only_in_reference": len(only_ref), "columns_compared": len(common),
        "columns_missing": [c for c in ref.columns if c not in out.columns],
        "cells": total, "cells_equal": equal, "concordance_pct": round(100 * equal / total, 3) if total else 0.0,
        "per_variable": per_var, "mismatch_examples": mismatches[:25],
    }
