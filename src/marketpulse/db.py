"""SQLite storage layer for MarketPulse Copilot.

Kept as plain `sqlite3` (no ORM) so it's easy to read end to end in a code
review, and easy to swap `db_path` for a Postgres connection string later
without dragging in SQLAlchemy just for three tables.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional, Sequence

from marketpulse.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS price_history (
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS filings (
    filing_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    form_type TEXT,
    filed_date TEXT,
    title TEXT,
    url TEXT,
    excerpt TEXT
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT,
    scored_date TEXT NOT NULL,
    label TEXT NOT NULL,
    score REAL NOT NULL,
    text_snippet TEXT
);

-- Mirror of every chunk in the vector store, so the BM25 (keyword) half of
-- hybrid retrieval can score the exact same units the dense half returns.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chunks_ticker ON chunks (ticker);

-- Small key/value store for app state (e.g. where each ticker's data came from).
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One row per billed LLM call; backs the per-client and global daily caps.
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usage_date TEXT NOT NULL,
    client_id TEXT NOT NULL,
    feature TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_date ON llm_usage (usage_date, client_id);
CREATE INDEX IF NOT EXISTS idx_sentiment_ticker ON sentiment_scores (ticker, scored_date);
CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings (ticker, filed_date);
"""

# Tables the natural-language SQL feature is allowed to read, with a short
# description of each column. This is what gets shown to the LLM as the
# schema - deliberately excluding internal tables like llm_usage.
PUBLIC_SCHEMA_DOC = """
price_history(ticker TEXT, trade_date TEXT 'YYYY-MM-DD', open REAL, high REAL, low REAL, close REAL, volume INTEGER)
  -- one row per ticker per trading day; primary key (ticker, trade_date)
filings(filing_id TEXT, ticker TEXT, form_type TEXT e.g. '10-K', filed_date TEXT 'YYYY-MM-DD', title TEXT, url TEXT,
        excerpt TEXT -- risk-factor section text)
sentiment_scores(id INTEGER, ticker TEXT, source_type TEXT e.g. 'filing', source_id TEXT -- filings.filing_id,
        scored_date TEXT 'YYYY-MM-DD', label TEXT one of 'positive'|'negative'|'neutral', score REAL 0..1 confidence,
        text_snippet TEXT)
""".strip()

PUBLIC_TABLES = frozenset({"price_history", "filings", "sentiment_scores"})


class DataNotFoundError(LookupError):
    """Requested ticker/data isn't in the database yet (maps to HTTP 404)."""


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or settings.db_path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def upsert_price_history(rows: Sequence[dict], db_path: Optional[str] = None) -> int:
    if not rows:
        return 0
    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO price_history (ticker, trade_date, open, high, low, close, volume)
            VALUES (:ticker, :trade_date, :open, :high, :low, :close, :volume)
            ON CONFLICT(ticker, trade_date) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
            """,
            rows,
        )
    return len(rows)


def upsert_filing(row: dict, db_path: Optional[str] = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO filings (filing_id, ticker, form_type, filed_date, title, url, excerpt)
            VALUES (:filing_id, :ticker, :form_type, :filed_date, :title, :url, :excerpt)
            ON CONFLICT(filing_id) DO UPDATE SET
                ticker=excluded.ticker, form_type=excluded.form_type,
                filed_date=excluded.filed_date, title=excluded.title,
                url=excluded.url, excerpt=excluded.excerpt
            """,
            row,
        )


