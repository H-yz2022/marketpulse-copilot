"""Hybrid retrieval: query rewrite -> BM25 + dense vectors -> Reciprocal Rank Fusion.

Why hybrid? The two retrievers fail in opposite ways on SEC filings:

* **Dense** (Chroma embeddings) matches meaning - "supply chain problems" finds
  "disruptions at contract manufacturers" - but is weak on exact tokens such as
  tickers, product names, form numbers or rare terms ("Rule 10b5-1", "CHIPS Act").
* **BM25** (keyword) nails exact and rare tokens but misses paraphrases.

Fusing both with RRF (score = sum 1/(k + rank)) needs no score calibration
between the two very different scoring scales, which is why it's the common
default in production RAG.

Query rewrite (optional, one cheap LLM call) turns a chatty question into a
retrieval-friendly query plus keywords. The *original* query is always kept as
one of the fused queries, so a bad rewrite can only add candidates - it can't
hide the results the user's own words would have found.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Callable, Optional

from marketpulse import db

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\.]*[a-z0-9]|[a-z0-9]")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with we our "
    "us may could can such any other which these those their there been being not no than into also".split()
)
RRF_K = 60


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP]


class BM25:
    """Okapi BM25 over an in-memory list of documents (fine at our corpus size)."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(d)) for d in docs]
        self.lens = [sum(tf.values()) for tf in self.tfs]
        self.avgdl = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter = Counter()
        for tf in self.tfs:
            df.update(tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, dl in zip(self.tfs, self.lens):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    norm = 1 - self.b + self.b * dl / (self.avgdl or 1)
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * norm)
            out.append(s)
        return out


def bm25_search(query: str, n_results: int = 8, where: Optional[dict] = None, db_path: Optional[str] = None):
    rows = db.fetch_chunks(ticker=(where or {}).get("ticker"), db_path=db_path)
    if not rows:
        return []
    index = BM25([r["text"] for r in rows])
    scored = sorted(zip(index.scores(query), rows), key=lambda x: x[0], reverse=True)
    return [
        {
            "id": r["chunk_id"],
            "text": r["text"],
            "metadata": json.loads(r["metadata_json"] or "{}"),
            "bm25": round(s, 3),
        }
        for s, r in scored[:n_results]
        if s > 0
    ]


def rrf_fuse(ranked_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion. Items are matched by their chunk `id`."""
    fused: dict[str, dict] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst, start=1):
            key = hit.get("id") or hit["text"][:80]
            entry = fused.setdefault(key, {**hit, "rrf": 0.0, "matched_by": []})
            entry["rrf"] += 1.0 / (k + rank)
            entry["matched_by"].append(hit.get("_source", "?"))
    return sorted(fused.values(), key=lambda h: h["rrf"], reverse=True)


REWRITE_SYSTEM = """Rewrite a user's question about companies' SEC 10-K risk factors into a search query.
Return JSON: {"query": concise keyword-rich rewrite, "keywords": [3-6 exact terms likely in the filing text]}.
Keep company names and tickers. Do not add facts."""


def rewrite_query(question: str, client: Any = None) -> dict:
    from marketpulse.llm.client import complete_json

    out = complete_json(REWRITE_SYSTEM, question, max_tokens=200, client=client)
    return {"query": str(out.get("query") or question), "keywords": [str(k) for k in out.get("keywords") or []][:6]}


def hybrid_retrieve(
    query: str,
    n_results: int = 6,
    where: Optional[dict] = None,
    rewrite: Optional[dict] = None,
    dense_fn: Optional[Callable[..., list[dict]]] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Dense + BM25 for the original query (and the rewrite, if given), fused with RRF."""
    if dense_fn is None:
        from marketpulse.rag.pipeline import retrieve as dense_fn

    queries = [query]
    if rewrite:
        queries.append(rewrite["query"])
        if rewrite.get("keywords"):
            queries.append(" ".join(rewrite["keywords"]))

    lists = []
    for q in dict.fromkeys(queries):  # de-dupe, keep order
        dense = [{**h, "_source": "dense"} for h in dense_fn(q, n_results=n_results * 2, where=where)]
        sparse = [{**h, "_source": "bm25"} for h in bm25_search(q, n_results * 2, where, db_path)]
        lists.extend([dense, sparse])
    fused = rrf_fuse(lists)[:n_results]
    for h in fused:
        h.pop("_source", None)
        h["matched_by"] = sorted(set(h["matched_by"]))
    return fused
