"""Standard-specific rule packs (SDTM, ADaM). Generic, publicly known conventions only."""
from __future__ import annotations

import re

from ...models import Category, Severity, Spec
from .engine import Hit, is_char, is_num, rule

SDTM_COMMON_IDS = {"STUDYID", "DOMAIN", "USUBJID", "SUBJID", "SITEID", "VISIT", "VISITNUM", "VISITDY", "EPOCH",
                   "TAETORD", "IDVAR", "IDVARVAL", "QNAM", "QLABEL", "QVAL", "QORIG", "QEVAL", "RDOMAIN",
                   "POOLID", "SPDEVID", "FOCID", "APID"}
DM_STYLE = {"DM", "SV", "SE", "TA", "TE", "TI", "TS", "TV", "CO", "RELREC"}


def _is_supp(name: str) -> bool:
    return name.startswith("SUPP") or name == "RELREC"


# ======================================================================== SDTM
@rule("SDTM-001", "Identifier variables missing", standards=("SDTM",), severity=Severity.critical,
      category=Category.completeness, kb_query="identifier variables STUDYID DOMAIN USUBJID")
def sdtm_ids(spec: Spec):
    for ds in spec.dataset_names():
        names = {v.variable for v in spec.vars_of(ds)}
        need = ["STUDYID", "USUBJID"] if _is_supp(ds) else ["STUDYID", "DOMAIN", "USUBJID"]
        if ds.startswith("T") and ds in DM_STYLE:
            need = ["STUDYID", "DOMAIN"]
        for n in need:
            if n not in names:
                yield Hit(f"{ds} has no {n}.", dataset=ds)


@rule("SDTM-002", "--DTC variable should be ISO 8601 character", standards=("SDTM",), severity=Severity.critical,
      kb_query="dates and times ISO 8601 character DTC")
def dtc_char(spec: Spec):
    for v in spec.variables:
        if v.variable.endswith("DTC") and not is_char(v):
            yield Hit(f"{v.variable} is a DTC variable but typed '{v.type}'. SDTM dates are ISO 8601 text.", v)


@rule("SDTM-003", "--DY / --SEQ / VISITNUM should be numeric", standards=("SDTM",), severity=Severity.major,
      kb_query="study day numeric no day zero sequence number")
def num_vars(spec: Spec):
    for v in spec.variables:
        n = v.variable
        if (n.endswith(("DY", "SEQ")) and len(n) > 3) or n in {"VISITNUM", "AGE"}:
            if not is_num(v):
                yield Hit(f"{n} should be numeric (typed '{v.type}').", v)


@rule("SDTM-004", "Study-day derivation does not address 'no day 0'", standards=("SDTM",), severity=Severity.major,
      category=Category.clarity, kb_query="study day relative to reference start no day zero")
def study_day(spec: Spec):
    for v in spec.variables:
        if v.variable.endswith("DY") and len(v.variable) > 3 and v.derivation:
            d = v.derivation.lower()
            if "+ 1" not in d and "+1" not in d and "day 0" not in d and "day zero" not in d:
                yield Hit(f"{v.variable}: the derivation does not say how dates on/after vs before the reference "
                          "date are handled (+1 / no day 0).", v)


@rule("SDTM-005", "Variable missing the domain prefix", standards=("SDTM",), severity=Severity.minor,
      kb_query="variable prefixes two-letter domain code")
def prefix(spec: Spec):
    for ds in spec.dataset_names():
        if ds in DM_STYLE or _is_supp(ds) or len(ds) != 2:
            continue
        for v in spec.vars_of(ds):
            if v.variable not in SDTM_COMMON_IDS and not v.variable.startswith(ds):
                yield Hit(f"{v.variable} in {ds} does not start with the domain prefix '{ds}'.", v)


@rule("SDTM-006", "DOMAIN value does not match dataset name", standards=("SDTM",), severity=Severity.critical,
      category=Category.consistency)
def domain_value(spec: Spec):
    for v in spec.variables:
        if v.variable == "DOMAIN":
            lits = re.findall(r"['\"]([A-Z]{2,8})['\"]", v.derivation)
            if lits and lits[0] != v.dataset:
                yield Hit(f"DOMAIN in {v.dataset} is set to '{lits[0]}'.", v)


@rule("SDTM-007", "--TESTCD / QNAM longer than 8", standards=("SDTM",), severity=Severity.major)
def testcd_len(spec: Spec):
    for v in spec.variables:
        if (v.variable.endswith("TESTCD") or v.variable == "QNAM") and v.length and v.length > 8:
            yield Hit(f"{v.variable} length is {v.length}; values are limited to 8 characters.", v)


# ======================================================================== ADaM
@rule("ADAM-001", "STUDYID / USUBJID missing", standards=("ADaM",), severity=Severity.critical,
      category=Category.completeness, kb_query="ADSL subject level identifiers")
def adam_ids(spec: Spec):
    for ds in spec.dataset_names():
        names = {v.variable for v in spec.vars_of(ds)}
        for n in ("STUDYID", "USUBJID"):
            if n not in names:
                yield Hit(f"{ds} has no {n}.", dataset=ds)


