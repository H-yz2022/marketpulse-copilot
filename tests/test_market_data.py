import sys
import types

import pandas as pd
import pytest

from marketpulse.db import fetch_price_history
from marketpulse.ingestion import market_data


class _FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def history(self, period="6mo"):
        idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
        return pd.DataFrame(
            {
                "Open": [100.0, 101.0],
                "High": [102.0, 103.0],
                "Low": [99.0, 100.0],
                "Close": [101.0, 102.5],
                "Volume": [1_000_000, 1_100_000],
            },
            index=idx,
        )


def test_fetch_price_history(monkeypatch):
    fake_module = types.ModuleType("yfinance")
    fake_module.Ticker = _FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)

    rows = market_data.fetch_price_history("AAPL", period="6mo")
    assert len(rows) == 2
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["trade_date"] == "2026-01-02"
    assert rows[1]["close"] == 102.5


def test_ingest_price_history_writes_to_db(monkeypatch, tmp_path):
    fake_module = types.ModuleType("yfinance")
    fake_module.Ticker = _FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_module)

    db_path = str(tmp_path / "test.db")
    written = market_data.ingest_price_history("AAPL", db_path=db_path)
    assert written == 2

    rows = fetch_price_history("AAPL", db_path=db_path)
    assert len(rows) == 2


def test_sync_benchmarks_refreshes_only_stale_ones(tmp_path, monkeypatch):
    from marketpulse import db, pipeline

    path = str(tmp_path / "b.db")
    for t, last in (("SPY", "2026-03-30"), ("QQQ", "2026-02-01")):
        db.upsert_price_history([{"ticker": t, "trade_date": last, "open": 1, "high": 1, "low": 1, "close": 1,
                                  "volume": 1}], db_path=path)
    called = []
    monkeypatch.setattr(pipeline, "refresh_prices", lambda t, db_path=None: called.append(t) or {"prices": 3})
    updated = pipeline.sync_benchmarks("2026-03-30", benchmarks=["SPY", "QQQ", "IWM"], db_path=path)
    assert called == updated == ["QQQ", "IWM"]  # SPY is current; IWM has no rows at all


def test_refresh_skips_vector_index_when_ai_is_off(tmp_path, monkeypatch):
    import dataclasses

    from marketpulse import db, pipeline

    path = str(tmp_path / "r.db")
    monkeypatch.setattr(pipeline, "settings", dataclasses.replace(pipeline.settings, ai_enabled=False))
    monkeypatch.setattr(pipeline, "delete_ticker_documents", lambda t: pytest.fail("Chroma must not load"))
    monkeypatch.setattr(pipeline, "ingest_price_history", lambda t, period, db_path: 1)
    monkeypatch.setattr(pipeline, "ingest_fundamentals", lambda t, db_path: True)
    monkeypatch.setattr(pipeline, "ingest_filings_for_ticker", lambda t, db_path: 1)
    monkeypatch.setattr(pipeline, "score_and_store", lambda *a, **k: None)
    seen = []
    monkeypatch.setattr(pipeline, "index_document", lambda *a, **k: seen.append(k["dense"]) or 1)
    db.upsert_filing({"filing_id": "A-1", "ticker": "AAPL", "form_type": "10-K", "filed_date": "2026-01-01",
                      "title": "t", "url": "", "excerpt": "risk text"}, db_path=path)
    monkeypatch.setattr(pipeline, "delete_filings_for_ticker", lambda t, db_path: 0)
    assert pipeline.refresh_ticker("AAPL", db_path=path)["chunks"] == 1
    assert seen == [False]