def insert_sentiment_score(row: dict, db_path: Optional[str] = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO sentiment_scores (ticker, source_type, source_id, scored_date, label, score, text_snippet)
            VALUES (:ticker, :source_type, :source_id, :scored_date, :label, :score, :text_snippet)
            """,
            row,
        )
        return cur.lastrowid


def fetch_price_history(ticker: str, db_path: Optional[str] = None) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM price_history WHERE ticker = ? ORDER BY trade_date", (ticker.upper(),)
        )
        return cur.fetchall()


def fetch_sentiment_scores(ticker: str, db_path: Optional[str] = None) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM sentiment_scores WHERE ticker = ? ORDER BY scored_date", (ticker.upper(),)
        )
        return cur.fetchall()


def fetch_filings(ticker: str, db_path: Optional[str] = None) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM filings WHERE ticker = ? ORDER BY filed_date DESC", (ticker.upper(),)
        )
        return cur.fetchall()


def delete_filings_for_ticker(ticker: str, db_path: Optional[str] = None) -> int:
    """Delete every filings row for a ticker. Returns the number of rows removed.

    Used to make re-ingestion a true *refresh* rather than an accumulation:
    without this, re-running the pipeline for a ticker only ever adds/updates
    filings by ID, so a filing that drops out of the current search results
    (e.g. an older 10-K, once a newer one takes its place) is never removed
    and just lingers in the database forever.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        cur = conn.execute("DELETE FROM filings WHERE ticker = ?", (ticker.upper(),))
        return cur.rowcount


def delete_sentiment_scores_for_ticker(
    ticker: str, source_type: Optional[str] = None, db_path: Optional[str] = None
) -> int:
    """Delete sentiment_scores rows for a ticker (optionally scoped to one
    source_type, e.g. "filing"). Returns the number of rows removed.

    `insert_sentiment_score` always inserts a new row rather than replacing
    one for the same document - by design, so a ticker's sentiment can be
    tracked *over time* - but that means re-scoring the same filings on every
    pipeline run just piles up duplicate rows for the same day. Callers that
    want a clean re-score (like the dashboard's refresh button) should call
    this first.
    """
    init_db(db_path)
    with connect(db_path) as conn:
        if source_type:
            cur = conn.execute(
                "DELETE FROM sentiment_scores WHERE ticker = ? AND source_type = ?",
                (ticker.upper(), source_type),
            )
        else:
            cur = conn.execute("DELETE FROM sentiment_scores WHERE ticker = ?", (ticker.upper(),))
        return cur.rowcount


def list_tickers(db_path: Optional[str] = None) -> list[str]:
    """Every ticker that has any price history stored, alphabetically."""
    init_db(db_path)
    with connect(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT ticker FROM price_history ORDER BY ticker").fetchall()
        return [r["ticker"] for r in rows]


def get_readonly_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open the database in SQLite read-only mode (``mode=ro``).

    Used for running LLM-generated SQL: even if every other guard failed,
    SQLite itself will refuse to write through this connection.
    """
    path = db_path or settings.db_path
    init_db(path)
    conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def record_llm_usage(client_id: str, feature: str, usage_date: str, db_path: Optional[str] = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO llm_usage (usage_date, client_id, feature) VALUES (?, ?, ?)",
            (usage_date, client_id, feature),
        )


def count_llm_usage(usage_date: str, client_id: Optional[str] = None, db_path: Optional[str] = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        if client_id is None:
            row = conn.execute("SELECT COUNT(*) AS n FROM llm_usage WHERE usage_date = ?", (usage_date,)).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM llm_usage WHERE usage_date = ? AND client_id = ?",
                (usage_date, client_id),
            ).fetchone()
        return int(row["n"])


def upsert_chunks(rows: Sequence[dict], db_path: Optional[str] = None) -> int:
    if not rows:
        return 0
    init_db(db_path)
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO chunks (chunk_id, doc_id, ticker, chunk_index, text, metadata_json)
            VALUES (:chunk_id, :doc_id, :ticker, :chunk_index, :text, :metadata_json)
            ON CONFLICT(chunk_id) DO UPDATE SET text=excluded.text, metadata_json=excluded.metadata_json
            """,
            rows,
        )
    return len(rows)


def fetch_chunks(ticker: Optional[str] = None, db_path: Optional[str] = None) -> list[sqlite3.Row]:
    init_db(db_path)
    with connect(db_path) as conn:
        if ticker:
            return conn.execute("SELECT * FROM chunks WHERE ticker = ?", (ticker.upper(),)).fetchall()
        return conn.execute("SELECT * FROM chunks").fetchall()


def delete_chunks_for_ticker(ticker: str, db_path: Optional[str] = None) -> int:
    init_db(db_path)
    with connect(db_path) as conn:
        return conn.execute("DELETE FROM chunks WHERE ticker = ?", (ticker.upper(),)).rowcount


def set_meta(key: str, value: str, db_path: Optional[str] = None) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str, default: Optional[str] = None, db_path: Optional[str] = None) -> Optional[str]:
    init_db(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
