"""Reviewer feedback memory ("calibration library").

Every accept / dismiss a human makes in the UI is stored. Two uses:
  1. The Judge agent lowers confidence of new findings that look like ones a human
     dismissed before (same rule, similar message) and raises it for accepted ones.
  2. LLM reviewers get the most similar past decisions as few-shot calibration
     examples, so the system learns a team's review taste without fine-tuning.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from ..models import Finding, now
from .retriever import Chunk, HybridRetriever

_LOCK = threading.Lock()


def _store_path() -> Path:
    p = Path(os.getenv("SPECFORGE_DATA_DIR", Path.cwd() / ".specforge")) / "feedback.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def record(finding: Finding, decision: str, note: str = "") -> None:
    entry = {"ts": now(), "decision": decision, "note": note, "rule_id": finding.rule_id,
             "category": finding.category.value, "dataset": finding.dataset, "variable": finding.variable,
             "message": finding.message}
    with _LOCK, _store_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def load() -> list[dict]:
    p = _store_path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


class FeedbackMemory:
    def __init__(self) -> None:
        self.entries = load()
        chunks = [Chunk(f"fb#{i}", "feedback", e["rule_id"], f"{e['rule_id']} {e['variable']} {e['message']}")
                  for i, e in enumerate(self.entries)]
        self.index = HybridRetriever(chunks) if chunks else None

    def similar(self, finding: Finding, k: int = 3, min_score: float = 0.025) -> list[dict]:
        if not self.index:
            return []
        hits = self.index.search(f"{finding.rule_id} {finding.variable} {finding.message}", k=k)
        out = []
        for h in hits:
            e = self.entries[int(h.chunk.id.split("#")[1])]
            if e["rule_id"] == finding.rule_id and h.score >= min_score:
                out.append(e)
        return out

    def examples(self, query: str, k: int = 4) -> list[dict]:
        if not self.index:
            return []
        return [self.entries[int(h.chunk.id.split("#")[1])] for h in self.index.search(query, k=k)]
