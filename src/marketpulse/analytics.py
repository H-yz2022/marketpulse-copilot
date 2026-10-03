"""Pure-Python market analytics: returns, risk, benchmark-relative stats, sentiment, correlation.

Everything here takes plain lists of row dicts (as returned by `db.fetch_*`)
and returns JSON-serialisable dicts, so it's trivially unit-testable and is
reused by the REST API, the watchlist view and the analyst agent's tools.
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Iterable, Mapping, Optional, Sequence

from marketpulse import db

TRADING_DAYS = 252


def _closes(rows: Sequence[Mapping]) -> list[tuple[str, float]]:
    return [(r["trade_date"], float(r["close"])) for r in rows if r["close"] is not None and float(r["close"]) > 0]


def daily_returns(closes: Sequence[float]) -> list[float]:
    return [(b / a) - 1.0 for a, b in zip(closes, closes[1:]) if a]


def _pct(a: float, b: float) -> Optional[float]:
    return round((b / a - 1.0) * 100.0, 2) if a else None


def max_drawdown(closes: Sequence[float]) -> float:
    """Largest peak-to-trough fall, as a negative percentage (e.g. -18.4)."""
    peak = -math.inf
    worst = 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            worst = min(worst, c / peak - 1.0)
    return round(worst * 100.0, 2)


def price_summary(rows: Sequence[Mapping], window: int = TRADING_DAYS) -> dict:
    """KPI tiles over the last `window` trading days (one year by default) of a ticker's history."""
    rows = list(rows)[-(window + 1):]
    series = _closes(rows)
    if not series:
        return {"has_data": False}
    dates, closes = zip(*series)
    rets = daily_returns(closes)
    vol = pstdev(rets) * math.sqrt(TRADING_DAYS) * 100.0 if len(rets) > 1 else None
    idx_30 = max(0, len(closes) - 22)  # ~1 trading month
    volumes = [int(r["volume"] or 0) for r in rows]
    return {
        "has_data": True,
        "start_date": dates[0],
        "end_date": dates[-1],
        "last_close": round(closes[-1], 2),
        "change_1d_pct": _pct(closes[-2], closes[-1]) if len(closes) > 1 else None,
        "return_1m_pct": _pct(closes[idx_30], closes[-1]),
        "return_period_pct": _pct(closes[0], closes[-1]),
        "volatility_ann_pct": round(vol, 2) if vol is not None else None,
        "max_drawdown_pct": max_drawdown(closes),
        "period_high": round(max(closes), 2),
        "period_low": round(min(closes), 2),
        "avg_volume": int(mean(volumes)) if volumes else 0,
        "n_days": len(closes),
    }


def _signed(label: str, score: float) -> float:
    label = (label or "").lower()
    if label == "positive":
        return float(score)
    if label == "negative":
        return -float(score)
    return 0.0


def sentiment_summary(rows: Sequence[Mapping]) -> dict:
    """Aggregate sentiment rows into counts plus a net index in [-1, 1]."""
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    signed = []
    for r in rows:
        label = (r["label"] or "neutral").lower()
        counts[label] = counts.get(label, 0) + 1
        signed.append(_signed(label, r["score"]))
    net = round(mean(signed), 3) if signed else None
    if net is None:
        tone = "no data"
    elif net > 0.15:
        tone = "positive"
    elif net < -0.15:
        tone = "negative"
    else:
        tone = "mixed"
    return {"counts": counts, "n": len(signed), "net_index": net, "tone": tone}


def rebased_series(rows: Sequence[Mapping], base: float = 100.0) -> list[dict]:
    series = _closes(rows)
    if not series:
        return []
    first = series[0][1]
    return [{"date": d, "value": round(c / first * base, 2)} for d, c in series]


def correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = mean(a), mean(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    vb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if va == 0 or vb == 0:
        return None
    return round(cov / (va * vb), 3)


def _aligned_returns(price_rows: Mapping[str, Sequence[Mapping]]) -> dict[str, list[float]]:
    """Daily returns per ticker computed only over dates *every* ticker traded."""
    by_ticker = {t: dict(_closes(rows)) for t, rows in price_rows.items()}
    if not by_ticker:
        return {}
    common = sorted(set.intersection(*(set(d) for d in by_ticker.values())))
    return {t: daily_returns([m[d] for d in common]) for t, m in by_ticker.items()}


def watchlist(tickers: Iterable[str], db_path: Optional[str] = None) -> dict:
    """Portfolio-level view: per-ticker KPIs, rebased performance, correlations."""
    tickers = [t.upper() for t in tickers]
    # Last year only: this view (and the AI tools built on it) describes "the period" as one year.
    price_rows = {
        t: [dict(r) for r in db.fetch_price_history(t, db_path=db_path)][-(TRADING_DAYS + 1):] for t in tickers
    }
    price_rows = {t: rows for t, rows in price_rows.items() if rows}
    rows_out = []
    for t in tickers:
        s = sentiment_summary([dict(r) for r in db.fetch_sentiment_scores(t, db_path=db_path)])
        p = price_summary(price_rows.get(t, []))
        rows_out.append({"ticker": t, **p, "sentiment": s})

    rets = _aligned_returns(price_rows)
    names = list(rets)
    matrix = [[1.0 if a == b else correlation(rets[a], rets[b]) for b in names] for a in names]

    have = [r for r in rows_out if r.get("has_data")]
    equal_weight = round(mean(r["return_period_pct"] for r in have), 2) if have else None
    sentiments = [r["sentiment"]["net_index"] for r in rows_out if r["sentiment"]["net_index"] is not None]
    return {
        "tickers": rows_out,
        "performance": {t: rebased_series(rows) for t, rows in price_rows.items()},
        "correlation": {"tickers": names, "matrix": matrix},
        "portfolio": {
            "equal_weight_return_pct": equal_weight,
            "avg_net_sentiment": round(mean(sentiments), 3) if sentiments else None,
            "best": max(have, key=lambda r: r["return_period_pct"])["ticker"] if have else None,
            "worst": min(have, key=lambda r: r["return_period_pct"])["ticker"] if have else None,
        },
    }


def ticker_overview(ticker: str, db_path: Optional[str] = None) -> dict:
    """Everything the dashboard page needs for one ticker in one payload."""
    t = ticker.upper()
    prices = [dict(r) for r in db.fetch_price_history(t, db_path=db_path)]
    sentiment = [dict(r) for r in db.fetch_sentiment_scores(t, db_path=db_path)]
    filings = [dict(r) for r in db.fetch_filings(t, db_path=db_path)]
    for f in filings:
        f["excerpt_preview"] = (f.pop("excerpt", "") or "")[:400]
    from marketpulse.seed import data_status

    return {
        "ticker": t,
        "data_status": data_status(t, db_path=db_path),
        "fundamentals": db.fetch_fundamentals([t], db_path=db_path).get(t),
        "summary": price_summary(prices),
        "sentiment": sentiment_summary(sentiment),
        "prices": [
            {k: r[k] for k in ("trade_date", "open", "high", "low", "close", "volume")} for r in prices
        ],
        "sentiment_rows": [
            {k: r[k] for k in ("scored_date", "label", "score", "source_id", "text_snippet")} for r in sentiment
        ],
        "filings": filings,
    }


# --------------------------------------------------------------------------- benchmark-relative analytics
RANGES = {"1M": 21, "3M": 63, "6M": 126, "YTD": None, "1Y": 252, "3Y": 756, "5Y": 1260, "MAX": None, "ALL": None}
ROLLING_WINDOW = 63  # ~one quarter of trading days
FLOW_WINDOW = 20  # Chaikin Money Flow lookback
MAX_POINTS = 520  # chart series are thinned to about this many points; metrics always use every day


def _r(v: Optional[float], digits: int = 2, scale: float = 1.0) -> Optional[float]:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return round(v * scale, digits)


def _cov(a: Sequence[float], b: Sequence[float]) -> float:
    ma, mb = mean(a), mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)


