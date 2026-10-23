"""FastAPI service: two workflows (Spec QC, Build) as background jobs with live SSE traces."""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..build.pipeline import read_table, run_build
from ..llm import get_provider
from ..models import Standard
from ..orchestration import Tracer
from ..qc.annotate import annotate
from ..qc.pipeline import run_qc
from ..qc.rules import RULES
from ..rag import feedback
from ..spec.parser import load_spec

DATA_DIR = Path(os.getenv("SPECFORGE_DATA_DIR", Path.cwd() / ".specforge"))
EXAMPLES = Path(os.getenv("SPECFORGE_EXAMPLES", Path(__file__).resolve().parents[3] / "examples"))
FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "dist"

app = FastAPI(title="SpecForge", version="0.1.0",
              description="Multi-agent + RAG spec QC and dataset generation for SDTM / ADaM")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@dataclass
class Job:
    id: str
    kind: str
    standard: str
    workdir: Path
    tracer: Tracer = field(default_factory=Tracer)
    status: str = "queued"
    error: str = ""
    result: Any = None
    spec: Any = None
    spec_path: Path | None = None


JOBS: dict[str, Job] = {}


def _new_job(kind: str, standard: str) -> Job:
    jid = uuid.uuid4().hex[:12]
    wd = DATA_DIR / "jobs" / jid
    wd.mkdir(parents=True, exist_ok=True)
    job = Job(jid, kind, standard, wd)
    JOBS[jid] = job
    return job


def _get(jid: str, kind: str | None = None) -> Job:
    job = JOBS.get(jid)
    if not job or (kind and job.kind != kind):
        raise HTTPException(404, "job not found")
    return job


async def _save(upload: UploadFile, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)
    return dest


# --------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    llm = get_provider()
    return {"status": "ok", "llm": llm.name, "model": llm.model, "offline": llm.offline}


@app.get("/api/rules")
def rules():
    return [{"id": r.id, "title": r.title, "standards": r.standards, "severity": r.severity.value,
             "category": r.category.value} for r in RULES.values()]


# ----------------------------------------------------------------------- QC
async def _run_qc_job(job: Job, support: dict[str, str]):
    job.status = "running"
    try:
        job.result = await run_qc(job.spec, get_provider(), job.tracer, job.id, support)
        (job.workdir / "qc_result.json").write_text(job.result.model_dump_json(indent=1))
        job.status = "done"
    except Exception as e:  # surface to UI
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
        job.tracer.emit("Orchestrator", job.error, "error")
    finally:
        job.tracer.close()


@app.post("/api/qc")
async def start_qc(background: BackgroundTasks, standard: Standard = Form(...), spec: UploadFile = File(...),
                   documents: list[UploadFile] | None = File(None)):
    job = _new_job("qc", standard)
    job.spec_path = await _save(spec, job.workdir / "input" / (spec.filename or "spec.xlsx"))
    try:
        job.spec = load_spec(job.spec_path, standard, spec.filename)
    except Exception as e:
        raise HTTPException(400, f"Could not read spec: {e}") from e
    support = {}
    for d in documents or []:
        support[d.filename or "doc"] = (await d.read()).decode("utf-8", errors="replace")
    background.add_task(_run_qc_job, job, support)
    return {"job_id": job.id, "variables": len(job.spec.variables), "datasets": job.spec.dataset_names()}


@app.post("/api/qc/demo")
async def demo_qc(background: BackgroundTasks, standard: Standard = Form(...)):
    src = EXAMPLES / standard.lower() / "spec_draft.xlsx"
    if not src.exists():
        raise HTTPException(404, "examples not generated: run `python examples/make_examples.py`")
    job = _new_job("qc", standard)
    job.spec_path = job.workdir / "input" / f"demo_{standard.lower()}_spec_draft.xlsx"
    job.spec_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, job.spec_path)
    job.spec = load_spec(job.spec_path, standard, job.spec_path.name)
    background.add_task(_run_qc_job, job, {})
    return {"job_id": job.id, "variables": len(job.spec.variables), "datasets": job.spec.dataset_names()}


class Decision(BaseModel):
    decision: str  # accepted | dismissed | open
    note: str = ""


