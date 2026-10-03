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


# --------------------------------------------------------------------------- benchmark-relative analytics
def _add_benchmark(path: str, symbol: str = "SPY") -> None:
    from marketpulse import db

    closes, c = [], 400.0
    for i in range(30):
        c *= 1 + (0.01 if i % 2 else -0.006)
        closes.append(c)
    db.upsert_price_history(
        [{"ticker": symbol, "trade_date": f"2026-03-{i + 1:02d}", "open": v, "high": v, "low": v, "close": v,
          "volume": 1} for i, v in enumerate(closes)],
        db_path=path,
    )


def test_risk_metrics_against_itself_and_a_levered_copy():
    m = [0.01, -0.02, 0.015, 0.003, -0.007, 0.012, -0.004]
    same = analytics.risk_metrics(m, m)
    assert same["beta"] == 1.0 and same["correlation"] == 1.0 and same["r_squared_pct"] == 100.0
    assert same["tracking_error_pct"] == 0.0 and same["excess_return_pct"] == 0.0 and same["alpha_pct"] == 0.0
    levered = analytics.risk_metrics([2 * x for x in m], m)
    assert levered["beta"] == 2.0 and levered["idio_vol_pct"] == 0.0
    assert levered["up_capture_pct"] == levered["down_capture_pct"] == 200.0
    assert levered["var95_pct"] < same["var95_pct"] < 0
    assert analytics.risk_metrics([0.01]) == {}


def test_risk_metrics_risk_free_rate_lowers_sharpe():
    r = [0.004, -0.001, 0.003, 0.002, -0.002, 0.005]
    assert analytics.risk_metrics(r, rf_pct=5)["sharpe"] < analytics.risk_metrics(r)["sharpe"]


def test_market_analytics_portfolio_and_benchmark(tmp_path):
    path = str(tmp_path / "m.db")
    seed_db(path)
    _add_benchmark(path)
    a = analytics.market_analytics(["aapl", "MSFT", "NOPE"], benchmark="spy", weights={"AAPL": 3, "MSFT": 1},
                                   db_path=path)
    assert a["benchmark"] == {"symbol": "SPY", "name": "S&P 500", "has_data": True}
    assert a["missing"] == ["NOPE"] and a["n_days"] == 29
    aapl = next(r for r in a["tickers"] if r["ticker"] == "AAPL")
    assert {"beta", "alpha_pct", "r_squared_pct", "sharpe", "var95_pct"} <= set(aapl["metrics"])
    assert a["benchmark_metrics"]["beta"] == 1.0
    p = a["portfolio"]
    assert p["weights"] == {"AAPL": 75.0, "MSFT": 25.0}
    assert sum(p["risk_contribution_pct"].values()) == pytest.approx(100.0, abs=0.2)
    assert p["series"][0]["value"] == 100.0 and p["metrics"]["beta"] is not None
    assert a["correlation"]["tickers"] == ["AAPL", "MSFT", "SPY"]
    assert set(a["series"]["relative"]) == {"AAPL", "MSFT"}
    assert a["series"]["relative"]["AAPL"][0]["value"] == 100.0
    assert set(a["monthly"]["rows"]) == {"Portfolio", "AAPL", "MSFT", "SPY"}


def test_market_analytics_windows_and_equal_weight_default(tmp_path):
    path = str(tmp_path / "w.db")
    seed_db(path)
    _add_benchmark(path)
    one_month = analytics.market_analytics(["AAPL", "MSFT"], range_="1M", db_path=path)
    assert one_month["n_days"] == 21 and one_month["start_date"] == "2026-03-09"
    assert one_month["portfolio"]["weights"] == {"AAPL": 50.0, "MSFT": 50.0}
    no_bench = analytics.market_analytics(["AAPL"], benchmark="QQQ", db_path=path)
    assert no_bench["benchmark"]["has_data"] is False and "beta" not in no_bench["tickers"][0]["metrics"]
    assert no_bench["series"]["relative"] == {} and no_bench["benchmark_metrics"] is None


def test_window_ytd_starts_at_prior_year_close():
    dates = ["2025-12-30", "2025-12-31", "2026-01-02", "2026-01-05"]
    assert analytics._window(dates, "YTD") == ["2025-12-31", "2026-01-02", "2026-01-05"]
    assert analytics._window(dates, "1M") == dates


def _ohlcv(closes, vols=None, spread=1.0):
    vols = vols or [100] * len(closes)
    return [{"trade_date": f"2026-01-{i + 1:02d}", "open": c, "high": c + spread, "low": c - spread, "close": c,
             "volume": v} for i, (c, v) in enumerate(zip(closes, vols))]