def _percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile, q in [0, 100]."""
    s = sorted(xs)
    k = (len(s) - 1) * q / 100.0
    lo = math.floor(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _growth(rets: Sequence[float]) -> list[float]:
    out, g = [1.0], 1.0
    for r in rets:
        g *= 1.0 + r
        out.append(g)
    return out


def _thin(points: list[dict], max_points: int = MAX_POINTS) -> list[dict]:
    """Every k-th point (always keeping the last) so multi-year charts stay light."""
    if len(points) <= max_points * 1.2:
        return points
    step = math.ceil(len(points) / max_points)
    out = points[::step]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


def risk_metrics(rets: Sequence[float], bench: Optional[Sequence[float]] = None, rf_pct: float = 0.0) -> dict:
    """Return, risk and risk-adjusted statistics for one daily-return series.

    With `bench` (same-length benchmark returns) it adds the market-relative
    set: beta (systematic risk), Jensen's alpha, correlation, R-squared (share
    of variance the market explains), idiosyncratic volatility, tracking error,
    information ratio, up/down capture and excess return. Percentages are in
    percent; ratios are plain numbers. Annualised with 252 trading days.
    """
    n = len(rets)
    if n < 2:
        return {}
    rf_d = (1.0 + rf_pct / 100.0) ** (1.0 / TRADING_DAYS) - 1.0
    growth = _growth(rets)
    total = growth[-1] - 1.0
    ann_ret = growth[-1] ** (TRADING_DAYS / n) - 1.0 if growth[-1] > 0 else None
    vol = pstdev(rets) * math.sqrt(TRADING_DAYS)
    excess = [r - rf_d for r in rets]
    ann_excess = mean(excess) * TRADING_DAYS
    downside = math.sqrt(mean(min(0.0, e) ** 2 for e in excess)) * math.sqrt(TRADING_DAYS)
    mdd = max_drawdown(growth) / 100.0
    var95 = _percentile(rets, 5)
    tail = [r for r in rets if r <= var95]
    out = {
        "return_pct": _r(total, scale=100),
        "ann_return_pct": _r(ann_ret, scale=100),
        "ann_vol_pct": _r(vol, scale=100),
        "downside_dev_pct": _r(downside, scale=100),
        "sharpe": _r(ann_excess / vol) if vol else None,
        "sortino": _r(ann_excess / downside) if downside else None,
        "max_drawdown_pct": _r(mdd, scale=100),
        "calmar": _r(ann_ret / abs(mdd)) if mdd and ann_ret is not None else None,
        "var95_pct": _r(var95, scale=100),
        "cvar95_pct": _r(mean(tail), scale=100) if tail else None,
        "best_day_pct": _r(max(rets), scale=100),
        "worst_day_pct": _r(min(rets), scale=100),
        "pct_up_days": _r(sum(1 for r in rets if r > 0) / n, 1, 100),
    }
    if bench is None or len(bench) != n:
        return out

    var_m = _cov(bench, bench)
    var_r = _cov(rets, rets)
    if var_m == 0:
        return out
    cov = _cov(rets, bench)
    beta = cov / var_m
    corr = cov / math.sqrt(var_m * var_r) if var_r else None
    alpha = (mean(rets) - rf_d - beta * (mean(bench) - rf_d)) * TRADING_DAYS
    resid_var = max(0.0, var_r - beta * beta * var_m)
    diff = [r - m for r, m in zip(rets, bench)]
    te = pstdev(diff) * math.sqrt(TRADING_DAYS)
    up = [(r, m) for r, m in zip(rets, bench) if m > 0]
    down = [(r, m) for r, m in zip(rets, bench) if m < 0]

    def capture(pairs: list[tuple[float, float]]) -> Optional[float]:
        mm = mean(m for _, m in pairs) if pairs else 0.0
        return mean(r for r, _ in pairs) / mm * 100.0 if pairs and mm else None

    out.update(
        {
            "beta": _r(beta),
            "alpha_pct": _r(alpha, scale=100),
            "correlation": _r(corr, 3),
            "r_squared_pct": _r(corr * corr, 1, 100) if corr is not None else None,
            "idio_vol_pct": _r(math.sqrt(resid_var * TRADING_DAYS), scale=100),
            "tracking_error_pct": _r(te, scale=100),
            "info_ratio": _r(mean(diff) * TRADING_DAYS / te) if te > 1e-12 else None,
            "up_capture_pct": _r(capture(up), 1),
            "down_capture_pct": _r(capture(down), 1),
            "excess_return_pct": _r(total - (_growth(bench)[-1] - 1.0), scale=100),
        }
    )
    return out


def _money_flow_multiplier(row: Mapping) -> float:
    """Where the close sits in the day's range: +1 at the high (buyers in control), -1 at the low."""
    h, lo, c = float(row["high"] or 0), float(row["low"] or 0), float(row["close"] or 0)
    return ((c - lo) - (h - c)) / (h - lo) if h > lo else 0.0


