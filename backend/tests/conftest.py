import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SPECFORGE_LLM", "mock")
EX = ROOT / "examples"


@pytest.fixture(scope="session", autouse=True)
def examples():
    if not (EX / "sdtm" / "spec_final.xlsx").exists():
        import subprocess
        subprocess.run([sys.executable, str(EX / "make_examples.py")], check=True)
    return EX


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPECFORGE_DATA_DIR", str(tmp_path / "data"))
    return tmp_path
