"""Spec-QC agents.

Graph:
            Intake
              |
   +----------+-----------+-------------+
   |          |           |             |
RuleEngine  Clarity   Standards    Consistency      (run in parallel)
   |          |           |             |
   +----------+-----+-----+-------------+
                    |
                  Judge   (dedupe, ground with RAG, calibrate with feedback, rank)

Each LLM reviewer has one narrow question to answer, its own retrieved context and
a strict JSON schema; the Judge is the only place findings are merged.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from ..llm import register_mock
from ..models import SEVERITY_ORDER, Category, Citation, Finding, Severity, Spec, SpecVariable
from ..orchestration import Agent, Context
from ..rag.feedback import FeedbackMemory
from ..rag.retriever import HybridRetriever
from .rules import RULES, run_rules

BATCH = 15


def spec_table(rows: list[SpecVariable]) -> str:
    lines = ["row | dataset | variable | label | type | len | origin | codelist | core | derivation"]
    for v in rows:
        lines.append(" | ".join(str(x) for x in (v.row, v.dataset, v.variable, v.label, v.type, v.length or "",
                                                   v.origin, v.codelist, v.core, v.derivation.replace("\n", " "))))
    return "\n".join(lines)


def kb_block(hits) -> str:
    return "\n\n".join(f"[{h.chunk.id}] {h.chunk.section}\n{h.chunk.text}" for h in hits)


def _sev(s: str) -> Severity:
    try:
        return Severity(str(s).lower())
    except ValueError:
        return Severity.major


def _cat(s: str, default: Category) -> Category:
    try:
        return Category(str(s).lower())
    except ValueError:
        return default


def llm_items_to_findings(items, agent: str, rule_id: str, default_cat: Category, spec: Spec,
                          dataset: str | None, kb: HybridRetriever) -> list[Finding]:
    out = []
    by_id = {c.id: c for c in kb.chunks}
    for it in items if isinstance(items, list) else items.get("findings", []):
        ds = (it.get("dataset") or dataset or "").upper()
        var = (it.get("variable") or "").upper()
        v = spec.find(ds, var) if var else None
        if var and v is None:  # hallucinated target -> drop rather than mislead
            continue
        cites = [Citation(source=by_id[c].source, section=by_id[c].section, snippet=by_id[c].text[:240])
                 for c in it.get("citations", []) if c in by_id]
        out.append(Finding(
            rule_id=it.get("rule_id") or rule_id, agent=agent, dataset=ds, variable=var,
            row=v.row if v else None, severity=_sev(it.get("severity", "major")),
            category=_cat(it.get("category", ""), default_cat), message=it.get("issue", "").strip(),
            suggestion=it.get("suggestion", "").strip(), evidence=cites,
            confidence=float(it.get("confidence", 0.7)),
        ))
    return [f for f in out if f.message]


# =============================================================================== 0
class IntakeAgent(Agent):
    name = "Intake"
    description = "Parse the spec and profile what can be checked"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        ds = spec.dataset_names()
        derived = [v for v in spec.variables if v.origin.lower() in {"derived", "assigned"}]
        profile = {"datasets": len(ds), "variables": len(spec.variables), "derived_rows": len(derived),
                   "codelists": len(spec.codelists), "sheets": spec.sheet_names}
        self.log(ctx, f"{len(spec.variables)} variable rows across {len(ds)} datasets "
                      f"({len(derived)} derived/assigned), {len(spec.codelists)} codelists", "result", **profile)
        gaps = []
        if not spec.datasets:
            gaps.append("No dataset-level sheet: key and structure checks skipped.")
        if not spec.codelists:
            gaps.append("No codelist sheet: terminology checks skipped.")
        for g in gaps:
            self.log(ctx, g, "warning")
        ctx.state["coverage"].extend({"agent": self.name, "gap": g} for g in gaps)
        return profile


# =============================================================================== 1
class RuleEngineAgent(Agent):
    name = "RuleEngine"
    description = "Deterministic conformance & consistency rules"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        findings, stats = run_rules(spec)
        fired = [s for s in stats if s["hits"]]
        self.log(ctx, f"{len(stats)} rules ran, {len(fired)} fired, {len(findings)} findings", "result",
                 rules=stats)
        ctx.state["coverage"].append({"agent": self.name, "checked": f"{len(stats)} rules"})
        return findings


# =============================================================================== 2
CLARITY_SYSTEM = """You are a senior clinical statistical programmer reviewing a {standard} dataset specification.
Your single question for every row: could an independent programmer who cannot ask anyone implement this
derivation and get exactly the same values as the author? If not, it is a defect.

