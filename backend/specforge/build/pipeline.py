"""Wire the build agents into a dependency-shaped graph and run it."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from ..llm import LLMProvider
from ..models import BuildResult, Spec
from ..orchestration import Context, Graph, Tracer
from .agents import DatasetBuilder, PlannerAgent


async def run_build(spec: Spec, inputs: dict[str, pd.DataFrame], llm: LLMProvider, workdir: Path,
                    tracer: Tracer | None = None, job_id: str = "local", targets: list[str] | None = None,
                    references: dict[str, pd.DataFrame] | None = None) -> BuildResult:
    tracer = tracer or Tracer()
    ctx = Context(llm=llm, tracer=tracer, state={
        "spec": spec, "inputs": inputs, "targets": targets, "workdir": workdir, "built": {},
        "references": references or {}})
    tracer.emit("Orchestrator", f"Build started: {spec.source_name} ({spec.standard}), inputs {sorted(inputs)}"
                + (f", references {sorted(references)} (validator only)" if references else ""), "start")

    plan = await PlannerAgent().run(ctx)
    g = Graph()
    for p in plan:
        g.add(DatasetBuilder(p["dataset"]), deps=[f"Build[{n}]" for n in p["needs"]], optional=True)
    results = await g.run(ctx)
    datasets = [results[f"Build[{p['dataset']}]"] for p in plan if results.get(f"Build[{p['dataset']}]")]
    tracer.emit("Orchestrator", "Build finished: " + ", ".join(f"{d.dataset}={d.status}" for d in datasets), "done",
                llm=llm.usage())
    return BuildResult(job_id=job_id, standard=spec.standard, plan=plan, datasets=datasets)


def detect_encoding(raw: bytes) -> str:
    """Per-file encoding detection. Never trust a declared encoding: extracts often arrive as Windows-1252
    even when everything else is UTF-8. UTF-8 is strict, so a successful decode is strong evidence."""
    for enc in ("utf-8-sig", "cp1252"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"  # decodes anything; last resort


def read_table(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf == ".csv":
        raw = path.read_bytes()
        encoding = detect_encoding(raw)
        df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=encoding)
        df.attrs["encoding"] = encoding
        return df
    if suf in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str).fillna("")
    if suf in (".sas7bdat", ".xpt"):
        df = pd.read_sas(path, format="xport" if suf == ".xpt" else "sas7bdat", encoding="utf-8")
        return df
    if suf == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported data file: {path.name}")