def trading_activity(rows: Sequence[Mapping], shares: Optional[float] = None) -> dict:
    """Liquidity (latest 3 months) and buying-vs-selling pressure (whole window) from OHLCV rows.

    Exchanges don't publish who initiated each trade, so buying/selling
    pressure is estimated the two standard ways: volume on up-close days vs
    down-close days, and Chaikin Money Flow (volume weighted by where each
    close falls within its high-low range; > 0 = accumulation, < 0 = distribution).
    """
    if len(rows) < 2:
        return {}
    vols = [float(r["volume"] or 0) for r in rows]
    closes = [float(r["close"] or 0) for r in rows]
    up = sum(v for v, a, b in zip(vols[1:], closes, closes[1:]) if b > a)
    down = sum(v for v, a, b in zip(vols[1:], closes, closes[1:]) if b < a)
    mfv = [_money_flow_multiplier(r) * v for r, v in zip(rows, vols)]
    recent_v = sum(vols[-FLOW_WINDOW:])
    # Liquidity uses the latest ~3 months (the usual "average volume"): split-adjusted share
    # volumes from years ago aren't comparable, and today's liquidity is what matters for trading.
    vol_3m = vols[-63:]
    avg_v = mean(vol_3m)
    prior = vols[-51:-1]
    return {
        "avg_volume": _r(avg_v, 0),
        "avg_dollar_volume": _r(mean(v * c for v, c in zip(vol_3m, closes[-63:])), 0),
        "last_volume": _r(vols[-1], 0),
        "rel_volume": _r(vols[-1] / mean(prior), 2) if prior and mean(prior) else None,
        "volume_trend_pct": _r(mean(vols[-FLOW_WINDOW:]) / avg_v - 1.0, 1, 100) if avg_v else None,
        "up_volume_pct": _r(up / (up + down), 1, 100) if up + down else None,
        "cmf_20": _r(sum(mfv[-FLOW_WINDOW:]) / recent_v, 3) if recent_v else None,
        "cmf_window": _r(sum(mfv) / sum(vols), 3) if sum(vols) else None,
        "turnover_pct": _r(avg_v / shares, 3, 100) if shares else None,
    }


def _money_flow_series(dates: Sequence[str], rows: Sequence[Mapping]) -> list[dict]:
    """Rolling 20-day Chaikin Money Flow."""
    out, mfv_sum, vol_sum = [], 0.0, 0.0
    mfv = [_money_flow_multiplier(r) * float(r["volume"] or 0) for r in rows]
    vols = [float(r["volume"] or 0) for r in rows]
    for i, d in enumerate(dates):
        mfv_sum += mfv[i]
        vol_sum += vols[i]
        if i >= FLOW_WINDOW:
            mfv_sum -= mfv[i - FLOW_WINDOW]
            vol_sum -= vols[i - FLOW_WINDOW]
        if i >= FLOW_WINDOW - 1 and vol_sum:
            out.append({"date": d, "value": round(mfv_sum / vol_sum, 3)})
    return out


