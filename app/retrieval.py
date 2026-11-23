"""Small TF-IDF retriever over markdown docs.

It keeps the project dependency-free and easy to read. In client work the same
interface is backed by embeddings in pgvector, Qdrant or a managed vector store;
only `Retriever.search` needs to change.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "get",
    "got",
    "happen",
    "has",
    "have",
    "help",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "its",
    "know",
    "like",
    "long",
    "many",
    "me",
    "much",
    "my",
    "need",
    "of",
    "on",
    "or",
    "our",
    "please",
    "should",
    "so",
    "tell",
    "that",
    "the",
    "there",
    "this",
    "to",
    "want",
    "was",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}
TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    out = []
    for word in TOKEN.findall(text.lower()):
        if word in STOPWORDS or len(word) < 2:
            continue
        stem = _stem(word)
        if stem not in STOPWORDS:
            out.append(stem)
    return out


def _stem(word: str) -> str:
    """Very small suffix stripper; enough to match "takes"/"take" or "arrived"/"arrives"."""
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        word = word[:-2]
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    return word


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    text: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # BM25 score, used for ranking
    coverage: float  # share of the query's meaning (idf-weighted) found in the chunk, 0..1


def chunk_markdown(path: Path) -> list[Chunk]:
    """Split a markdown file into one chunk per `##` section."""
    raw = path.read_text(encoding="utf-8")
    doc_title = path.stem.replace("-", " ").title()
    sections: list[tuple[str, list[str]]] = []
    current_title, lines = doc_title, []
    for line in raw.splitlines():
        if line.startswith("# "):
            doc_title = current_title = line[2:].strip()
            continue
        if line.startswith("## "):
            if any(s.strip() for s in lines):
                sections.append((current_title, lines))
            current_title, lines = line[3:].strip(), []
            continue
        lines.append(line)
    if any(s.strip() for s in lines):
        sections.append((current_title, lines))

    chunks = []
    for i, (title, body) in enumerate(sections):
        text = " ".join(" ".join(body).split())
        chunks.append(Chunk(id=f"{path.stem}#{i}", source=path.name, title=title, text=text))
    return chunks


class Retriever:
    """BM25 ranking plus an idf-weighted coverage score used as a relevance gate.

    Coverage answers "how much of the question does this chunk actually talk about".
    A question like "who is your CEO?" matches the word "name" somewhere but has
    low coverage, so the agent treats it as unanswered instead of guessing.
    """

    k1 = 1.2
    b = 0.75

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._tfs = [Counter(tokenize(f"{c.title} {c.text}")) for c in chunks]
        self._lens = [sum(tf.values()) for tf in self._tfs]
        self._avg_len = (sum(self._lens) / len(self._lens)) if self._lens else 1.0
        df: Counter[str] = Counter()
        for tf in self._tfs:
            df.update(tf.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self._unseen_idf = math.log(1 + (n + 0.5) / 0.5)

    @classmethod
    def from_dir(cls, docs_dir: Path) -> Retriever:
        chunks: list[Chunk] = []
        for path in sorted(docs_dir.glob("*.md")):
            chunks.extend(chunk_markdown(path))
        return cls(chunks)

    def search(self, query: str, k: int = 4) -> list[Hit]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms:
            return []
        weights = {t: self._idf.get(t, self._unseen_idf) for t in terms}
        total = sum(weights.values())
        hits = []
        for chunk, tf, length in zip(self.chunks, self._tfs, self._lens, strict=True):
            score, covered = 0.0, 0.0
            for t in terms:
                f = tf.get(t, 0)
                if not f:
                    continue
                covered += weights[t]
                norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self._avg_len))
                score += self._idf[t] * norm
            if score > 0:
                hits.append(Hit(chunk, round(score, 3), round(covered / total, 3)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
