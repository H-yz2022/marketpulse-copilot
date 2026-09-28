import sys
import types

import pandas as pd

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