def _rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    """Wilder's Relative Strength Index on the last close (70+ overbought, 30- oversold)."""
    if len(closes) <= n:
        return None
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = mean(max(d, 0.0) for d in deltas[:n])
    loss = mean(max(-d, 0.0) for d in deltas[:n])
    for d in deltas[n:]:
        gain = (gain * (n - 1) + max(d, 0.0)) / n
        loss = (loss * (n - 1) + max(-d, 0.0)) / n
    return round(100.0 - 100.0 / (1.0 + gain / loss), 1) if loss else 100.0


def technicals(rows: Sequence[Mapping]) -> dict:
    """Trend and range read-outs as of the last row: moving-average gaps, RSI, 52-week range."""
    closes = [float(r["close"]) for r in rows if r["close"]]
    if len(closes) < 2:
        return {}
    last = closes[-1]
    year = rows[-TRADING_DAYS:]
    hi = max(float(r["high"] or r["close"]) for r in year)
    lo = min(float(r["low"] or r["close"]) for r in year)

    def gap(n: int) -> Optional[float]:
        return _r(last / mean(closes[-n:]) - 1.0, 1, 100) if len(closes) >= n else None

    return {
        "sma50_gap_pct": gap(50),
        "sma200_gap_pct": gap(200),
        "rsi14": _rsi(closes[-300:]),
        "high_52w": _r(hi),
        "low_52w": _r(lo),
        "from_high_pct": _r(last / hi - 1.0, 1, 100) if hi else None,
        "range_52w_pos_pct": _r((last - lo) / (hi - lo), 0, 100) if hi > lo else None,
    }


def _window(dates: list[str], range_: str) -> list[str]:
    """Dates of the analysis window: N return days need N+1 prices; YTD starts at last year's final close."""
    if range_ == "YTD" and dates:
        jan1 = f"{dates[-1][:4]}-01-01"
        prior = [d for d in dates if d < jan1]
        start = prior[-1] if prior else dates[0]
        return [d for d in dates if d >= start]
    n = RANGES.get(range_)
    return dates[-(n + 1):] if n else dates


def _period_returns(dates: Sequence[str], closes: Sequence[float], key_len: int) -> dict[str, float]:
    """Calendar-period returns from period-end closes; key_len 7 = months, 4 = years.
    The first period runs from the first available close, so it may be partial."""
    last: dict[str, float] = {}
    for d, c in zip(dates, closes):
        last[d[:key_len]] = c
    out: dict[str, float] = {}
    prev = closes[0] if closes else None
    for period, c in last.items():
        if prev:
            out[period] = round((c / prev - 1.0) * 100.0, 2)
        prev = c
    return out


def _monthly_returns(dates: Sequence[str], closes: Sequence[float]) -> dict[str, float]:
    return _period_returns(dates, closes, 7)


def _cagr(dates: Sequence[str], closes: Sequence[float]) -> Optional[float]:
    from datetime import date

    if len(closes) < 2 or not closes[0]:
        return None
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    return _r((closes[-1] / closes[0]) ** (1.0 / years) - 1.0, 2, 100) if years >= 1 else None


def _rolling_beta(dates: Sequence[str], rets: Sequence[float], bench: Sequence[float], window: int) -> list[dict]:
    """Beta over a trailing `window` of returns; rets[i] is the move into dates[i + 1]. O(n) via running sums."""
    out = []
    sa = sm = sam = smm = 0.0
    for i in range(len(rets)):
        a, m = rets[i], bench[i]
        sa, sm, sam, smm = sa + a, sm + m, sam + a * m, smm + m * m
        if i >= window:
            a0, m0 = rets[i - window], bench[i - window]
            sa, sm, sam, smm = sa - a0, sm - m0, sam - a0 * m0, smm - m0 * m0
        if i >= window - 1:
            var_m = smm / window - (sm / window) ** 2
            if var_m > 1e-14:
                out.append({"date": dates[i + 1], "value": round((sam / window - sa * sm / window**2) / var_m, 3)})
    return out


