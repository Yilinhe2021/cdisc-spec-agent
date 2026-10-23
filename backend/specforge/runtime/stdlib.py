"""Helper library imported by every generated program.

Generated code should call these instead of re-implementing date parsing, study
day arithmetic etc. Each function is small, documented and unit-tested, which
keeps generated programs short, consistent between datasets and reviewable —
and stops the classic drift where every program has its own slightly different
copy of the same helper.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

__all__ = ["pd", "np", "iso_date", "num_date", "age_years", "study_day", "seq_number", "map_codelist",
           "merge_var", "concat", "to_num", "is_missing", "not_missing", "where", "finalize", "clean_text"]

_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
_UNK = {"UN", "UNK", "UK", "NK", "XX", "--", ""}


def clean_text(s: pd.Series) -> pd.Series:
    """Unicode-normalise (NFKC), turn NBSP into spaces and strip. Missing -> ''."""
    return s.map(lambda x: "" if is_scalar_missing(x) else unicodedata.normalize("NFKC", str(x)).replace("\xa0", " ").strip())


def is_scalar_missing(x) -> bool:
    return x is None or (isinstance(x, float) and np.isnan(x)) or x is pd.NaT or (isinstance(x, str) and x.strip() == "") \
        or (not isinstance(x, str) and pd.isna(x))


def is_missing(s: pd.Series) -> pd.Series:
    return s.map(is_scalar_missing).astype(bool)


def not_missing(s: pd.Series) -> pd.Series:
    return ~is_missing(s)


def _iso_one(x) -> str:
    if is_scalar_missing(x):
        return ""
    if isinstance(x, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(x).strftime("%Y-%m-%d")
    s = str(x).strip().upper()
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?(?:[T ](\d{2}:\d{2}(?::\d{2})?))?", s)
    if m:
        y, mo, d, t = m.groups()
        out = y + (f"-{int(mo):02d}" if mo else "") + (f"-{int(d):02d}" if mo and d else "")
        return out + (f"T{t}" if t and d else "")
    m = re.fullmatch(r"([A-Z0-9-]{0,3})[-/ ]([A-Z-]{2,3})[-/ ](\d{4})", s)  # DD-MON-YYYY with UNK parts
    if m:
        d, mon, y = m.groups()
        if mon in _UNK or mon not in _MONTHS:
            return y
        if d in _UNK or not d.isdigit():
            return f"{y}-{_MONTHS[mon]:02d}"
        return f"{y}-{_MONTHS[mon]:02d}-{int(d):02d}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)  # MM/DD/YYYY
    if m:
        mo, d, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    raise ValueError(f"Unrecognised date value: {x!r}")


def iso_date(s: pd.Series) -> pd.Series:
    """Raw date text -> ISO 8601 text. Partial dates are truncated (never imputed); missing -> ''."""
    return s.map(_iso_one)


def num_date(s: pd.Series) -> pd.Series:
    """ISO text or datetime -> numeric date (pandas datetime). Partial or missing -> NaT."""
    def one(x):
        if is_scalar_missing(x):
            return pd.NaT
        if isinstance(x, pd.Timestamp):
            return x.normalize()
        v = _iso_one(x)
        return pd.Timestamp(v[:10]) if len(v) >= 10 else pd.NaT
    return pd.to_datetime(s.map(one))


def age_years(birth: pd.Series, ref: pd.Series) -> pd.Series:
    """Completed years between two dates (birthday not yet reached -> subtract one)."""
    b, r = num_date(birth), num_date(ref)
    years = r.dt.year - b.dt.year - ((r.dt.month < b.dt.month) | ((r.dt.month == b.dt.month) & (r.dt.day < b.dt.day))).astype(int)
    return years.where(b.notna() & r.notna()).astype("Float64")


def study_day(date: pd.Series, ref: pd.Series) -> pd.Series:
    """date - ref + 1 when date >= ref, else date - ref (there is no day 0). Missing/partial -> missing."""
    d, r = num_date(date), num_date(ref)
    diff = (d - r).dt.days
    return diff.where(diff < 0, diff + 1).where(d.notna() & r.notna()).astype("Float64")


def seq_number(df: pd.DataFrame, by: list[str], order: list[str]) -> pd.Series:
    """1..n within `by`, ordered by `order` (stable; ties keep input order)."""
    tmp = df[by + order].copy()
    tmp["_pos"] = np.arange(len(df))
    tmp = tmp.sort_values(by + order + ["_pos"], kind="mergesort")
    seq = tmp.groupby(by, sort=False).cumcount() + 1
    return seq.reindex(df.index).astype("Float64")


def map_codelist(s: pd.Series, terms: dict[str, str], strict: bool = True) -> pd.Series:
    """Map raw values to codelist codes. `terms` maps code -> decode. Matches code or decode, case-insensitively.
    Unmapped non-missing values raise (strict) so silent data loss is impossible."""
    lookup = {}
    for code, decode in terms.items():
        lookup[str(code).strip().upper()] = code
        if decode:
            lookup[str(decode).strip().upper()] = code
    def one(x):
        if is_scalar_missing(x):
            return ""
        k = str(x).strip().upper()
        if k in lookup:
            return lookup[k]
        if strict:
            raise ValueError(f"Value {x!r} not found in codelist {sorted(terms)}")
        return str(x)
    return s.map(one)


def merge_var(df: pd.DataFrame, other: pd.DataFrame, var: str, by: list[str] | str = "USUBJID") -> pd.Series:
    """Look up `var` from `other` by key(s) without changing row count; errors on duplicate keys."""
    by = [by] if isinstance(by, str) else list(by)
    right = other[by + [var]]
    if right.duplicated(by).any():
        raise ValueError(f"merge_var: keys {by} are not unique in source while fetching {var}")
    merged = df[by].merge(right, on=by, how="left")
    merged.index = df.index
    return merged[var]


def concat(*parts, sep: str = "") -> pd.Series:
    """Concatenate Series and/or string literals element-wise."""
    series = [p for p in parts if isinstance(p, pd.Series)]
    idx = series[0].index if series else None
    out = pd.Series([""] * len(idx), index=idx) if idx is not None else ""
    for i, p in enumerate(parts):
        piece = clean_text(p) if isinstance(p, pd.Series) else str(p)
        out = out + (sep if i and sep else "") + piece
    return out


def to_num(s: pd.Series) -> pd.Series:
    """Numeric view of a column read as text: ISO date strings -> dates, numbers -> floats, else NaN."""
    if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
        return s
    vals = s[not_missing(s)].astype(str)
    if len(vals) and vals.str.fullmatch(r"\d{4}-\d{2}-\d{2}.*").all():
        return num_date(s)
    return pd.to_numeric(s, errors="coerce")


def where(cond: pd.Series, a, b) -> pd.Series:
    """Element-wise if/else that keeps pandas dtypes; a/b may be scalars or Series. None means missing."""
    a_s = a if isinstance(a, pd.Series) else pd.Series([a] * len(cond), index=cond.index, dtype=object)
    b_s = b if isinstance(b, pd.Series) else pd.Series([b] * len(cond), index=cond.index, dtype=object)
    return a_s.where(cond.fillna(False).astype(bool), b_s)


def finalize(df: pd.DataFrame, columns: list[str], types: dict[str, str]) -> pd.DataFrame:
    """Keep spec columns in spec order and coerce storage types. Char missing -> ''. Num stays numeric/datetime."""
    out = pd.DataFrame(index=df.index)
    for c in columns:
        col = df[c] if c in df.columns else pd.Series([None] * len(df), index=df.index)
        if types.get(c, "Char").lower().startswith("char"):
            out[c] = col.map(lambda x: "" if is_scalar_missing(x) else (x.strftime("%Y-%m-%d") if isinstance(x, pd.Timestamp) else str(x)))
        elif pd.api.types.is_datetime64_any_dtype(col):
            out[c] = col
        else:
            out[c] = pd.to_numeric(col, errors="coerce")
    return out.reset_index(drop=True)
