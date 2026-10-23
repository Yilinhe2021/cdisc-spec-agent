"""Read a spec workbook (xlsx) or a single variable-level CSV into a `Spec`.

Real-world specs never share a template, so column and sheet names are matched
through alias tables instead of fixed positions. Anything we don't recognise is
kept in `SpecVariable.extra` so nothing is silently dropped.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..models import CodelistTerm, Spec, SpecDataset, SpecVariable, Standard

SHEET_ALIASES = {
    "datasets": ["datasets", "dataset", "domains", "tables", "dataset metadata"],
    "variables": ["variables", "variable", "variable metadata", "spec", "mapping", "specification"],
    "codelists": ["codelists", "codelist", "controlled terms", "ct", "terminology", "value list"],
}

VAR_COLS = {
    "dataset": ["dataset", "domain", "table", "dataset name"],
    "variable": ["variable", "variable name", "name", "varname"],
    "label": ["label", "variable label", "description"],
    "type": ["type", "data type", "datatype"],
    "length": ["length", "len", "size"],
    "origin": ["origin", "source type"],
    "derivation": ["derivation", "source/derivation", "source / derivation", "mapping rule",
                   "mapping", "method", "computation method", "comment", "source"],
    "codelist": ["codelist", "controlled terms", "controlled terms or format", "ct", "format"],
    "core": ["core", "required", "req/exp/perm", "mandatory"],
    "key_seq": ["key", "key sequence", "keyseq", "key seq"],
}

DS_COLS = {
    "name": ["dataset", "name", "domain", "dataset name"],
    "label": ["label", "description", "dataset label"],
    "structure": ["structure", "class", "class/structure"],
    "keys": ["keys", "key variables", "key"],
    "sources": ["sources", "source", "source datasets", "input"],
}

CL_COLS = {
    "codelist": ["codelist", "codelist name", "id", "name"],
    "code": ["code", "term", "coded value", "value", "submission value"],
    "decode": ["decode", "decoded value", "decoded", "description"],
}


def _norm(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _match_columns(columns: list[str], table: dict[str, list[str]]) -> dict[str, str]:
    """Map logical field -> actual column using exact alias match first, then prefix."""
    normed = {_norm(c): c for c in columns}
    out: dict[str, str] = {}
    used: set[str] = set()
    for field, aliases in table.items():
        for a in aliases:
            if a in normed and normed[a] not in used:
                out[field] = normed[a]
                used.add(normed[a])
                break
    for field, aliases in table.items():
        if field in out:
            continue
        for nc, c in normed.items():
            if c not in used and any(nc.startswith(a) for a in aliases):
                out[field] = c
                used.add(c)
                break
    return out


def _cell(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    s = str(v)
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


def _int(v: object) -> int | None:
    s = _cell(v).strip()
    try:
        return int(float(s)) if s else None
    except ValueError:
        return None


def _find_sheet(sheets: dict[str, pd.DataFrame], logical: str) -> str | None:
    by_norm = {_norm(n): n for n in sheets}
    for a in SHEET_ALIASES[logical]:
        if a in by_norm:
            return by_norm[a]
    for n, real in by_norm.items():
        if any(a in n for a in SHEET_ALIASES[logical]):
            return real
    return None


def parse_variables(df: pd.DataFrame, header_row: int = 1) -> list[SpecVariable]:
    cols = _match_columns([str(c) for c in df.columns], VAR_COLS)
    if "variable" not in cols:
        raise ValueError(f"Could not find a variable-name column among {list(df.columns)}")
    out: list[SpecVariable] = []
    for i, rec in enumerate(df.to_dict("records")):
        name = _cell(rec.get(cols["variable"])).strip()
        if not name:
            continue
        extra = {str(k): _cell(v) for k, v in rec.items() if k not in cols.values() and _cell(v)}
        out.append(SpecVariable(
            row=header_row + 1 + i,
            dataset=_cell(rec.get(cols.get("dataset", ""), "")).strip().upper(),
            variable=name,
            label=_cell(rec.get(cols.get("label", ""), "")),
            type=_cell(rec.get(cols.get("type", ""), "")).strip(),
            length=_int(rec.get(cols.get("length", ""))),
            origin=_cell(rec.get(cols.get("origin", ""), "")).strip(),
            derivation=_cell(rec.get(cols.get("derivation", ""), "")).strip(),
            codelist=_cell(rec.get(cols.get("codelist", ""), "")).strip(),
            core=_cell(rec.get(cols.get("core", ""), "")).strip(),
            key_seq=_int(rec.get(cols.get("key_seq", ""))),
            extra=extra,
        ))
    return out


def parse_datasets(df: pd.DataFrame) -> list[SpecDataset]:
    cols = _match_columns([str(c) for c in df.columns], DS_COLS)
    out = []
    for i, rec in enumerate(df.to_dict("records")):
        name = _cell(rec.get(cols.get("name", ""), "")).strip().upper()
        if not name:
            continue
        split = lambda s: [t.strip().upper() for t in re.split(r"[,;\s]+", s) if t.strip()]  # noqa: E731
        out.append(SpecDataset(
            name=name,
            label=_cell(rec.get(cols.get("label", ""), "")),
            structure=_cell(rec.get(cols.get("structure", ""), "")),
            keys=split(_cell(rec.get(cols.get("keys", ""), ""))),
            sources=split(_cell(rec.get(cols.get("sources", ""), ""))),
            row=i + 2,
        ))
    return out


def parse_codelists(df: pd.DataFrame) -> dict[str, list[CodelistTerm]]:
    cols = _match_columns([str(c) for c in df.columns], CL_COLS)
    out: dict[str, list[CodelistTerm]] = {}
    for i, rec in enumerate(df.to_dict("records")):
        cl = _cell(rec.get(cols.get("codelist", ""), "")).strip()
        code = _cell(rec.get(cols.get("code", ""), "")).strip()
        if not cl or code == "":
            continue
        out.setdefault(cl, []).append(CodelistTerm(
            codelist=cl, code=code, decode=_cell(rec.get(cols.get("decode", ""), "")), row=i + 2))
    return out


def load_spec(path: str | Path, standard: Standard, source_name: str | None = None) -> Spec:
    path = Path(path)
    name = source_name or path.name
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        return Spec(standard=standard, source_name=name, variables=parse_variables(df))

    sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    var_sheet = _find_sheet(sheets, "variables")
    if var_sheet is None:
        # fall back: the sheet with most rows that has a variable column
        for n, df in sorted(sheets.items(), key=lambda kv: -len(kv[1])):
            if "variable" in _match_columns([str(c) for c in df.columns], VAR_COLS):
                var_sheet = n
                break
    if var_sheet is None:
        raise ValueError(f"No variable-level sheet found in {path.name}; sheets: {list(sheets)}")

    spec = Spec(standard=standard, source_name=name, variables=parse_variables(sheets[var_sheet]))
    spec.sheet_names["variables"] = var_sheet
    if (ds := _find_sheet(sheets, "datasets")) and ds != var_sheet:
        spec.datasets = parse_datasets(sheets[ds])
        spec.sheet_names["datasets"] = ds
    if (cl := _find_sheet(sheets, "codelists")) and cl != var_sheet:
        spec.codelists = parse_codelists(sheets[cl])
        spec.sheet_names["codelists"] = cl
    return spec