Look for: undefined branches (if without else / missing-input case), ordering words without sort key or
tie-breaker (first, last, baseline, worst), date comparisons without partial/missing-date handling,
vague wording (as appropriate, if applicable, TBD, per SAP without a section), unstated units or boundaries,
references to things not defined in the spec. Do NOT report naming, label length or type problems
(another agent handles those). Do not invent issues for rows that are clear.

Use the reference notes and past reviewer decisions to calibrate. Output a JSON list; each item:
{{"dataset": str, "variable": str, "severity": "critical|major|minor", "issue": str (what is unclear, quote
the words), "suggestion": str (the question to send to the spec owner), "citations": [reference ids],
"confidence": 0-1}}. Return [] if every row is clear."""

VAGUE = ["tbd", "tbc", "to be confirmed", "to be determined", "as appropriate", "if applicable", "etc", "and/or",
         "derived accordingly", "standard algorithm", "as needed", "see programming notes", "???", "per sap",
         "see sap", "as per protocol", "similar to"]
ORDER_WORDS = re.compile(r"\b(first|last|earliest|latest|worst|best|highest|lowest|baseline|maximum|minimum)\b(?!\s+day\b)", re.I)
ORDER_KEYS = re.compile(r"\b(sort(ed)?|order(ed)?|by\s+[A-Z]{3,}|tie|chronolog|min\(|max\()", re.I)
DATE_WORDS = re.compile(r"(DTC|DT\b|date)", re.I)
DATE_COMPARE = re.compile(r"(<|>|before|after|prior to|on or after|minus|difference|between)", re.I)
MISSING_HANDLED = re.compile(r"(partial|missing|imput|incomplete|null|blank)", re.I)


@register_mock("clarity_review")
def offline_clarity(ctx: dict) -> list[dict]:
    out = []
    for r in ctx["rows"]:
        d = r["derivation"]
        low = d.lower()
        base = {"dataset": r["dataset"], "variable": r["variable"], "citations": []}
        vague = [w for w in VAGUE if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low)]
        if "per sap" in vague and re.search(r"sap\s+(section\s*)?\d", low):
            vague.remove("per sap")
        if vague:
            out.append({**base, "severity": "major", "confidence": 0.85,
                        "issue": f"Vague wording {vague} hides the actual rule: \"{d[:120]}\"",
                        "suggestion": "Replace the vague wording with the explicit rule or an exact document reference.",
                        "citations": ["04_spec_writing#4"]})
        branch_text = re.sub(r"\bif (missing|null|blank)\b[^;.]*", "", low)  # "; if missing set to X" is a fallback, not a branch
        if re.search(r"\bif\b", branch_text) and not re.search(r"\b(else|otherwise|all other)\b|\b(missing|null|blank) (if|when|for)\b", low):
            out.append({**base, "severity": "major", "confidence": 0.8,
                        "issue": "Only the 'if' branch is defined; the value for all other records is not stated.",
                        "suggestion": "State the value when the condition is false and when the input is missing.",
                        "citations": ["04_spec_writing#1"]})
        if ORDER_WORDS.search(d) and not ORDER_KEYS.search(d):
            w = ORDER_WORDS.search(d).group(0)
            out.append({**base, "severity": "major", "confidence": 0.7,
                        "issue": f"'{w}' is used without a sort key or tie-breaker.",
                        "suggestion": f"Which variable defines '{w}', and how are ties on the same date resolved?",
                        "citations": ["04_spec_writing#2"]})
        if DATE_WORDS.search(d) and DATE_COMPARE.search(d) and not MISSING_HANDLED.search(d):
            out.append({**base, "severity": "minor", "confidence": 0.6,
                        "issue": "Dates are compared but partial/missing date handling is not described.",
                        "suggestion": "Say whether partial dates are excluded, imputed (how) or kept missing.",
                        "citations": ["04_spec_writing#3"]})
        if r["origin"].lower() == "derived" and 0 < len(d) < 12 and "." not in d:
            out.append({**base, "severity": "minor", "confidence": 0.5,
                        "issue": f"Derivation '{d}' is too terse to implement.",
                        "suggestion": "Spell out the source variables and logic.", "citations": []})
    return out


class ClarityReviewer(Agent):
    name = "ClarityReviewer"
    description = "LLM: can each derivation be implemented without asking anyone?"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        kb: HybridRetriever = ctx.state["kb"]
        fb: FeedbackMemory = ctx.state["feedback"]
        rows = [v for v in spec.variables if v.derivation.strip()]
        findings: list[Finding] = []
        notes = kb.search("implementable derivation branches sort order missing dates vague wording", k=6)
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            examples = fb.examples(" ".join(v.derivation for v in batch)[:500], k=3)
            user = (f"Reference notes:\n{kb_block(notes)}\n\nPast reviewer decisions:\n{json.dumps(examples)}\n\n"
                    f"Spec rows:\n{spec_table(batch)}")
            items = await ctx.llm.complete_json(
                CLARITY_SYSTEM.format(standard=spec.standard), user, task="clarity_review",
                context={"rows": [v.model_dump() for v in batch]})
            fs = llm_items_to_findings(items, self.name, "LLM-CLARITY", Category.clarity, spec, None, kb)
            findings += fs
            self.log(ctx, f"batch {i // BATCH + 1}: {len(batch)} rows -> {len(fs)} findings", "llm")
        ctx.state["coverage"].append({"agent": self.name, "checked": f"{len(rows)} rows with derivation text"})
        return findings


# =============================================================================== 3
STANDARDS_SYSTEM = """You are a CDISC {standard} standards reviewer. Using ONLY the reference notes given (cite their
ids), review the dataset below for problems that simple rules miss: variables used against their standard meaning,
labels of well-known variables re-worded, analysis logic placed in SDTM (imputation, derived flags), missing
traceability in ADaM (Predecessor without a source variable), structure/keys that do not fit the stated structure.
Ignore issues of name length, label length, data type (handled elsewhere). Output a JSON list of
{{"dataset","variable","severity","category":"conformance|completeness","issue","suggestion","citations":[ids],
"confidence"}}. Return [] if nothing is wrong."""

STANDARD_LABELS = {
    "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation", "USUBJID": "Unique Subject Identifier",
    "SUBJID": "Subject Identifier for the Study", "SITEID": "Study Site Identifier", "AGE": "Age",
    "AGEU": "Age Units", "SEX": "Sex", "RACE": "Race", "ETHNIC": "Ethnicity", "COUNTRY": "Country",
    "ARM": "Description of Planned Arm", "ARMCD": "Planned Arm Code", "ACTARM": "Description of Actual Arm",
    "ACTARMCD": "Actual Arm Code", "RFSTDTC": "Subject Reference Start Date/Time",
    "RFENDTC": "Subject Reference End Date/Time", "BRTHDTC": "Date/Time of Birth",
    "AETERM": "Reported Term for the Adverse Event", "AEDECOD": "Dictionary-Derived Term",
    "AESEV": "Severity/Intensity", "AESER": "Serious Event", "AESTDTC": "Start Date/Time of Adverse Event",
    "AEENDTC": "End Date/Time of Adverse Event", "AESEQ": "Sequence Number", "PARAMCD": "Parameter Code",
    "PARAM": "Parameter", "AVAL": "Analysis Value", "AVALC": "Analysis Value (C)", "SAFFL": "Safety Population Flag",
    "ITTFL": "Intent-To-Treat Population Flag", "TRTSDT": "Date of First Exposure to Treatment",
    "TRTEDT": "Date of Last Exposure to Treatment", "TRT01P": "Planned Treatment for Period 01",
    "TRT01A": "Actual Treatment for Period 01", "ASTDT": "Analysis Start Date", "AENDT": "Analysis End Date",
    "TRTEMFL": "Treatment Emergent Analysis Flag", "ADT": "Analysis Date", "ABLFL": "Baseline Record Flag",
    "BASE": "Baseline Value", "CHG": "Change from Baseline",
}


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


@register_mock("standards_review")
def offline_standards(ctx: dict) -> list[dict]:
    out = []
    std = ctx["standard"]
    for r in ctx["rows"]:
        base = {"dataset": r["dataset"], "variable": r["variable"], "confidence": 0.75}
        std_label = STANDARD_LABELS.get(r["variable"])
        if std_label and r["label"] and _squash(std_label) != _squash(r["label"]):
            out.append({**base, "severity": "minor", "category": "conformance",
                        "issue": f"Label '{r['label']}' differs from the usual standard label '{std_label}'.",
                        "suggestion": f"Use '{std_label}' verbatim unless there is a reason to deviate.",
                        "citations": ["01_general_conventions#1", "05_common_variables#0"]})
        low = r["derivation"].lower()
        if std == "SDTM" and "imput" in low:
            out.append({**base, "severity": "major", "category": "conformance",
                        "issue": "SDTM derivation imputes values; SDTM represents collected data and keeps partial dates as-is.",
                        "suggestion": "Move the imputation to ADaM and keep the SDTM value un-imputed.",
                        "citations": ["02_sdtm_basics#3", "02_sdtm_basics#0"]})
        if std == "ADaM" and r["origin"].lower() == "predecessor" and not re.search(r"\b[A-Z]{2,8}\.[A-Z]", r["derivation"]):
            out.append({**base, "severity": "minor", "category": "completeness",
                        "issue": "Predecessor variable does not name its source dataset.variable, which breaks traceability.",
                        "suggestion": "State the source as DATASET.VARIABLE.", "citations": ["03_adam_basics#0"]})
    return out


class StandardsReviewer(Agent):
    name = "StandardsReviewer"
    description = "LLM + RAG: conformance issues rules cannot express"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        kb: HybridRetriever = ctx.state["kb"]
        tag = {spec.standard.lower()}
        findings: list[Finding] = []
        for ds in spec.dataset_names():
            rows = spec.vars_of(ds)
            meta = spec.dataset(ds)
            query = f"{spec.standard} {ds} {meta.structure if meta else ''} " + " ".join(v.variable for v in rows[:25])
            hits = kb.search(query, k=6, tags=tag | {"general"}) + kb.search(query, k=3)
            seen, uniq = set(), []
            for h in hits:
                if h.chunk.id not in seen:
                    seen.add(h.chunk.id)
                    uniq.append(h)
            for i in range(0, len(rows), BATCH * 2):
                batch = rows[i:i + BATCH * 2]
                user = (f"Reference notes:\n{kb_block(uniq)}\n\nDataset {ds} "
                        f"({meta.structure if meta else 'structure not given'}; keys {meta.keys if meta else '?'}):\n"
                        f"{spec_table(batch)}")
                items = await ctx.llm.complete_json(
                    STANDARDS_SYSTEM.format(standard=spec.standard), user, task="standards_review",
                    context={"standard": spec.standard, "rows": [v.model_dump() for v in batch]})
                findings += llm_items_to_findings(items, self.name, "LLM-STANDARDS", Category.conformance,
                                                  spec, ds, kb)
            self.log(ctx, f"{ds}: retrieved {len(uniq)} notes ({', '.join(h.chunk.id for h in uniq[:4])}...)", "tool")
        ctx.state["coverage"].append({"agent": self.name, "checked": f"{len(spec.dataset_names())} datasets"})
        return findings


# =============================================================================== 4
CONSISTENCY_SYSTEM = """You review a whole {standard} specification for internal contradictions: the same variable
defined differently in different datasets, derivations that depend on each other in a cycle, a dataset structure that
contradicts its keys, derivations that contradict the codelist or another row. Output a JSON list of
{{"dataset","variable","severity","category":"consistency","issue","suggestion","confidence"}}. Return [] if none."""


@register_mock("consistency_review")
def offline_consistency(ctx: dict) -> list[dict]:
    rows = ctx["rows"]
    out = []
    by_name = defaultdict(list)
    for r in rows:
        by_name[r["variable"]].append(r)
    for name, rs in by_name.items():
        if len({r["dataset"] for r in rs}) < 2:
            continue
        for attr in ("label", "type"):
            vals = {r[attr].strip() for r in rs if r[attr].strip()}
            if len(vals) > 1:
                where = ", ".join(f"{r['dataset']}='{r[attr]}'" for r in rs)
                out.append({"dataset": rs[-1]["dataset"], "variable": name, "severity": "minor",
                            "category": "consistency", "confidence": 0.8,
                            "issue": f"{name} has different {attr} across datasets: {where}.",
                            "suggestion": f"Use one {attr} for {name} in every dataset."})
    # dependency cycles inside a dataset
    by_ds = defaultdict(dict)
    for r in rows:
        by_ds[r["dataset"]][r["variable"]] = r
    for ds, vars_ in by_ds.items():
        graph = {v: {t for t in re.findall(r"\b[A-Z][A-Z0-9]{1,7}\b", r["derivation"]) if t in vars_ and t != v}
                 for v, r in vars_.items()}
        reported = set()
        for a, deps in graph.items():
            for b in deps:
                if a in graph.get(b, set()) and (b, a) not in reported:
                    reported.add((a, b))
                    out.append({"dataset": ds, "variable": a, "severity": "major", "category": "consistency",
                                "confidence": 0.75, "issue": f"{a} and {b} are derived from each other (circular).",
                                "suggestion": "Define which variable is derived first."})
    return out


class ConsistencyReviewer(Agent):
    name = "ConsistencyReviewer"
    description = "LLM: contradictions across rows and datasets"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        kb: HybridRetriever = ctx.state["kb"]
        compact = [v for v in spec.variables]
        user = f"Datasets: {[d.model_dump(include={'name', 'structure', 'keys'}) for d in spec.datasets]}\n\n" \
               f"{spec_table(compact)}"
        items = await ctx.llm.complete_json(CONSISTENCY_SYSTEM.format(standard=spec.standard), user[:120_000],
                                            task="consistency_review",
                                            context={"rows": [v.model_dump() for v in compact]})
        findings = llm_items_to_findings(items, self.name, "LLM-CONSIST", Category.consistency, spec, None, kb)
        ctx.state["coverage"].append({"agent": self.name, "checked": "whole spec"})
        return findings


# =============================================================================== 5
VERIFY_SYSTEM = """You are the final judge of spec-review findings produced by other AI reviewers. For each finding,
decide if it is real and grounded in the spec row shown (not a hallucination, not a style preference). Output a JSON
list of {"id": str, "keep": bool, "reason": str}."""


@register_mock("verify_findings")
def offline_verify(ctx: dict) -> list[dict]:
    return [{"id": f["id"], "keep": True, "reason": "offline mode: no LLM verification"} for f in ctx["findings"]]


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


class JudgeAgent(Agent):
    name = "Judge"
    description = "Merge, verify, ground and rank all findings"

    async def run(self, ctx: Context):
        spec: Spec = ctx.state["spec"]
        kb: HybridRetriever = ctx.state["kb"]
        fb: FeedbackMemory = ctx.state["feedback"]
        raw: list[Finding] = []
        for name in ("RuleEngine", "ClarityReviewer", "StandardsReviewer", "ConsistencyReviewer"):
            raw += ctx.state["results"].get(name) or []
        self.log(ctx, f"received {len(raw)} raw findings")

        # 1) LLM self-verification of LLM findings (rules are exact, skip them)
        llm_f = [f for f in raw if f.agent != "RuleEngine"]
        if llm_f and not ctx.llm.offline:
            payload = [{"id": f.id, "target": f.target, "issue": f.message,
                        "row": (spec.find(f.dataset, f.variable).model_dump(include={"label", "type", "origin", "derivation"})
                                if f.variable and spec.find(f.dataset, f.variable) else None)} for f in llm_f]
            verdicts = await ctx.llm.complete_json(VERIFY_SYSTEM, json.dumps(payload)[:100_000],
                                                   task="verify_findings", context={"findings": payload})
            drop = {v["id"] for v in verdicts if not v.get("keep", True)}
            raw = [f for f in raw if f.id not in drop]
            self.log(ctx, f"verification dropped {len(drop)} ungrounded LLM findings", "llm")

        # 2) dedupe: same target + category + overlapping wording
        merged: list[Finding] = []
        for f in sorted(raw, key=lambda f: (SEVERITY_ORDER[f.severity], -f.confidence)):
            dup = next((m for m in merged if m.dataset == f.dataset and m.variable == f.variable
                        and m.category == f.category
                        and len(_tokens(m.message) & _tokens(f.message)) / max(len(_tokens(f.message)), 1) > 0.5), None)
            if dup:
                dup.merged_from.append(f"{f.agent}:{f.rule_id}")
                dup.confidence = min(1.0, dup.confidence + 0.1)  # independent agreement
                dup.evidence += [e for e in f.evidence if e not in dup.evidence]
            else:
                merged.append(f)
        self.log(ctx, f"deduplicated {len(raw)} -> {len(merged)}")

        # 3) ground rule findings with retrieved notes
        for f in merged:
            if not f.evidence and f.rule_id in RULES:
                hits = kb.search(RULES[f.rule_id].kb_query, k=1)
                f.evidence = [Citation(source=h.chunk.source, section=h.chunk.section,
                                       snippet=h.chunk.text[:240], score=h.score) for h in hits]

        # 4) calibrate with human feedback
        adjusted = 0
        for f in merged:
            past = fb.similar(f)
            if past:
                dismissed = sum(p["decision"] == "dismissed" for p in past)
                accepted = sum(p["decision"] == "accepted" for p in past)
                f.confidence = max(0.05, min(1.0, f.confidence - 0.25 * dismissed + 0.1 * accepted))
                adjusted += 1
        if adjusted:
            self.log(ctx, f"calibrated {adjusted} findings from reviewer history", "tool")

        final = [f for f in merged if f.confidence >= 0.3]
        final.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.dataset, f.row or 0))
        self.log(ctx, f"{len(final)} findings after calibration", "result")
        return final