@app.post("/api/qc/{jid}/findings/{fid}")
def decide(jid: str, fid: str, body: Decision):
    job = _get(jid, "qc")
    if not job.result:
        raise HTTPException(409, "job not finished")
    f = next((f for f in job.result.findings if f.id == fid), None)
    if not f:
        raise HTTPException(404, "finding not found")
    if body.decision not in ("accepted", "dismissed", "open"):
        raise HTTPException(400, "decision must be accepted|dismissed|open")
    f.status = body.decision
    if body.decision != "open":
        feedback.record(f, body.decision, body.note)
    return {"ok": True}


@app.get("/api/qc/{jid}/annotated.xlsx")
def annotated(jid: str):
    job = _get(jid, "qc")
    if not job.result:
        raise HTTPException(409, "job not finished")
    out = annotate(job.spec_path, job.spec.model_copy(deep=True), job.result,
                   job.workdir / f"QC_{Path(job.spec.source_name).stem}.xlsx")
    return FileResponse(out, filename=out.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# -------------------------------------------------------------------- build
async def _run_build_job(job: Job, inputs, refs, targets):
    job.status = "running"
    try:
        job.result = await run_build(job.spec, inputs, get_provider(), job.workdir, job.tracer, job.id, targets, refs)
        (job.workdir / "build_result.json").write_text(job.result.model_dump_json(indent=1))
        job.status = "done"
    except Exception as e:
        job.status, job.error = "error", f"{type(e).__name__}: {e}"
        job.tracer.emit("Orchestrator", job.error, "error")
    finally:
        job.tracer.close()


def _tables(paths: list[Path]):
    return {p.stem.upper(): read_table(p) for p in paths}


@app.post("/api/build")
async def start_build(background: BackgroundTasks, standard: Standard = Form(...), spec: UploadFile = File(...),
                      data: list[UploadFile] = File(...), references: list[UploadFile] | None = File(None),
                      targets: str = Form("")):
    job = _new_job("build", standard)
    job.spec_path = await _save(spec, job.workdir / "input" / (spec.filename or "spec.xlsx"))
    try:
        job.spec = load_spec(job.spec_path, standard, spec.filename)
        inputs = _tables([await _save(f, job.workdir / "input" / "data" / f.filename) for f in data])
        refs = _tables([await _save(f, job.workdir / "input" / "reference" / f.filename) for f in references or []])
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    tl = [t.strip().upper() for t in targets.split(",") if t.strip()] or None
    background.add_task(_run_build_job, job, inputs, refs, tl)
    return {"job_id": job.id, "inputs": sorted(inputs), "references": sorted(refs)}


@app.post("/api/build/demo")
async def demo_build(background: BackgroundTasks, standard: Standard = Form(...)):
    base = EXAMPLES / standard.lower()
    if not (base / "spec_final.xlsx").exists():
        raise HTTPException(404, "examples not generated: run `python examples/make_examples.py`")
    job = _new_job("build", standard)
    job.spec_path = base / "spec_final.xlsx"
    job.spec = load_spec(job.spec_path, standard, f"demo_{standard.lower()}_spec_final.xlsx")
    inputs = _tables(sorted((base / ("raw" if standard == "SDTM" else "inputs")).glob("*.csv")))
    refs = _tables(sorted((base / "reference").glob("*.csv")))
    background.add_task(_run_build_job, job, inputs, refs, None)
    return {"job_id": job.id, "inputs": sorted(inputs), "references": sorted(refs)}


@app.get("/api/build/{jid}/download.zip")
def download_build(jid: str):
    job = _get(jid, "build")
    if not job.result:
        raise HTTPException(409, "job not finished")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("programs", "datasets"):
            for f in sorted((job.workdir / sub).glob("*.*")):
                z.write(f, f"{sub}/{f.name}")
        z.writestr("build_report.json", job.result.model_dump_json(indent=1))
        z.writestr("trace.jsonl", "\n".join(e.model_dump_json() for e in job.tracer.events))
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="specforge_build_{jid}.zip"'})


# --------------------------------------------------------------------- jobs
@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    job = _get(jid)
    return {"id": job.id, "kind": job.kind, "standard": job.standard, "status": job.status, "error": job.error,
            "result": job.result.model_dump() if job.result else None,
            "events": [e.model_dump() for e in job.tracer.events]}


@app.get("/api/jobs/{jid}/events")
async def job_events(jid: str):
    job = _get(jid)

    async def stream():
        q = job.tracer.subscribe()
        if job.tracer.closed:
            q.put_nowait(None)
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if ev is None:
                yield f"event: end\ndata: {json.dumps({'status': job.status})}\n\n"
                return
            yield f"data: {ev.model_dump_json()}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
