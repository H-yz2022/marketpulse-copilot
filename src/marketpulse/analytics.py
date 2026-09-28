"""Pure-Python market analytics: returns, risk, sentiment aggregation, correlation.

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


def price_summary(rows: Sequence[Mapping]) -> dict:
    """KPI tiles for one ticker's price history."""
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
    price_rows = {t: [dict(r) for r in db.fetch_price_history(t, db_path=db_path)] for t in tickers}
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
