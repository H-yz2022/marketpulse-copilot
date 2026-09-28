"""Offline retrieval evaluation: how do chunk size, overlap and retriever choice affect recall?

This is how chunking parameters are *chosen* rather than guessed. For each
configuration we re-chunk the stored 10-K excerpts, run every question in
eval/retrieval_eval.json, and count a hit when a top-k chunk for the right
ticker contains one of the expected phrases (a cheap, transparent relevance
proxy - swap in human labels or an LLM judge for a stricter eval).

Metrics: Recall@k (did any top-k chunk hit?) and MRR (how high was the first hit?).

Usage (after ingesting some tickers with scripts/run_pipeline.py):
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --k 3 --sizes 400 800 1200 --overlaps 0 100 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from marketpulse import db  # noqa: E402
from marketpulse.rag.hybrid import BM25, rrf_fuse  # noqa: E402
from marketpulse.rag.pipeline import chunk_text  # noqa: E402


def build_corpus(size: int, overlap: int) -> list[dict]:
    corpus = []
    for t in db.list_tickers():
        for f in db.fetch_filings(t):
            for i, c in enumerate(chunk_text(f["excerpt"] or "", chunk_size=size, overlap=overlap)):
                corpus.append({"id": f"{f['filing_id']}-{i}", "ticker": t, "text": c})
    return corpus


def dense_ranker(corpus: list[dict]):
    """In-memory Chroma collection (same default embedding model as production), or None."""
    try:
        import chromadb
    except ImportError:
        return None
    client = chromadb.EphemeralClient()
    col = client.create_collection(f"eval-{abs(hash(len(corpus)))}-{id(corpus)}")
    for start in range(0, len(corpus), 200):
        batch = corpus[start : start + 200]
        col.add(ids=[c["id"] for c in batch], documents=[c["text"] for c in batch],
                metadatas=[{"ticker": c["ticker"]} for c in batch])

    def rank(q: str, ticker: str, k: int) -> list[str]:
        r = col.query(query_texts=[q], n_results=k, where={"ticker": ticker})
        return r["ids"][0]

    return rank


def evaluate(corpus, questions, k):
    by_id = {c["id"]: c for c in corpus}
    bm25_idx = {}
    for t in {c["ticker"] for c in corpus}:
        docs = [c for c in corpus if c["ticker"] == t]
        bm25_idx[t] = (docs, BM25([d["text"] for d in docs]))

    def bm25(q, t, n):
        if t not in bm25_idx:
            return []
        docs, idx = bm25_idx[t]
        ranked = sorted(zip(idx.scores(q), docs), key=lambda x: x[0], reverse=True)
        return [d["id"] for s, d in ranked[:n] if s > 0]

    dense = dense_ranker(corpus)
    methods = {"bm25": bm25}
    if dense:
        methods["dense"] = dense
        methods["hybrid"] = lambda q, t, n: [
            h["id"] for h in rrf_fuse([[{"id": i, "text": ""} for i in dense(q, t, n * 2)],
                                       [{"id": i, "text": ""} for i in bm25(q, t, n * 2)]])[:n]
        ]

    results = {}
    for name, fn in methods.items():
        hits, rr = 0, 0.0
        for item in questions:
            ids = fn(item["q"], item["ticker"], k)
            for rank, cid in enumerate(ids, start=1):
                text = f" {by_id[cid]['text'].lower()} "
                if any(p.lower() in text for p in item["must_contain"]):
                    hits += 1
                    rr += 1 / rank
                    break
        n = len(questions)
        results[name] = {"recall@k": round(hits / n, 3), "mrr": round(rr / n, 3)}
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--sizes", type=int, nargs="+", default=[400, 800, 1200])
    ap.add_argument("--overlaps", type=int, nargs="+", default=[0, 100, 200])
    ap.add_argument("--eval-file", default=str(ROOT / "eval" / "retrieval_eval.json"))
    args = ap.parse_args()

    questions = json.loads(Path(args.eval_file).read_text())
    have = set(db.list_tickers())
    questions = [q for q in questions if q["ticker"] in have]
    if not questions:
        sys.exit("No eval questions match ingested tickers - run scripts/run_pipeline.py first.")

    print(f"{len(questions)} questions, k={args.k}\n")
    print(f"{'size':>6} {'overlap':>8} {'chunks':>7}  " + "  ".join(f"{m:>18}" for m in ("bm25", "dense", "hybrid")))
    for size in args.sizes:
        for overlap in args.overlaps:
            if overlap >= size:
                continue
            corpus = build_corpus(size, overlap)
            res = evaluate(corpus, questions, args.k)
            cells = [
                f"R={res[m]['recall@k']:.2f} MRR={res[m]['mrr']:.2f}" if m in res else f"{'n/a':>18}"
                for m in ("bm25", "dense", "hybrid")
            ]
            print(f"{size:>6} {overlap:>8} {len(corpus):>7}  " + "  ".join(f"{c:>18}" for c in cells))


if __name__ == "__main__":
    main()