@rule("ADAM-002", "Dataset name should start with AD", standards=("ADaM",), severity=Severity.minor)
def ad_prefix(spec: Spec):
    for ds in spec.dataset_names():
        if not ds.startswith("AD"):
            yield Hit(f"ADaM dataset {ds} does not start with 'AD'.", dataset=ds)


@rule("ADAM-003", "Analysis date/time variable is not numeric", standards=("ADaM",), severity=Severity.critical,
      kb_query="ADaM numeric dates DT DTM TM")
def adam_dates(spec: Spec):
    for v in spec.variables:
        n = v.variable
        if n.endswith(("DT", "DTM")) and not n.endswith("DTC") and len(n) > 3 and not is_num(v):
            yield Hit(f"{n} is an analysis date but typed '{v.type}'; ADaM *DT/*DTM are numeric.", v)


@rule("ADAM-004", "Flag variable is not Char(1) with Y/N", standards=("ADaM",), severity=Severity.major,
      category=Category.terminology, kb_query="analysis flags FL Y N null character length 1")
def flags(spec: Spec):
    for v in spec.variables:
        if not v.variable.endswith("FL"):
            continue
        if not is_char(v) or (v.length and v.length != 1):
            yield Hit(f"{v.variable} should be Char length 1 (is {v.type} {v.length}).", v)
        terms = spec.codelists.get(v.codelist)
        if terms and not {t.code for t in terms} <= {"Y", "N"}:
            yield Hit(f"{v.variable} codelist {v.codelist} contains values other than Y/N.", v)


@rule("ADAM-005", "Numeric companion without its character variable", standards=("ADaM",),
      severity=Severity.minor, category=Category.consistency, kb_query="numeric companions AVISIT AVISITN TRT01PN")
def companions(spec: Spec):
    for ds in spec.dataset_names():
        names = {v.variable for v in spec.vars_of(ds)}
        for v in spec.vars_of(ds):
            n = v.variable
            if len(n) > 4 and n.endswith("N") and n[:-1] in names and not is_num(v):
                yield Hit(f"{n} is the numeric companion of {n[:-1]} but is not numeric.", v)
            known_pair = n in {"AVISITN", "ATPTN", "APHASEN", "TRTPN", "TRTAN"} or re.fullmatch(r"TRT\d\d[PA]N", n)
            if known_pair and n[:-1] not in names:
                yield Hit(f"{n} exists without its character variable {n[:-1]}.", v)


@rule("ADAM-006", "BDS dataset missing PARAMCD/PARAM/AVAL", standards=("ADaM",), severity=Severity.critical,
      category=Category.completeness, kb_query="BDS structure PARAMCD PARAM AVAL AVALC")
def bds(spec: Spec):
    for ds in spec.datasets:
        if "BDS" not in ds.structure.upper() and "PARAM" not in ds.structure.upper():
            continue
        names = {v.variable for v in spec.vars_of(ds.name)}
        for n in ("PARAMCD", "PARAM"):
            if n not in names:
                yield Hit(f"BDS dataset {ds.name} has no {n}.", dataset=ds.name, row=ds.row)
        if not names & {"AVAL", "AVALC"}:
            yield Hit(f"BDS dataset {ds.name} has neither AVAL nor AVALC.", dataset=ds.name, row=ds.row)


@rule("ADAM-007", "PARAMCD longer than 8", standards=("ADaM",), severity=Severity.major)
def paramcd(spec: Spec):
    for v in spec.variables:
        if v.variable == "PARAMCD" and v.length and v.length > 8:
            yield Hit(f"PARAMCD length is {v.length}; must be at most 8.", v)
    for cl, terms in spec.codelists.items():
        if "PARAMCD" in cl.upper():
            for t in terms:
                if len(t.code) > 8:
                    yield Hit(f"PARAMCD value '{t.code}' is longer than 8 characters.", dataset="(codelists)", row=t.row)


@rule("ADAM-008", "ADSL is not keyed one record per subject", standards=("ADaM",), severity=Severity.major,
      category=Category.consistency, kb_query="ADSL one record per subject")
def adsl_keys(spec: Spec):
    ds = spec.dataset("ADSL")
    if ds and ds.keys and ds.keys not in (["USUBJID"], ["STUDYID", "USUBJID"]):
        yield Hit(f"ADSL keys are {ds.keys}; ADSL has one record per subject (USUBJID).", dataset="ADSL", row=ds.row)


@rule("ADAM-009", "Imputed date without imputation rule", standards=("ADaM",), severity=Severity.major,
      category=Category.clarity, kb_query="date imputation flags whole date missing")
def imputation(spec: Spec):
    for v in spec.variables:
        n = v.variable
        if n.endswith("DT") and v.derivation and "imput" in v.derivation.lower():
            d = v.derivation.lower()
            if not any(w in d for w in ("first day", "last day", "day 1", "01", "15", "mid", "earliest", "latest", "missing")):
                yield Hit(f"{n} mentions imputation but does not state the imputation rule.", v)
