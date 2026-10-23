"""Rules that apply to any tabulation/analysis spec (SDTM and ADaM)."""
from __future__ import annotations

from collections import Counter

from ...models import Category, Severity, Spec
from .engine import NAME_RE, REF_RE, Hit, assigned_literals, is_char, is_derived, is_num, rule

ALLOWED_ORIGINS = {"crf", "collected", "derived", "assigned", "protocol", "edt", "predecessor", "sponsor defined"}


@rule("GEN-001", "Duplicate variable within dataset", severity=Severity.critical, category=Category.consistency,
      rationale="Two rows for the same variable give two competing definitions.")
def dup_vars(spec: Spec):
    seen: Counter = Counter((v.dataset, v.variable) for v in spec.variables)
    for v in spec.variables:
        if seen[(v.dataset, v.variable)] > 1:
            yield Hit(f"{v.variable} is defined {seen[(v.dataset, v.variable)]} times in {v.dataset}.", v,
                      suggestion="Keep one definition and delete the others.")


@rule("GEN-002", "Variable name not submission-compliant", severity=Severity.major,
      kb_query="variable names 8 characters upper case letters digits")
def bad_name(spec: Spec):
    for v in spec.variables:
        if not NAME_RE.match(v.variable):
            why = "longer than 8 characters" if len(v.variable) > 8 else "must be upper-case letters/digits starting with a letter"
            yield Hit(f"Variable name '{v.variable}' is {why}.", v)


@rule("GEN-003", "Dataset name not submission-compliant", severity=Severity.major)
def bad_dsname(spec: Spec):
    for name in spec.dataset_names():
        if name and not NAME_RE.match(name):
            yield Hit(f"Dataset name '{name}' is not 1-8 upper-case letters/digits.", dataset=name)


@rule("GEN-004", "Label missing or longer than 40 characters", severity=Severity.minor,
      kb_query="variable labels 40 characters truncated")
def label_len(spec: Spec):
    for v in spec.variables:
        if not v.label.strip():
            yield Hit(f"{v.variable} has no label.", v, severity=Severity.major)
        elif len(v.label) > 40:
            yield Hit(f"Label of {v.variable} is {len(v.label)} characters (max 40): '{v.label}'.", v,
                      suggestion="Provide the final shortened label in the spec.")


@rule("GEN-005", "Type is not Char or Num", severity=Severity.major, kb_query="data types character numeric")
def bad_type(spec: Spec):
    for v in spec.variables:
        if not (is_char(v) or is_num(v)):
            yield Hit(f"Type of {v.variable} is '{v.type or '(blank)'}'; transport files only store Char or Num.", v)


@rule("GEN-006", "Character variable without a valid length", severity=Severity.minor,
      kb_query="character variables need a length")
def char_len(spec: Spec):
    for v in spec.variables:
        if is_char(v) and (v.length is None or v.length <= 0):
            yield Hit(f"Character variable {v.variable} has no length.", v)
        elif is_char(v) and v.length and v.length > 200:
            yield Hit(f"{v.variable} length {v.length} exceeds 200 characters.", v)


@rule("GEN-007", "Derived/Assigned variable without derivation", severity=Severity.critical,
      category=Category.completeness, kb_query="Derived or Assigned variable without derivation text")
def missing_derivation(spec: Spec):
    for v in spec.variables:
        if is_derived(v) and not v.derivation.strip():
            yield Hit(f"{v.variable} has origin '{v.origin}' but no derivation text.", v,
                      suggestion="Write the rule, including every branch and missing-value handling.")


@rule("GEN-008", "Origin missing or not a recognised value", severity=Severity.minor,
      category=Category.completeness, kb_query="origin values CRF Derived Assigned Protocol eDT Predecessor")
def origin(spec: Spec):
    for v in spec.variables:
        o = v.origin.strip().lower()
        if not o:
            yield Hit(f"{v.variable} has no origin.", v)
        elif o not in ALLOWED_ORIGINS:
            yield Hit(f"Origin '{v.origin}' of {v.variable} is not a standard origin value.", v)


@rule("GEN-009", "Referenced codelist is not defined", severity=Severity.major, category=Category.terminology,
      kb_query="controlled terminology codelist must be defined")
def missing_codelist(spec: Spec):
    if not spec.codelists:
        return
    for v in spec.variables:
        if v.codelist and v.codelist not in spec.codelists and not v.codelist.upper().startswith(("ISO", "MEDDRA", "WHODRUG")):
            yield Hit(f"{v.variable} references codelist '{v.codelist}', which is not defined in the codelist sheet.", v)


@rule("GEN-010", "Duplicate code within a codelist", severity=Severity.major, category=Category.terminology)
def dup_codes(spec: Spec):
    for cl, terms in spec.codelists.items():
        c = Counter(t.code for t in terms)
        for code, n in c.items():
            if n > 1:
                yield Hit(f"Codelist '{cl}' lists code '{code}' {n} times.", dataset="(codelists)",
                          row=next(t.row for t in terms if t.code == code))


@rule("GEN-011", "Declared key variable not in dataset", severity=Severity.critical, category=Category.consistency,
      kb_query="key variables record uniqueness")
def keys_exist(spec: Spec):
    for ds in spec.datasets:
        names = {v.variable for v in spec.vars_of(ds.name)}
        for k in ds.keys:
            if names and k not in names:
                yield Hit(f"Key {k} of {ds.name} is not defined as a variable.", dataset=ds.name, row=ds.row)


@rule("GEN-012", "Dataset listed without variables / variables without dataset entry",
      severity=Severity.major, category=Category.completeness)
def ds_coverage(spec: Spec):
    if not spec.datasets:
        return
    declared = {d.name for d in spec.datasets}
    used = {v.dataset for v in spec.variables}
    for d in spec.datasets:
        if d.name not in used:
            yield Hit(f"Dataset {d.name} is declared but has no variable rows.", dataset=d.name, row=d.row)
    for name in sorted(used - declared):
        yield Hit(f"Variables exist for {name} but it is missing from the dataset sheet.", dataset=name)


@rule("GEN-013", "Derivation references an undefined variable", severity=Severity.major,
      category=Category.consistency, kb_query="cross references dataset variable merge key")
def undefined_refs(spec: Spec):
    in_spec = set(spec.dataset_names())
    for v in spec.variables:
        for ds, var in REF_RE.findall(v.derivation):
            if ds in in_spec and not spec.find(ds, var):
                yield Hit(f"{v.variable} uses {ds}.{var}, which is not defined in the spec.", v)


@rule("GEN-014", "Assigned literal not in the variable's codelist", severity=Severity.critical,
      category=Category.terminology, kb_query="literal values must match codelist exactly")
def literal_vs_codelist(spec: Spec):
    for v in spec.variables:
        terms = spec.codelists.get(v.codelist)
        if not terms:
            continue
        codes = {t.code for t in terms}
        for lit in assigned_literals(v):
            if lit and lit not in codes:
                near = next((c for c in codes if c.lower() == lit.lower()), None)
                hint = f" (did you mean '{near}'? case differs)" if near else ""
                yield Hit(f"{v.variable} is assigned '{lit}', which is not in codelist {v.codelist} "
                          f"{sorted(codes)}{hint}.", v)


@rule("GEN-015", "Required variable is permitted to be missing", severity=Severity.minor,
      category=Category.consistency)
def req_nullable(spec: Spec):
    for v in spec.variables:
        if v.core.lower().startswith("req") and any(
                p in v.derivation.lower() for p in ("else missing", "otherwise missing", "else null", "leave blank", "else blank")):
            yield Hit(f"{v.variable} is Required but its derivation allows missing values.", v)
