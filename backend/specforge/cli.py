"""Command line entry point.

  specforge qc    SPEC --standard SDTM [--docs sap.md ...] [--out annotated.xlsx]
  specforge build SPEC --standard ADaM --data DM.csv AE.csv [--reference ADSL.csv] [--out outdir]
  specforge serve [--port 8000]
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from .llm import get_provider
from .orchestration import Tracer


def _print_events(tracer: Tracer) -> None:
    orig = tracer.emit

    def emit(agent, message, kind="info", **data):
        print(f"  [{agent:>20}] {message}")
        return orig(agent, message, kind, **data)
    tracer.emit = emit  # type: ignore[method-assign]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="specforge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("qc", help="review a spec")
    q.add_argument("spec", type=Path)
    q.add_argument("--standard", choices=["SDTM", "ADaM"], required=True)
    q.add_argument("--docs", nargs="*", type=Path, default=[])
    q.add_argument("--out", type=Path)
    q.add_argument("--llm")
    b = sub.add_parser("build", help="generate programs + datasets")
    b.add_argument("spec", type=Path)
    b.add_argument("--standard", choices=["SDTM", "ADaM"], required=True)
    b.add_argument("--data", nargs="+", type=Path, required=True)
    b.add_argument("--reference", nargs="*", type=Path, default=[])
    b.add_argument("--targets", nargs="*")
    b.add_argument("--out", type=Path, default=Path("specforge_out"))
    b.add_argument("--llm")
    s = sub.add_parser("serve", help="run the web app")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("specforge.api.app:app", host=a.host, port=a.port)
        return

    from .spec.parser import load_spec

    spec = load_spec(a.spec, a.standard)
    tracer = Tracer()
    _print_events(tracer)
    if a.cmd == "qc":
        from .qc.annotate import annotate
        from .qc.pipeline import run_qc

        docs = {p.name: p.read_text(encoding="utf-8") for p in a.docs}
        res = asyncio.run(run_qc(spec, get_provider(a.llm), tracer, support_docs=docs))
        for f in res.findings:
            print(f"{f.severity.value:9} {f.target:22} row {str(f.row or '-'):>4}  {f.message}")
        out = a.out or a.spec.with_name(f"QC_{a.spec.stem}.xlsx")
        annotate(a.spec, spec, res, out)
        print(f"\n{len(res.findings)} findings -> {out}")
    else:
        from .build.pipeline import read_table, run_build

        inputs = {p.stem.upper(): read_table(p) for p in a.data}
        refs = {p.stem.upper(): read_table(p) for p in a.reference}
        res = asyncio.run(run_build(spec, inputs, get_provider(a.llm), a.out, tracer,
                                    targets=[t.upper() for t in a.targets] if a.targets else None, references=refs))
        for d in res.datasets:
            conc = f", reference match {d.concordance['concordance_pct']}%" if d.concordance else ""
            print(f"{d.dataset:8} {d.status:9} {d.rows} rows, {len(d.issues)} issues{conc}")
        print(f"\nprograms -> {a.out / 'programs'}   datasets -> {a.out / 'datasets'}")


if __name__ == "__main__":
    main()
