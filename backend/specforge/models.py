"""Core domain models shared by every layer (parser, QC agents, build agents, API).

The same models are used for SDTM and ADaM: from the tool's point of view both are
"a spec that describes how to turn source tables into target tables". The standard
only selects which rule pack and knowledge the agents lean on.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

Standard = Literal["SDTM", "ADaM"]


def _id() -> str:
    return uuid.uuid4().hex[:10]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- spec
class SpecVariable(BaseModel):
    row: int = Field(description="1-based row number in the source sheet (for annotation)")
    dataset: str
    variable: str
    label: str = ""
    type: str = ""            # Char / Num
    length: int | None = None
    origin: str = ""          # CRF, Derived, Assigned, Predecessor, Protocol, eDT ...
    derivation: str = ""      # source / derivation / mapping text
    codelist: str = ""
    core: str = ""            # Req / Exp / Perm / Cond
    key_seq: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.dataset}.{self.variable}"


class SpecDataset(BaseModel):
    name: str
    label: str = ""
    structure: str = ""       # e.g. "One record per subject", or class: ADSL / BDS / OCCDS / EVENTS ...
    keys: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    row: int | None = None


class CodelistTerm(BaseModel):
    codelist: str
    code: str
    decode: str = ""
    row: int | None = None


class Spec(BaseModel):
    standard: Standard
    source_name: str = "spec"
    datasets: list[SpecDataset] = Field(default_factory=list)
    variables: list[SpecVariable] = Field(default_factory=list)
    codelists: dict[str, list[CodelistTerm]] = Field(default_factory=dict)
    sheet_names: dict[str, str] = Field(default_factory=dict)  # logical -> actual sheet name

    def dataset_names(self) -> list[str]:
        names = [d.name for d in self.datasets]
        for v in self.variables:
            if v.dataset not in names:
                names.append(v.dataset)
        return names

    def vars_of(self, dataset: str) -> list[SpecVariable]:
        return [v for v in self.variables if v.dataset == dataset]

    def dataset(self, name: str) -> SpecDataset | None:
        return next((d for d in self.datasets if d.name == name), None)

    def find(self, dataset: str, variable: str) -> SpecVariable | None:
        return next((v for v in self.variables if v.dataset == dataset and v.variable == variable), None)


# ----------------------------------------------------------------------- findings
class Severity(str, Enum):
    critical = "critical"   # will produce wrong data / non-conformant submission
    major = "major"         # programmer must ask someone before coding
    minor = "minor"         # cosmetic / convention
    info = "info"


SEVERITY_ORDER = {Severity.critical: 0, Severity.major: 1, Severity.minor: 2, Severity.info: 3}


class Category(str, Enum):
    conformance = "conformance"       # breaks a CDISC / submission convention
    clarity = "clarity"               # derivation cannot be implemented without asking
    consistency = "consistency"       # spec contradicts itself
    completeness = "completeness"     # something required is missing
    terminology = "terminology"       # codelist problems


class Citation(BaseModel):
    source: str
    section: str = ""
    snippet: str = ""
    score: float | None = None


class Finding(BaseModel):
    id: str = Field(default_factory=_id)
    rule_id: str
    agent: str
    dataset: str = ""
    variable: str = ""
    row: int | None = None
    severity: Severity
    category: Category
    message: str
    suggestion: str = ""
    evidence: list[Citation] = Field(default_factory=list)
    confidence: float = 1.0
    status: Literal["open", "accepted", "dismissed"] = "open"
    merged_from: list[str] = Field(default_factory=list)

    @property
    def target(self) -> str:
        return f"{self.dataset}.{self.variable}" if self.variable else self.dataset


# -------------------------------------------------------------------------- trace
class TraceEvent(BaseModel):
    ts: str = Field(default_factory=now)
    agent: str
    kind: Literal["start", "info", "llm", "tool", "result", "warning", "error", "done"] = "info"
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- jobs
class QCResult(BaseModel):
    job_id: str
    standard: Standard
    spec_name: str
    summary: dict[str, Any]
    findings: list[Finding]
    coverage: list[dict[str, Any]] = Field(default_factory=list)  # what each agent did / did not check


class DatasetBuild(BaseModel):
    dataset: str
    program: str = ""
    attempts: int = 0
    status: Literal["pending", "ok", "warnings", "failed"] = "pending"
    rows: int = 0
    columns: list[str] = Field(default_factory=list)
    preview: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    concordance: dict[str, Any] | None = None


class BuildResult(BaseModel):
    job_id: str
    standard: Standard
    plan: list[dict[str, Any]]
    datasets: list[DatasetBuild]
