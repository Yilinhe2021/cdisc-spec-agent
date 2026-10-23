"""MCP server: expose SpecForge to any MCP client (Claude Desktop, Claude Code, IDE agents).

    python -m specforge.mcp_server            # stdio transport

Tools: review_spec, build_datasets, search_knowledge, list_rules. Paths are local
files on the machine running the server.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]

from .build.pipeline import read_table, run_build
from .llm import get_provider
from .qc.pipeline import run_qc
from .qc.rules import RULES
from .rag.retriever import knowledge_base
from .spec.parser import load_spec

mcp = _Server("specforge", instructions="QC CDISC SDTM/ADaM specifications and generate datasets from them.")


@mcp.tool()
async def review_spec(spec_path: str, standard: str = "SDTM", max_findings: int = 50) -> list[dict]:
    """Run the multi-agent QC on a spec workbook (.xlsx/.csv). Returns ranked findings."""
    spec = load_spec(spec_path, standard)  # type: ignore[arg-type]
    res = await run_qc(spec, get_provider())
    return [f.model_dump(include={"severity", "category", "dataset", "variable", "row", "rule_id", "message",
                                  "suggestion"}) for f in res.findings[:max_findings]]


@mcp.tool()
async def build_datasets(spec_path: str, data_paths: list[str], standard: str = "SDTM",
                         output_dir: str | None = None, reference_paths: list[str] | None = None) -> dict:
    """Generate programs and datasets from a reviewed spec and source tables (file stem = table name)."""
    spec = load_spec(spec_path, standard)  # type: ignore[arg-type]
    inputs = {Path(p).stem.upper(): read_table(Path(p)) for p in data_paths}
    refs = {Path(p).stem.upper(): read_table(Path(p)) for p in reference_paths or []}
    out = Path(output_dir or tempfile.mkdtemp(prefix="specforge_"))
    res = await run_build(spec, inputs, get_provider(), out, references=refs)
    return {"output_dir": str(out), "datasets": [
        {"dataset": d.dataset, "status": d.status, "rows": d.rows, "issues": d.issues,
         "concordance_pct": d.concordance["concordance_pct"] if d.concordance else None} for d in res.datasets]}


@mcp.tool()
def search_knowledge(query: str, k: int = 4) -> list[dict]:
    """Hybrid (BM25 + vector) search over the SpecForge knowledge base."""
    return [{"source": h.chunk.source, "section": h.chunk.section, "text": h.chunk.text, "score": h.score}
            for h in knowledge_base().search(query, k=k)]


@mcp.tool()
def list_rules(standard: str | None = None) -> list[dict]:
    """List deterministic QC rules."""
    return [{"id": r.id, "title": r.title, "severity": r.severity.value, "standards": list(r.standards)}
            for r in RULES.values() if not standard or standard in r.standards]


if __name__ == "__main__":
    mcp.run()