def _risk_contributions(
    names: list[str], weights: list[float], rets: Mapping[str, Sequence[float]]
) -> tuple[dict, Optional[float]]:
    """Each holding's share of portfolio variance (sums to 100) and the diversification ratio."""
    cov = [[_cov(rets[a], rets[b]) for b in names] for a in names]
    sigma_w = [sum(cov[i][j] * weights[j] for j in range(len(names))) for i in range(len(names))]
    port_var = sum(w * s for w, s in zip(weights, sigma_w))
    if port_var <= 0:
        return {}, None
    contrib = {n: round(w * s / port_var * 100.0, 1) for n, w, s in zip(names, weights, sigma_w)}
    weighted_vol = sum(w * math.sqrt(cov[i][i]) for i, w in enumerate(weights))
    return contrib, round(weighted_vol / math.sqrt(port_var), 2)


def _normalise_weights(names: list[str], weights: Optional[Mapping[str, float]]) -> list[float]:
    """Non-negative weights summing to 1; equal weight when none (or all zero) are given."""
    raw = [max(0.0, float((weights or {}).get(n) or 0.0)) for n in names]
    total = sum(raw)
    if not names:
        return []
    if total <= 0:
        return [1.0 / len(names)] * len(names)
    return [w / total for w in raw]


def _portfolio_fundamentals(
    names: list[str], weights: list[float], fund: Mapping[str, dict], last: Mapping[str, float]
) -> dict:
    """Weighted look-through of the holdings: valuation, yield, analyst upside and sector mix."""

    def harmonic(key: str) -> Optional[float]:
        # Portfolio P/E = price / earnings of the whole basket = 1 / sum(w / PE); skips loss-makers.
        pairs = [(w, fund.get(n, {}).get(key)) for n, w in zip(names, weights)]
        pairs = [(w, v) for w, v in pairs if v and v > 0]
        cover = sum(w for w, _ in pairs)
        return _r(cover / sum(w / v for w, v in pairs), 1) if pairs else None

    def weighted(get) -> Optional[float]:
        pairs = [(w, get(n)) for n, w in zip(names, weights)]
        pairs = [(w, v) for w, v in pairs if v is not None]
        cover = sum(w for w, _ in pairs)
        return _r(sum(w * v for w, v in pairs) / cover, 2) if cover else None

    def upside(n: str) -> Optional[float]:
        target = fund.get(n, {}).get("target_mean")
        return (target / last[n] - 1.0) * 100.0 if target and last.get(n) else None

    sectors: dict[str, float] = {}
    for n, w in zip(names, weights):
        s = fund.get(n, {}).get("sector") or "Unknown"
        sectors[s] = sectors.get(s, 0.0) + w * 100.0
    return {
        "pe_trailing": harmonic("pe_trailing"),
        "pe_forward": harmonic("pe_forward"),
        # Non-payers count as 0% yield; holdings with no fundamentals at all are left out.
        "dividend_yield_pct": weighted(lambda n: (fund[n].get("dividend_yield_pct") or 0.0) if n in fund else None),
        "analyst_upside_pct": weighted(upside),
        "beta_5y": weighted(lambda n: fund.get(n, {}).get("beta_5y")),
        "sectors": {k: round(v, 1) for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])},
    }


