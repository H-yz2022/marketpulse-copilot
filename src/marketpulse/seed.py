"""Built-in snapshot dataset: instant start-up without waiting on SEC/yfinance.

`export_snapshot()` writes the current database (latest few 10-Ks per ticker,
all price history, fundamentals, sentiment scores) to a small gzipped JSON file that is
committed to the repo (seed/marketpulse_seed.json.gz).

`load_snapshot()` runs on first boot when the database is empty. It restores
the SQL tables and the BM25 chunk mirror in a second or two, so every page,
the SQL explorer and keyword search work immediately. The file also carries
each chunk's embedding (float16), which the vector index picks up lazily on
the first semantic query (`load_vectors`) - so start-up never loads the
embedding model or Chroma, and a small container stays well inside its memory.

Users can still pull real-time data for any ticker with "Refresh live data",
which replaces that ticker's snapshot rows.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from marketpulse import db
from marketpulse.config import BASE_DIR

log = logging.getLogger(__name__)
SEED_PATH = BASE_DIR / "seed" / "marketpulse_seed.json.gz"
FORMAT_VERSION = 1
_EXHIBIT_RE = re.compile(r"^\s*EX-\d", re.IGNORECASE)


def _latest_main_filings(ticker: str, per_ticker: int, db_path: Optional[str]) -> list[dict]:
    kept, seen = [], set()
    for f in db.fetch_filings(ticker, db_path=db_path):  # newest first
        f = dict(f)
        if _EXHIBIT_RE.match(f["excerpt"] or ""):
            continue
        accession = f["filing_id"].partition(":")[0]
        if accession in seen:
            continue
        seen.add(accession)
        kept.append(f)
        if len(kept) >= per_ticker:
            break
    return kept


def _chunk_filing(f: dict) -> tuple[list[str], list[str]]:
    """(chunk ids, chunk texts) exactly as `load_snapshot` will index this filing."""
    from marketpulse.rag.pipeline import chunk_text

    chunks = chunk_text(f["excerpt"] or f["title"] or "")
    return [f"{f['filing_id']}-{i}" for i in range(len(chunks))], chunks


def encode_vectors(filings: list[dict]) -> dict:
    """Embed every chunk of these filings -> compact {"ids", "dim", "f16": base64} block."""
    import numpy as np

    from marketpulse.rag.pipeline import embed_texts

    ids, texts = [], []
    for f in filings:
        i, t = _chunk_filing(f)
        ids += i
        texts += t
    vecs = np.asarray(embed_texts(texts), dtype=np.float16)
    dim = int(vecs.shape[1]) if vecs.size else 0
    return {"ids": ids, "dim": dim, "f16": base64.b64encode(vecs.tobytes()).decode("ascii")}


def export_snapshot(
    path: Path = SEED_PATH, per_ticker: int = 3, db_path: Optional[str] = None, with_vectors: bool = True
) -> dict:
    """Write the snapshot file. Returns a summary of what was exported."""
    tickers = db.list_tickers(db_path=db_path)
    prices, filings, sentiment = [], [], []
    for t in tickers:
        prices += [dict(r) for r in db.fetch_price_history(t, db_path=db_path)]
        kept = _latest_main_filings(t, per_ticker, db_path)
        filings += kept
        ids = {f["filing_id"] for f in kept}
        latest: dict[str, dict] = {}
        for r in db.fetch_sentiment_scores(t, db_path=db_path):
            r = dict(r)
            if r["source_id"] in ids:
                r.pop("id", None)
                latest[r["source_id"]] = r  # rows come oldest first -> keep the newest per filing
        sentiment += list(latest.values())
    payload = {
        "format": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "price_history": prices,
        "filings": filings,
        "sentiment_scores": sentiment,
        "fundamentals": [
            {"ticker": t, "as_of": f.pop("as_of"), "data": f}
            for t, f in db.fetch_fundamentals(tickers, db_path=db_path).items()
        ],
    }
    if with_vectors:
        payload["vectors"] = encode_vectors(filings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return {
        "path": str(path),
        "tickers": tickers,
        "prices": len(prices),
        "filings": len(filings),
        "sentiment": len(sentiment),
        "fundamentals": len(payload["fundamentals"]),
        "vectors": len(payload.get("vectors", {}).get("ids", [])),
        "bytes": path.stat().st_size,
    }


def snapshot_available(path: Path = SEED_PATH) -> bool:
    return path.is_file()


def load_snapshot(path: Path = SEED_PATH, db_path: Optional[str] = None) -> dict:
    """Restore SQL tables + BM25 chunks from the snapshot (no network, no embeddings)."""
    from marketpulse.rag.pipeline import index_document

    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("format") != FORMAT_VERSION:
        raise ValueError(f"Unsupported snapshot format: {payload.get('format')}")

    db.init_db(db_path)
    db.upsert_price_history(payload["price_history"], db_path=db_path)
    for f in payload["filings"]:
        db.upsert_filing(f, db_path=db_path)
    for r in payload["sentiment_scores"]:
        db.insert_sentiment_score(r, db_path=db_path)
    for f in payload.get("fundamentals", []):
        db.upsert_fundamentals(f["ticker"], f["as_of"], f["data"], db_path=db_path)

    n_chunks = 0
    for f in payload["filings"]:
        text = f["excerpt"] or f["title"] or ""  # keep in sync with _chunk_filing
        n_chunks += index_document(
            f["filing_id"],
            text,
            metadata={
                "ticker": f["ticker"],
                "form_type": f["form_type"] or "",
                "filed_date": f["filed_date"] or "",
                "url": f["url"] or "",
            },
            dense=False,
        )

    as_of = payload.get("exported_at", "")
    for t in payload["tickers"]:
        db.set_meta(f"source:{t}", json.dumps({"source": "snapshot", "as_of": as_of}), db_path=db_path)
    return {"tickers": payload["tickers"], "filings": len(payload["filings"]), "chunks": n_chunks, "as_of": as_of}


def backfill_from_snapshot(path: Path = SEED_PATH, db_path: Optional[str] = None) -> dict:
    """Top up an existing database from a newer snapshot without touching live data:
    price history older than each ticker's earliest stored day (so new benchmarks and
    longer history appear) and fundamentals for tickers that have none. Runs once per
    snapshot version. Returns {"prices": rows added, "fundamentals": tickers added}."""
    if not path.is_file():
        return {"prices": 0, "fundamentals": []}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    as_of = payload.get("exported_at", "")
    if db.get_meta("snapshot_backfill", db_path=db_path) == as_of:
        return {"prices": 0, "fundamentals": []}

    earliest: dict[str, str] = {}
    with db.connect(db_path) as conn:
        for r in conn.execute("SELECT ticker, MIN(trade_date) AS d FROM price_history GROUP BY ticker"):
            earliest[r["ticker"]] = r["d"]
    rows = [r for r in payload["price_history"] if r["trade_date"] < earliest.get(r["ticker"], "9999")]
    db.upsert_price_history(rows, db_path=db_path)
    for t in {r["ticker"] for r in rows} - set(earliest):
        db.set_meta(f"source:{t}", json.dumps({"source": "snapshot", "as_of": as_of}), db_path=db_path)

    have = db.fetch_fundamentals([f["ticker"] for f in payload.get("fundamentals", [])], db_path=db_path)
    added = []
    for f in payload.get("fundamentals", []):
        if f["ticker"] not in have:
            db.upsert_fundamentals(f["ticker"], f["as_of"], f["data"], db_path=db_path)
            added.append(f["ticker"])
    db.set_meta("snapshot_backfill", as_of, db_path=db_path)
    return {"prices": len(rows), "fundamentals": sorted(added)}


def load_vectors(path: Path = SEED_PATH) -> dict:
    """{chunk_id: embedding} from the snapshot file; {} if it has none."""
    import numpy as np

    if not path.is_file():
        return {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        block = json.load(fh).get("vectors")
    if not block or not block.get("ids"):
        return {}
    vecs = np.frombuffer(base64.b64decode(block["f16"]), dtype=np.float16).reshape(-1, block["dim"])
    return dict(zip(block["ids"], vecs.astype(np.float32).tolist()))


def data_status(ticker: str, db_path: Optional[str] = None) -> dict:
    """Where a ticker's data came from: {"source": "snapshot"|"live"|"unknown", "as_of": iso}."""
    raw = db.get_meta(f"source:{ticker.upper()}", db_path=db_path)
    if not raw:
        return {"source": "unknown", "as_of": None}
    try:
        return json.loads(raw)
    except ValueError:
        return {"source": "unknown", "as_of": None}
