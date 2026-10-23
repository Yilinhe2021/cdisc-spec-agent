"""Deterministic rule registry.

A rule is a plain function `fn(spec) -> Iterable[Hit]` registered with metadata.
Rules are cheap, exact and explainable, so they run first and the LLM agents only
spend tokens on what rules cannot judge (clarity, intent, cross-document meaning).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ...models import Category, Finding, Severity, Spec, SpecVariable


@dataclass
class Hit:
    message: str
    var: SpecVariable | None = None
    dataset: str = ""
    row: int | None = None
    suggestion: str = ""
    severity: Severity | None = None  # override rule default


@dataclass
class Rule:
    id: str
    title: str
    standards: tuple[str, ...]
    severity: Severity
    category: Category
    rationale: str
    kb_query: str
    fn: Callable[[Spec], Iterable[Hit]] = field(repr=False)


RULES: dict[str, Rule] = {}


def rule(id: str, title: str, *, standards=("SDTM", "ADaM"), severity=Severity.major,
         category=Category.conformance, rationale: str = "", kb_query: str = ""):
    def deco(fn):
        RULES[id] = Rule(id, title, tuple(standards), severity, category, rationale, kb_query or title, fn)
        return fn
    return deco


def run_rules(spec: Spec, only: set[str] | None = None) -> tuple[list[Finding], list[dict]]:
    findings: list[Finding] = []
    stats: list[dict] = []
    for r in RULES.values():
        if spec.standard not in r.standards or (only and r.id not in only):
            continue
        n = 0
        for h in r.fn(spec):
            n += 1
            v = h.var
            findings.append(Finding(
                rule_id=r.id, agent="RuleEngine",
                dataset=(v.dataset if v else h.dataset), variable=(v.variable if v else ""),
                row=(v.row if v else h.row), severity=h.severity or r.severity, category=r.category,
                message=h.message, suggestion=h.suggestion, confidence=1.0,
            ))
        stats.append({"rule": r.id, "title": r.title, "hits": n})
    return findings, stats


# ----------------------------------------------------------------- shared helpers
NAME_RE = re.compile(r"^[A-Z][A-Z0-9]{0,7}$")
REF_RE = re.compile(r"\b([A-Z][A-Z0-9_]{1,7})\.([A-Z][A-Z0-9_]{0,31})\b")
LITERAL_ASSIGN_RE = re.compile(
    r"(?:set\s+(?:to|as)|assign(?:ed)?(?:\s+(?:to|as))?|then|else|otherwise|populate(?:d)?\s+with|=)\s*['\"]([^'\"]*)['\"]",
    re.I,
)


def is_derived(v: SpecVariable) -> bool:
    return v.origin.strip().lower() in {"derived", "assigned"}


def is_char(v: SpecVariable) -> bool:
    return v.type.strip().lower() in {"char", "character", "text", "$", "string"}


def is_num(v: SpecVariable) -> bool:
    return v.type.strip().lower() in {"num", "numeric", "integer", "float", "number", "int"}


def assigned_literals(v: SpecVariable) -> list[str]:
    """Literal values a derivation assigns to *this* variable (not values it compares against)."""
    text = v.derivation
    out = []
    for m in LITERAL_ASSIGN_RE.finditer(text):
        token = m.group(0).lower()
        if token.lstrip().startswith("="):
            # "X = 'a'" is a comparison unless X is the target variable itself
            before = text[:m.start()].rstrip().split()
            if not before or before[-1].upper() != v.variable:
                continue
        out.append(m.group(1))
    return out