def market_analytics(
    tickers: Iterable[str],
    benchmark: str = "SPY",
    range_: str = "1Y",
    weights: Optional[Mapping[str, float]] = None,
    rf_pct: float = 0.0,
    db_path: Optional[str] = None,
) -> dict:
    """Multi-ticker analytics against a market benchmark, on the dates every series shares.

    Powers the watchlist (weighted buy-and-hold portfolio, risk contribution,
    look-through valuation), the multi-company compare view, the dashboard's
    market card and the markets page. Per ticker: risk/return metrics, trading
    activity (volume, liquidity, buying vs selling pressure), technicals,
    fundamentals and calendar-year returns over its full stored history.
    Pure Python; chart series are thinned for long windows.
    """
    from marketpulse.config import benchmark_name

    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    bm = benchmark.upper()
    by_date: dict[str, dict[str, Mapping]] = {}
    for t in dict.fromkeys([*tickers, bm]):
        rows = {r["trade_date"]: dict(r) for r in db.fetch_price_history(t, db_path=db_path) if (r["close"] or 0) > 0}
        if rows:
            by_date[t] = rows
    fund = db.fetch_fundamentals(list(by_date), db_path=db_path)
    have = [t for t in tickers if t in by_date]
    has_bm = bm in by_date
    keys = have + ([bm] if has_bm and bm not in have else [])
    all_dates = sorted(set.intersection(*(set(by_date[t]) for t in keys))) if keys else []
    dates = _window(all_dates, range_)
    if len(dates) < 3:
        dates = []
    px = {t: [float(by_date[t][d]["close"]) for d in dates] for t in keys} if dates else {}
    rets = {t: daily_returns(c) for t, c in px.items()}
    bm_rets = rets.get(bm) if has_bm else None

    def rebased(c: Sequence[float]) -> list[dict]:
        return _thin([{"date": d, "value": round(v / c[0] * 100.0, 2)} for d, v in zip(dates, c)])

    def drawdown(c: Sequence[float]) -> list[dict]:
        out, peak = [], -math.inf
        for d, v in zip(dates, c):
            peak = max(peak, v)
            out.append({"date": d, "value": round((v / peak - 1.0) * 100.0, 2)})
        return _thin(out)

    def history_to_end(t: str) -> list[Mapping]:
        """The ticker's own full history up to the window end (for moving averages, RSI, 52-week range)."""
        end = dates[-1] if dates else "9999"
        return [by_date[t][d] for d in sorted(by_date[t]) if d <= end]

    rows = []
    for t in tickers:
        row: dict = {"ticker": t, "has_data": t in px, "is_benchmark": t == bm, "fundamentals": fund.get(t)}
        if t in px:
            c = px[t]
            f = fund.get(t) or {}
            window_rows = [by_date[t][d] for d in dates]
            row.update(
                {
                    "last_close": round(c[-1], 2),
                    "change_1d_pct": _pct(c[-2], c[-1]),
                    "metrics": risk_metrics(rets[t], bm_rets, rf_pct),
                    "activity": trading_activity(window_rows, f.get("float_shares") or f.get("shares_outstanding")),
                    "technicals": technicals(history_to_end(t)),
                }
            )
        row["sentiment"] = sentiment_summary([dict(r) for r in db.fetch_sentiment_scores(t, db_path=db_path)])
        rows.append(row)

    held = [t for t in have if t in px]
    window = min(ROLLING_WINDOW, max(20, len(dates) // 3))
    series = {
        "performance": {t: rebased(px[t]) for t in keys if t in px},
        "drawdown": {t: drawdown(px[t]) for t in keys if t in px},
        "relative": {
            t: _thin(
                [
                    {"date": d, "value": round((v / px[t][0]) / (b / px[bm][0]) * 100.0, 2)}
                    for d, v, b in zip(dates, px[t], px[bm])
                ]
            )
            for t in held
            if bm in px and t != bm
        },
        "rolling_beta": {
            t: _thin(_rolling_beta(dates, rets[t], bm_rets, window))
            for t in held
            if bm_rets and t != bm and len(dates) > window + 5
        },
        "rolling_window": window,
        "money_flow": {t: _thin(_money_flow_series(dates, [by_date[t][d] for d in dates])) for t in held},
    }

    corr_names = [t for t in keys if t in rets]
    matrix = [[1.0 if a == b else correlation(rets[a], rets[b]) for b in corr_names] for a in corr_names]

    # Weighted buy-and-hold portfolio of the holdings (weights drift with prices after day one).
    w = _normalise_weights(held, weights)
    weight_of = dict(zip(held, w))
    portfolio: dict = {"weights": {t: round(x * 100.0, 2) for t, x in zip(held, w)}}
    monthly_rows: dict[str, dict] = {}
    if held:
        value = [sum(wi * px[t][k] / px[t][0] for wi, t in zip(w, held)) * 100.0 for k in range(len(dates))]
        contrib, div_ratio = _risk_contributions(held, w, rets)
        scored = [r for r in rows if r.get("metrics")]
        sentiments = [r["sentiment"]["net_index"] for r in rows if r["sentiment"]["net_index"] is not None]
        portfolio.update(
            {
                "series": _thin([{"date": d, "value": round(v, 2)} for d, v in zip(dates, value)]),
                "drawdown": drawdown(value),
                "metrics": risk_metrics(daily_returns(value), bm_rets, rf_pct),
                "risk_contribution_pct": contrib,
                "diversification_ratio": div_ratio,
                "fundamentals": _portfolio_fundamentals(held, w, fund, {t: px[t][-1] for t in held}),
                "best": max(scored, key=lambda r: r["metrics"]["return_pct"])["ticker"] if scored else None,
                "worst": min(scored, key=lambda r: r["metrics"]["return_pct"])["ticker"] if scored else None,
                "avg_net_sentiment": round(mean(sentiments), 3) if sentiments else None,
            }
        )
        monthly_rows["Portfolio"] = _monthly_returns(dates, value)
    for t in keys:
        if t in px:
            monthly_rows[t] = _monthly_returns(dates, px[t])
    months = sorted({m for r in monthly_rows.values() for m in r})

    # Calendar-year returns use each ticker's own full history, not the window.
    yearly_rows: dict[str, dict] = {}
    cagr: dict[str, Optional[float]] = {}
    first_date: dict[str, str] = {}
    for t in keys:
        ds = sorted(by_date[t])
        cs = [float(by_date[t][d]["close"]) for d in ds]
        yearly_rows[t] = _period_returns(ds, cs, 4)
        cagr[t] = _cagr(ds, cs)
        first_date[t] = ds[0]
    years = sorted({y for r in yearly_rows.values() for y in r})
    if held:
        # Rebalanced to the target weights every January; holdings without data that year are skipped.
        port_years = {}
        for y in years:
            pairs = [(weight_of[t], yearly_rows[t][y]) for t in held if y in yearly_rows[t]]
            cover = sum(wt for wt, _ in pairs)
            if cover:
                port_years[y] = round(sum(wt * r for wt, r in pairs) / cover, 2)
        yearly_rows = {"Portfolio": port_years, **yearly_rows}
        growth = math.prod(1.0 + r / 100.0 for r in port_years.values())
        start = min(first_date[t] for t in held)
        end = max(max(by_date[t]) for t in held)
        cagr["Portfolio"] = _cagr([start, end], [1.0, growth]) if growth > 0 else None

    return {
        "benchmark": {"symbol": bm, "name": benchmark_name(bm), "has_data": has_bm},
        "range": range_,
        "rf_pct": rf_pct,
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "n_days": max(0, len(dates) - 1),
        "missing": [t for t in tickers if t not in by_date],
        "tickers": rows,
        "benchmark_metrics": risk_metrics(bm_rets, bm_rets, rf_pct) if bm_rets else None,
        "benchmark_fundamentals": fund.get(bm),
        "benchmark_activity": trading_activity([by_date[bm][d] for d in dates]) if bm in px else None,
        "benchmark_technicals": technicals(history_to_end(bm)) if bm in px else None,
        "benchmark_last_close": round(px[bm][-1], 2) if bm in px else None,
        "series": series,
        "correlation": {"tickers": corr_names, "matrix": matrix},
        "monthly": {"months": months, "rows": {k: [v.get(m) for m in months] for k, v in monthly_rows.items()}},
        "yearly": {
            "years": years,
            "rows": {k: [v.get(y) for y in years] for k, v in yearly_rows.items()},
            "cagr_pct": cagr,
            "first_date": first_date,
        },
        "portfolio": portfolio,
    }
