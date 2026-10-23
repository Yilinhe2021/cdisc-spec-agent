"""Run a generated program in a separate, resource-limited Python process.

The program only sees pickled input tables in its own job folder and must write
its output there. Limits: wall-clock timeout, CPU seconds and address-space cap
(POSIX). For untrusted multi-tenant use, run the whole backend in the provided
Docker image (no network) — this module is the in-process line of defence.
"""
from __future__ import annotations

import pickle
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

BACKEND_ROOT = Path(__file__).resolve().parents[2]

RUNNER = textwrap.dedent("""
    import sys, pickle, traceback, importlib.util
    sys.path.insert(0, sys.argv[1])
    job = sys.argv[2]
    try:
        spec = importlib.util.spec_from_file_location("program", sys.argv[3])
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        with open(job + "/inputs.pkl", "rb") as fh:
            src = pickle.load(fh)
        out = mod.build(src)
        with open(job + "/output.pkl", "wb") as fh:
            pickle.dump(out, fh)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
""")


@dataclass
class RunResult:
    ok: bool
    output: pd.DataFrame | None
    stderr: str
    seconds_limit: int


def _limits(cpu: int, mem_mb: int):
    def apply():  # pragma: no cover - runs in child
        try:
            import resource

            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            resource.setrlimit(resource.RLIMIT_AS, (mem_mb * 1024 * 1024,) * 2)
        except Exception:
            pass
    return apply


def run_program(code: str, inputs: dict[str, pd.DataFrame], workdir: Path, name: str,
                timeout: int = 120, mem_mb: int = 4096) -> RunResult:
    workdir.mkdir(parents=True, exist_ok=True)
    prog = workdir / f"{name.lower()}.py"
    prog.write_text(code, encoding="utf-8")
    run_dir = workdir / f".run_{name.lower()}"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "output.pkl").unlink(missing_ok=True)
    with (run_dir / "inputs.pkl").open("wb") as fh:
        pickle.dump(inputs, fh)
    (run_dir / "runner.py").write_text(RUNNER, encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-I", str(run_dir / "runner.py"), str(BACKEND_ROOT), str(run_dir), str(prog)],
            capture_output=True, text=True, timeout=timeout, cwd=run_dir,
            preexec_fn=_limits(timeout, mem_mb) if sys.platform != "win32" else None,
        )
    except subprocess.TimeoutExpired:
        return RunResult(False, None, f"Timed out after {timeout}s", timeout)
    out_file = run_dir / "output.pkl"
    if proc.returncode != 0 or not out_file.exists():
        return RunResult(False, None, (proc.stderr or proc.stdout)[-4000:], timeout)
    with out_file.open("rb") as fh:
        df = pickle.load(fh)
    if not isinstance(df, pd.DataFrame):
        return RunResult(False, None, f"build() returned {type(df).__name__}, expected DataFrame", timeout)
    return RunResult(True, df, proc.stderr[-2000:], timeout)
