"""Market data ingestion via yfinance (free, no API key required)."""
from __future__ import annotations

from typing import Optional

from marketpulse.db import upsert_price_history


def fetch_price_history(ticker: str, period: str = "6mo") -> list[dict]:
    """Fetch OHLCV history for a ticker using yfinance.

    Returns a list of row dicts shaped for `db.upsert_price_history`.
    Raises ImportError with a clear message if yfinance isn't installed,
    and re-raises any network error from yfinance so callers can decide
    whether to retry or fall back to cached data.
    """
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - exercised only when dep missing
        raise ImportError(
            "yfinance is required for live market data. Install it with `pip install yfinance`."
        ) from exc

    hist = yf.Ticker(ticker).history(period=period)
    rows = []
    for idx, row in hist.iterrows():
        rows.append(
            {
                "ticker": ticker.upper(),
                "trade_date": idx.strftime("%Y-%m-%d"),
                "open": float(row.get("Open", 0.0) or 0.0),
                "high": float(row.get("High", 0.0) or 0.0),
                "low": float(row.get("Low", 0.0) or 0.0),
                "close": float(row.get("Close", 0.0) or 0.0),
                "volume": int(row.get("Volume", 0) or 0),
            }
        )
    return rows


def ingest_price_history(ticker: str, period: str = "6mo", db_path: Optional[str] = None) -> int:
    """Fetch and persist price history for a ticker. Returns rows written."""
    rows = fetch_price_history(ticker, period=period)
    return upsert_price_history(rows, db_path=db_path)
