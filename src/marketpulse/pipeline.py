"""End-to-end ingestion for one ticker: prices -> fundamentals -> filings -> sentiment -> vector index.

Shared by the CLI (`scripts/run_pipeline.py`), the API's refresh endpoint and
the first-boot auto-seed, so there is exactly one definition of "refresh".

This is a *refresh*, not an append: the ticker's existing filings, sentiment
rows and indexed chunks are cleared first. Every write below is an
upsert-by-ID, which on its own would never remove a filing that stops being
re-fetched (e.g. an older 10-K displaced by a newer one) - those used to
accumulate and dilute retrieval with stale data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from marketpulse.db import (
    delete_filings_for_ticker,
    delete_sentiment_scores_for_ticker,
    fetch_filings,
    fetch_price_history,
    init_db,
    set_meta,
)
from marketpulse.ingestion.filings import ingest_filings_for_ticker
from marketpulse.ingestion.fundamentals import ingest_fundamentals
from marketpulse.ingestion.market_data import ingest_price_history
from marketpulse.nlp.sentiment import score_and_store
from marketpulse.rag.pipeline import delete_ticker_documents, index_document

log = logging.getLogger(__name__)
HISTORY_PERIOD = "10y"  # long enough for calendar-year returns and multi-year risk windows


def _refresh_fundamentals(t: str, db_path: Optional[str]) -> bool:
    try:
        return ingest_fundamentals(t, db_path=db_path)
    except Exception:  # noqa: BLE001 - fundamentals are enrichment; prices and filings still count
        log.exception("Fundamentals fetch failed for %s", t)
        return False


def refresh_ticker(
    ticker: str,
    period: str = HISTORY_PERIOD,
    progress: Optional[Callable[[str], None]] = None,
    db_path: Optional[str] = None,
) -> dict:
    """Rebuild all stored data for a ticker. Returns counts for each stage."""
    say = progress or (lambda msg: log.info(msg))
    t = ticker.upper()
    init_db(db_path)

    say(f"Clearing existing data for {t}")
    delete_filings_for_ticker(t, db_path=db_path)
    delete_sentiment_scores_for_ticker(t, source_type="filing", db_path=db_path)
    delete_ticker_documents(t)

    say(f"Fetching {period} of price history for {t}")
    n_prices = ingest_price_history(t, period=period, db_path=db_path)

    say(f"Fetching fundamentals, ownership and insider trades for {t}")
    has_fundamentals = _refresh_fundamentals(t, db_path)

    say(f"Searching SEC EDGAR for {t} 10-K filings")
    n_filings = ingest_filings_for_ticker(t, db_path=db_path)

    say("Scoring sentiment and indexing filing text")
    n_indexed = 0
    n_chunks = 0
    for filing in fetch_filings(t, db_path=db_path):
        text = filing["excerpt"] or filing["title"] or ""
        if not text:
            continue
        score_and_store(t, text, source_type="filing", source_id=filing["filing_id"], db_path=db_path)
        n_chunks += index_document(
            filing["filing_id"],
            text,
            metadata={
                "ticker": t,
                "form_type": filing["form_type"] or "",
                "filed_date": filing["filed_date"] or "",
                "url": filing["url"] or "",
            },
        )
        n_indexed += 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    set_meta(f"source:{t}", json.dumps({"source": "live", "as_of": now}), db_path=db_path)
    return {
        "ticker": t,
        "prices": n_prices,
        "fundamentals": has_fundamentals,
        "filings": n_filings,
        "indexed": n_indexed,
        "chunks": n_chunks,
    }


def refresh_prices(ticker: str, period: str = HISTORY_PERIOD, db_path: Optional[str] = None) -> dict:
    """Prices + fund data only, for benchmarks (index ETFs have no 10-K filings)."""
    t = ticker.upper()
    n_prices = ingest_price_history(t, period=period, db_path=db_path)
    if n_prices:
        _refresh_fundamentals(t, db_path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        set_meta(f"source:{t}", json.dumps({"source": "live", "as_of": now}), db_path=db_path)
    return {"ticker": t, "prices": n_prices, "filings": 0, "indexed": 0, "chunks": 0}


def sync_benchmarks(until: str, benchmarks: Optional[list[str]] = None, db_path: Optional[str] = None) -> list[str]:
    """Refresh any benchmark whose prices stop before `until` (a trade date), so a
    freshly refreshed company still lines up with its market reference. Best effort."""
    from marketpulse.config import settings

    updated = []
    for b in benchmarks or settings.benchmarks:
        rows = fetch_price_history(b, db_path=db_path)
        if rows and rows[-1]["trade_date"] >= until:
            continue
        try:
            if refresh_prices(b, db_path=db_path)["prices"]:
                updated.append(b)
        except Exception:  # noqa: BLE001 - a benchmark hiccup must not fail the company refresh
            log.exception("Benchmark refresh failed for %s", b)
    return updated
