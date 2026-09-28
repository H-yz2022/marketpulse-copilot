"""Retrieval-augmented generation over SEC filing text using ChromaDB + Claude.

Chunking and retrieval work fully offline (Chroma's default embedding
function downloads a small local model the first time it runs, then it's
cached). Only the final answer-generation step calls the Anthropic API, and
it's isolated behind a swappable `generate_fn` so tests/demos can run
without a real API key.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from marketpulse.config import settings
from marketpulse.db import delete_chunks_for_ticker, upsert_chunks

_CLIENT = None
_COLLECTION_NAME = "filings"


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Split text into overlapping ~chunk_size-character chunks for embedding/retrieval.

    Sentence-aware: when a sentence boundary (". ") falls in the last 40% of a
    window, the chunk ends there instead of mid-sentence, so each chunk tends
    to hold whole risk-factor statements. `overlap` characters are repeated
    between consecutive chunks so a statement split across a boundary is still
    retrievable from either side. Tune size/overlap against real questions
    with scripts/eval_retrieval.py (Recall@k / MRR) rather than guessing.
    """
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            cut = text.rfind(". ", start + int(chunk_size * 0.6), end)
            if cut != -1:
                end = cut + 1
        chunks.append(text[start:end].strip())
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return [c for c in chunks if c]


def _get_collection():
    global _CLIENT
    import chromadb

    if _CLIENT is None:
        _CLIENT = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return _CLIENT.get_or_create_collection(_COLLECTION_NAME)


def index_document(doc_id: str, text: str, metadata: dict) -> int:
    """Chunk a filing and add it to the vector store. Returns chunk count."""
    chunks = chunk_text(text)
    if not chunks:
        return 0
    collection = _get_collection()
    ids = [f"{doc_id}-{i}" for i in range(len(chunks))]
    metadatas = [dict(metadata, chunk_index=i) for i in range(len(chunks))]
    collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
    upsert_chunks(
        [
            {
                "chunk_id": cid,
                "doc_id": doc_id,
                "ticker": str(meta.get("ticker", "")).upper(),
                "chunk_index": meta["chunk_index"],
                "text": chunk,
                "metadata_json": json.dumps(meta),
            }
            for cid, chunk, meta in zip(ids, chunks, metadatas)
        ]
    )
    return len(chunks)


def delete_ticker_documents(ticker: str) -> None:
    """Remove every indexed chunk for a ticker from the vector store.

    `index_document` only ever upserts by chunk ID, so a filing that stops
    being re-fetched (an older 10-K displaced by a newer one, or a filing
    indexed under an earlier, wider search before ingestion was narrowed to
    the most recent filings only) is never cleaned up on its own - it just
    keeps winning retrieval alongside, or instead of, the current data.
    Callers that want a clean re-index (like the dashboard's refresh button)
    should call this before re-ingesting.
    """
    collection = _get_collection()
    collection.delete(where={"ticker": ticker.upper()})
    delete_chunks_for_ticker(ticker)


def reset_client() -> None:
    """Drop the cached Chroma client so the next call reconnects from scratch.

    Needed after deleting the persisted Chroma directory out from under a
    long-running process (e.g. scripts/reset_data.py deleting data/chroma/
    while the Streamlit dashboard is still running in the same session) -
    without this, the already-initialized client would keep pointing at
    on-disk files that no longer exist.
    """
    global _CLIENT
    _CLIENT = None


def retrieve(query: str, n_results: int = 8, where: Optional[dict] = None) -> list[dict]:
    """Retrieve the most relevant indexed chunks for a natural-language query.

    Defaults to 8, not 4: SEC filings open their risk-factors section with
    near-identical boilerplate ("This discussion of risk factors contains
    forward-looking statements..."), so the first couple of chunks from any
    indexed 10-K tend to score well against almost any question in this
    domain. A small n_results can fill up entirely with that intro text
    before reaching the specific risks further into the document; asking for
    more chunks gives the LLM a real chance to see past the intro.
    """
    collection = _get_collection()
    results = collection.query(query_texts=[query], n_results=n_results, where=where)
    hits = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0] if results.get("distances") else [None] * len(docs)
    ids = results.get("ids", [[]])[0] if results.get("ids") else [None] * len(docs)
    for cid, doc, meta, dist in zip(ids, docs, metas, dists):
        hits.append({"id": cid, "text": doc, "metadata": meta, "distance": dist})
    return hits


RAG_SYSTEM = (
    "You are a financial research assistant. Answer the question using ONLY the numbered filing "
    "excerpts provided. Cite excerpts inline like [1] or [2][3]. If the excerpts don't contain "
    "the answer, say so explicitly rather than guessing. Be concise: short paragraphs or bullets."
)


def format_context(hits: list[dict]) -> str:
    """Number each retrieved chunk and label it with its source filing."""
    parts = []
    for i, h in enumerate(hits, start=1):
        m = h.get("metadata") or {}
        label = " ".join(x for x in (m.get("ticker"), m.get("form_type"), m.get("filed_date")) if x)
        parts.append(f"[{i}] ({label})\n{h['text']}")
    return "\n\n---\n\n".join(parts)


def _default_generate_answer(question: str, context_chunks: list[str]) -> str:
    """Call Claude to answer a question grounded in retrieved chunks."""
    from marketpulse.llm.client import complete_text

    context = "\n\n---\n\n".join(f"[{i}] {c}" for i, c in enumerate(context_chunks, start=1))
    return complete_text(RAG_SYSTEM, f"Filing excerpts:\n{context}\n\nQuestion: {question}", max_tokens=700)


def answer_question(
    question: str,
    n_results: int = 8,
    where: Optional[dict] = None,
    generate_fn: Optional[Callable[[str, list[str]], str]] = None,
) -> dict:
    """Retrieve relevant filing chunks and generate a grounded answer.

    Pass `generate_fn` to swap in a mock/local model for tests or demos
    that shouldn't require an Anthropic API key.
    """
    hits = retrieve(question, n_results=n_results, where=where)
    context_chunks = [h["text"] for h in hits]
    if not context_chunks:
        return {
            "answer": (
                "No indexed filings matched this question yet. Refresh a ticker's data first "
                "(the refresh button in the app, or scripts/run_pipeline.py)."
            ),
            "sources": [],
        }
    generate = generate_fn or _default_generate_answer
    answer = generate(question, context_chunks)
    return {"answer": answer, "sources": hits}
