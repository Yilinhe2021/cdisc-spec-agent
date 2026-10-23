"""Wire the QC agents into a graph and run it."""
from __future__ import annotations

from collections import Counter

from ..llm import LLMProvider
from ..models import QCResult, Spec
from ..orchestration import Context, Graph, Tracer
from ..rag.feedback import FeedbackMemory
from ..rag.retriever import HybridRetriever, chunk_markdown, knowledge_base
from .agents import (ClarityReviewer, ConsistencyReviewer, IntakeAgent, JudgeAgent, RuleEngineAgent,
                     StandardsReviewer)


def build_graph() -> Graph:
    g = Graph()
    g.add(IntakeAgent())
    for reviewer in (RuleEngineAgent(), ClarityReviewer(), StandardsReviewer(), ConsistencyReviewer()):
        g.add(reviewer, deps=["Intake"], optional=not isinstance(reviewer, RuleEngineAgent))
    g.add(JudgeAgent(), deps=["RuleEngine", "ClarityReviewer", "StandardsReviewer", "ConsistencyReviewer"])
    return g


async def run_qc(spec: Spec, llm: LLMProvider, tracer: Tracer | None = None, job_id: str = "local",
                 support_docs: dict[str, str] | None = None) -> QCResult:
    tracer = tracer or Tracer()
    kb = knowledge_base()
    if support_docs:  # study documents (SAP, protocol notes...) become extra retrievable context for this job
        extra = [c for name, text in support_docs.items() for c in chunk_markdown(text, f"study:{name}", set())]
        kb = HybridRetriever(kb.chunks + extra)
        tracer.emit("Intake", f"indexed {len(extra)} chunks from {len(support_docs)} study document(s)", "tool")
    ctx = Context(llm=llm, tracer=tracer, state={
        "spec": spec, "kb": kb, "feedback": FeedbackMemory(), "coverage": [], "results": {}})

    async def on_done(name, result):
        ctx.state["results"][name] = result

    tracer.emit("Orchestrator", f"QC started: {spec.source_name} ({spec.standard}) with {llm.name}/{llm.model}", "start")
    results = await build_graph().run(ctx, on_done)
    findings = results["Judge"]
    sev = Counter(f.severity.value for f in findings)
    cat = Counter(f.category.value for f in findings)
    by_agent = Counter(a for f in findings for a in [f.agent] + [m.split(":")[0] for m in f.merged_from])
    summary = {
        "total": len(findings), "by_severity": dict(sev), "by_category": dict(cat), "by_agent": dict(by_agent),
        "rows_flagged": len({(f.dataset, f.variable) for f in findings if f.variable}),
        "profile": results["Intake"], "llm": llm.usage(),
    }
    tracer.emit("Orchestrator", f"QC finished: {len(findings)} findings", "done", summary=summary)
    return QCResult(job_id=job_id, standard=spec.standard, spec_name=spec.source_name, summary=summary,
                    findings=findings, coverage=ctx.state["coverage"])
