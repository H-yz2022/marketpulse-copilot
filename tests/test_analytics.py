import pytest

from marketpulse import analytics
from tests.fakes import seed_db


def test_max_drawdown():
    assert analytics.max_drawdown([100, 120, 90, 130]) == -25.0
    assert analytics.max_drawdown([1, 2, 3]) == 0.0


def test_price_summary_empty():
    assert analytics.price_summary([]) == {"has_data": False}


def test_price_summary_values():
    rows = [{"trade_date": f"2026-01-{i:02d}", "close": c, "volume": 10} for i, c in enumerate([100, 110, 99], 1)]
    s = analytics.price_summary(rows)
    assert s["last_close"] == 99
    assert s["change_1d_pct"] == -10.0
    assert s["return_period_pct"] == -1.0
    assert s["max_drawdown_pct"] == -10.0
    assert s["volatility_ann_pct"] > 0


def test_sentiment_summary_net_index():
    rows = [
        {"label": "positive", "score": 0.9},
        {"label": "negative", "score": 0.3},
        {"label": "neutral", "score": 0.5},
    ]
    s = analytics.sentiment_summary(rows)
    assert s["counts"] == {"positive": 1, "negative": 1, "neutral": 1}
    assert s["net_index"] == pytest.approx(0.2)
    assert s["tone"] == "positive"
    assert analytics.sentiment_summary([])["tone"] == "no data"


def test_correlation():
    assert analytics.correlation([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert analytics.correlation([1, 2, 3, 4], [8, 6, 4, 2]) == -1.0
    assert analytics.correlation([1, 2], [1, 2]) is None


def test_watchlist(tmp_path):
    path = str(tmp_path / "w.db")
    seed_db(path)
    w = analytics.watchlist(["aapl", "MSFT", "NOPE"], db_path=path)
    assert [r["ticker"] for r in w["tickers"]] == ["AAPL", "MSFT", "NOPE"]
    assert w["tickers"][2]["has_data"] is False
    assert w["correlation"]["tickers"] == ["AAPL", "MSFT"]
    assert w["correlation"]["matrix"][0][0] == 1.0
    assert w["portfolio"]["best"] == "AAPL" and w["portfolio"]["worst"] == "MSFT"
    assert w["performance"]["AAPL"][0]["value"] == 100.0


def test_ticker_overview_shape(tmp_path):
    path = str(tmp_path / "o.db")
    seed_db(path)
    o = analytics.ticker_overview("aapl", db_path=path)
    assert o["ticker"] == "AAPL"
    assert len(o["prices"]) == 30
    assert o["filings"][0]["excerpt_preview"] == "Risk factors text"
    assert "excerpt" not in o["filings"][0]
