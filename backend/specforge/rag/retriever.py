"""Hybrid retrieval: BM25 (lexical) + dense vectors, fused with Reciprocal Rank Fusion.

Why hybrid: CDISC questions are full of exact identifiers (AESTDTC, PARAMCD, --DY)
where lexical match matters, plus fuzzy questions ("is this flag convention right?")
where semantic similarity matters. Neither alone is good enough.

Dense backend is pluggable:
  * default `HashingEmbedder` — dependency-free hashed word+char-n-gram TF-IDF vectors,
    deterministic, good enough for a small curated corpus and for CI.
  * `SentenceTransformerEmbedder` if SPECFORGE_EMBEDDINGS=st and the package is installed.

Variable names are expanded to their generic "--" form (AESTDTC -> --STDTC) so a
question about a concrete domain hits knowledge written generically.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
_STOP = set("a an the of and or to in is are be by for on with as at it its this that from into than then "
            "which what when where who should must can may not no if each every per".split())


@dataclass
class Chunk:
    id: str
    source: str
    section: str
    text: str
    tags: set[str] = field(default_factory=set)


def tokenize(text: str) -> list[str]:
    toks: list[str] = []
    for raw in re.findall(r"--[A-Z0-9]+|[A-Za-z0-9]+", text):
        low = raw.lower()
        if low in _STOP or len(low) < 2:
            continue
        toks.append(low)
        # concrete SDTM-style names -> generic form, e.g. AESTDTC -> --stdtc
        if raw.isupper() and 5 <= len(raw) <= 8 and raw[:2].isalpha():
            toks.append("--" + low[2:])
    return toks


# --------------------------------------------------------------------- embedders
class Embedder(Protocol):
    def fit(self, texts: list[str]) -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    def __init__(self, dim: int = 2048) -> None:
        self.dim = dim
        self.idf: dict[int, float] = {}

    def _features(self, text: str) -> Counter:
        feats: Counter = Counter()
        words = tokenize(text)
        for w in words:
            feats[self._h("w:" + w)] += 1
            padded = f"#{w}#"
            for i in range(len(padded) - 2):
                feats[self._h("c:" + padded[i:i + 3])] += 0.3
        for a, b in zip(words, words[1:]):
            feats[self._h(f"b:{a}_{b}")] += 0.7
        return feats

    def _h(self, s: str) -> int:
        return int(hashlib.md5(s.encode()).hexdigest()[:8], 16) % self.dim

    def fit(self, texts: list[str]) -> None:
        df: Counter = Counter()
        for t in texts:
            df.update(set(self._features(t)))
        n = max(len(texts), 1)
        self.idf = {k: math.log((1 + n) / (1 + v)) + 1 for k, v in df.items()}

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for k, v in self._features(t).items():
                out[i, k] = (1 + math.log(v)) * self.idf.get(k, 1.0) if v > 0 else 0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


class SentenceTransformerEmbedder:  # pragma: no cover - optional
    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model)

    def fit(self, texts: list[str]) -> None:
        pass

    def embed(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True))


def default_embedder() -> Embedder:
    if os.getenv("SPECFORGE_EMBEDDINGS") == "st":
        try:
            return SentenceTransformerEmbedder()
        except Exception:
            pass
    return HashingEmbedder()


# ------------------------------------------------------------------------- index
class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.4, b: float = 0.75) -> None:
        self.docs = docs
        self.k1, self.b = k1, b
        self.avgdl = sum(map(len, docs)) / max(len(docs), 1)
        self.tf = [Counter(d) for d in docs]
        df: Counter = Counter()
        for d in docs:
            df.update(set(d))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: list[str]) -> np.ndarray:
        out = np.zeros(len(self.docs))
        for i, tf in enumerate(self.tf):
            dl = len(self.docs[i])
            for q in query:
                if q in tf:
                    f = tf[q]
                    out[i] += self.idf[q] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
        return out


@dataclass
class Hit:
    chunk: Chunk
    score: float
    lexical_rank: int | None
    dense_rank: int | None


class HybridRetriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder | None = None) -> None:
        self.chunks = chunks
        self.embedder = embedder or default_embedder()
        texts = [f"{c.section}\n{c.text}" for c in chunks]
        self.bm25 = BM25([tokenize(t) for t in texts])
        self.embedder.fit(texts)
        self.vectors = self.embedder.embed(texts) if texts else np.zeros((0, 1))

    @classmethod
    def from_markdown_dir(cls, path: Path = KNOWLEDGE_DIR, extra: list[Chunk] | None = None) -> "HybridRetriever":
        chunks: list[Chunk] = []
        for f in sorted(path.glob("*.md")):
            chunks.extend(chunk_markdown(f.read_text(encoding="utf-8"), f.stem))
        return cls(chunks + (extra or []))

    def search(self, query: str, k: int = 4, tags: set[str] | None = None, rrf_k: int = 60) -> list[Hit]:
        if not self.chunks:
            return []
        idx = [i for i, c in enumerate(self.chunks) if not tags or not c.tags or c.tags & tags]
        if not idx:
            return []
        lex = self.bm25.scores(tokenize(query))[idx]
        dense = (self.vectors[idx] @ self.embedder.embed([query])[0]) if len(idx) else np.array([])
        lex_order = [idx[i] for i in np.argsort(-lex) if lex[i] > 0]
        dense_order = [idx[i] for i in np.argsort(-dense) if dense[i] > 0]
        fused: dict[int, float] = {}
        for order in (lex_order, dense_order):
            for rank, i in enumerate(order):
                fused[i] = fused.get(i, 0.0) + 1.0 / (rrf_k + rank + 1)
        best = sorted(fused, key=lambda i: -fused[i])[:k]
        return [Hit(self.chunks[i], round(fused[i], 5),
                    lex_order.index(i) + 1 if i in lex_order else None,
                    dense_order.index(i) + 1 if i in dense_order else None) for i in best]


def chunk_markdown(text: str, source: str, tags: set[str] | None = None) -> list[Chunk]:
    """Split on '## ' headings; each section becomes one chunk."""
    if tags is None:
        low = source.lower()
        tags = {"sdtm"} if "sdtm" in low else {"adam"} if "adam" in low else set()
    chunks, section, buf = [], "Overview", []
    for line in text.splitlines():
        if line.startswith("## "):
            if "".join(buf).strip():
                chunks.append((section, "\n".join(buf).strip()))
            section, buf = line[3:].strip(), []
        elif line.startswith("# ") or line.startswith(">"):
            continue
        else:
            buf.append(line)
    if "".join(buf).strip():
        chunks.append((section, "\n".join(buf).strip()))
    return [Chunk(f"{source}#{i}", source, s, t, set(tags)) for i, (s, t) in enumerate(chunks)]


_DEFAULT: HybridRetriever | None = None


def knowledge_base() -> HybridRetriever:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = HybridRetriever.from_markdown_dir()
    return _DEFAULT