def test_trading_activity_buying_vs_selling_pressure():
    # Heavy volume on up days, light on down days -> buying pressure.
    closes = [10, 11, 10.5, 11.5, 11, 12]
    vols = [100, 300, 100, 300, 100, 300]
    a = analytics.trading_activity(_ohlcv(closes, vols), shares=10_000)
    assert a["up_volume_pct"] == 81.8  # 900 up-day shares vs 200 down-day shares
    assert a["avg_dollar_volume"] > 0 and a["turnover_pct"] == 2.0
    # Closing at the top of each day's range = accumulation (CMF +1); at the bottom = distribution.
    top = [{"trade_date": "d", "high": 11, "low": 9, "close": 11, "volume": 10}] * 3
    bottom = [{"trade_date": "d", "high": 11, "low": 9, "close": 9, "volume": 10}] * 3
    assert analytics.trading_activity(top)["cmf_20"] == 1.0
    assert analytics.trading_activity(bottom)["cmf_window"] == -1.0


def test_technicals_and_rsi():
    rising = _ohlcv([float(i) for i in range(1, 260)])
    t = analytics.technicals(rising)
    assert t["rsi14"] == 100.0 and t["sma50_gap_pct"] > 0 and t["sma200_gap_pct"] > t["sma50_gap_pct"]
    assert t["range_52w_pos_pct"] > 95
    assert analytics._rsi([1, 2]) is None


def test_yearly_returns_and_cagr():
    dates = ["2024-06-03", "2024-12-31", "2025-06-02", "2025-12-31", "2026-03-02"]
    closes = [100, 110, 99, 121, 133.1]
    assert analytics._period_returns(dates, closes, 4) == {"2024": 10.0, "2025": 10.0, "2026": 10.0}
    assert analytics._cagr(["2020-01-01", "2022-01-01"], [100, 121]) == pytest.approx(10.0, abs=0.02)
    assert analytics._cagr(["2026-01-01", "2026-06-01"], [100, 121]) is None  # under a year: not annualised


def test_rolling_beta_matches_direct_computation():
    import random

    rnd = random.Random(7)
    m = [rnd.gauss(0, 0.01) for _ in range(120)]
    r = [1.3 * x + rnd.gauss(0, 0.005) for x in m]
    dates = [str(i) for i in range(121)]
    fast = analytics._rolling_beta(dates, r, m, 30)
    i = 75
    direct = analytics._cov(r[i - 29 : i + 1], m[i - 29 : i + 1]) / analytics._cov(m[i - 29 : i + 1], m[i - 29 : i + 1])
    point = next(p for p in fast if p["date"] == dates[i + 1])
    assert point["value"] == pytest.approx(direct, abs=1e-3) and len(fast) == 120 - 29


def test_thin_keeps_last_point_and_short_series():
    pts = [{"date": str(i), "value": i} for i in range(2000)]
    thin = analytics._thin(pts, max_points=500)
    assert len(thin) <= 501 and thin[-1] == pts[-1] and thin[0] == pts[0]
    assert analytics._thin(pts[:100]) == pts[:100]


def test_market_analytics_activity_fundamentals_and_yearly(tmp_path):
    from marketpulse import db

    path = str(tmp_path / "y.db")
    seed_db(path)
    _add_benchmark(path)
    aapl_fund = {"pe_trailing": 30.0, "dividend_yield_pct": 0.5, "sector": "Technology", "target_mean": 200.0,
                 "float_shares": 1e6}
    db.upsert_fundamentals("AAPL", "2026-03-30", aapl_fund, db_path=path)
    db.upsert_fundamentals("MSFT", "2026-03-30", {"pe_trailing": 20.0, "sector": "Technology"}, db_path=path)
    a = analytics.market_analytics(["AAPL", "MSFT"], range_="MAX", db_path=path)
    aapl = a["tickers"][0]
    assert aapl["fundamentals"]["pe_trailing"] == 30.0 and aapl["activity"]["turnover_pct"] is not None
    assert {"rsi14", "range_52w_pos_pct"} <= set(aapl["technicals"])
    pf = a["portfolio"]["fundamentals"]
    assert pf["pe_trailing"] == 24.0  # harmonic: 1 / (0.5/30 + 0.5/20)
    assert pf["dividend_yield_pct"] == 0.25 and pf["sectors"] == {"Technology": 100.0}
    assert a["yearly"]["years"] == ["2026"] and set(a["yearly"]["rows"]) == {"Portfolio", "AAPL", "MSFT", "SPY"}
    assert set(a["series"]["money_flow"]) == {"AAPL", "MSFT"}
    assert a["benchmark_activity"]["up_volume_pct"] is not None and "rsi14" in a["benchmark_technicals"]
