"""Built-in snapshot dataset: instant start-up without waiting on SEC/yfinance.

`export_snapshot()` writes the current database (latest few 10-Ks per ticker,
all price history, sentiment scores) to a small gzipped JSON file that is
committed to the repo (seed/marketpulse_seed.json.gz).

`load_snapshot()` runs on first boot when the database is empty. It restores
the SQL tables and the BM25 chunk mirror in a second or two, so every page,
the SQL explorer and keyword search work immediately. Vector embeddings are
built afterwards in a background thread (`start_background_embedding`);
until they finish, hybrid retrieval simply runs on BM25 alone.

Users can still pull real-time data for any ticker with "Refresh live data",
which replaces that ticker's snapshot rows.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
import threading
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


def export_snapshot(path: Path = SEED_PATH, per_ticker: int = 3, db_path: Optional[str] = None) -> dict:
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
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    return {
        "path": str(path),
        "tickers": tickers,
        "prices": len(prices),
        "filings": len(filings),
        "sentiment": len(sentiment),
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

    n_chunks = 0
    for f in payload["filings"]:
        text = f["excerpt"] or f["title"] or ""
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


def start_background_embedding() -> threading.Thread:
    """Embed the snapshot's chunks into Chroma without blocking start-up."""

    def run() -> None:
        from marketpulse.rag.pipeline import embed_stored_chunks

        try:
            n = embed_stored_chunks()
            log.info("Background embedding finished: %d chunks", n)
        except Exception:  # noqa: BLE001 - keyword search still works without vectors
            log.exception("Background embedding failed; retrieval will use BM25 only")

    thread = threading.Thread(target=run, name="embed-snapshot", daemon=True)
    thread.start()
    return thread


def data_status(ticker: str, db_path: Optional[str] = None) -> dict:
    """Where a ticker's data came from: {"source": "snapshot"|"live"|"unknown", "as_of": iso}."""
    raw = db.get_meta(f"source:{ticker.upper()}", db_path=db_path)
    if not raw:
        return {"source": "unknown", "as_of": None}
    try:
        return json.loads(raw)
    except ValueError:
        return {"source": "unknown", "as_of": None}
