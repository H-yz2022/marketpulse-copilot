"""Company fundamentals, ownership, short interest, analyst targets and insider trades via yfinance.

Everything is flattened into one JSON-serialisable dict per ticker with
consistent units: percentages are in percent (16.4 = 16.4%), money in the
quote currency, ratios as plain numbers. Missing fields are None - Yahoo's
coverage varies by company and is different for ETFs (which get fund fields
such as assets and expense ratio instead of earnings and margins).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from marketpulse.db import upsert_fundamentals

# our key -> (Yahoo `info` key, multiplier). Yahoo returns most ratios as
# fractions (0.164); dividendYield, debtToEquity and netExpenseRatio already in percent.
_FIELDS: dict[str, tuple[str, float]] = {
    "market_cap": ("marketCap", 1),
    "enterprise_to_ebitda": ("enterpriseToEbitda", 1),
    "pe_trailing": ("trailingPE", 1),
    "pe_forward": ("forwardPE", 1),
    "peg": ("trailingPegRatio", 1),
    "price_to_book": ("priceToBook", 1),
    "price_to_sales": ("priceToSalesTrailing12Months", 1),
    "eps_trailing": ("trailingEps", 1),
    "eps_forward": ("forwardEps", 1),
    "dividend_yield_pct": ("dividendYield", 1),
    "payout_ratio_pct": ("payoutRatio", 100),
    "revenue": ("totalRevenue", 1),
    "revenue_growth_pct": ("revenueGrowth", 100),
    "earnings_growth_pct": ("earningsGrowth", 100),
    "gross_margin_pct": ("grossMargins", 100),
    "operating_margin_pct": ("operatingMargins", 100),
    "profit_margin_pct": ("profitMargins", 100),
    "roe_pct": ("returnOnEquity", 100),
    "roa_pct": ("returnOnAssets", 100),
    "debt_to_equity": ("debtToEquity", 0.01),
    "current_ratio": ("currentRatio", 1),
    "free_cash_flow": ("freeCashflow", 1),
    "shares_outstanding": ("sharesOutstanding", 1),
    "float_shares": ("floatShares", 1),
    "shares_short": ("sharesShort", 1),
    "shares_short_prior_month": ("sharesShortPriorMonth", 1),
    "short_pct_float": ("shortPercentOfFloat", 100),
    "short_ratio_days": ("shortRatio", 1),
    "insider_pct": ("heldPercentInsiders", 100),
    "institution_pct": ("heldPercentInstitutions", 100),
    "target_mean": ("targetMeanPrice", 1),
    "target_high": ("targetHighPrice", 1),
    "target_low": ("targetLowPrice", 1),
    "recommendation_mean": ("recommendationMean", 1),
    "analyst_count": ("numberOfAnalystOpinions", 1),
    "beta_5y": ("beta", 1),
    "avg_volume_3m": ("averageVolume", 1),
    "avg_volume_10d": ("averageVolume10days", 1),
    "employees": ("fullTimeEmployees", 1),
    # ETFs
    "total_assets": ("totalAssets", 1),
    "expense_ratio_pct": ("netExpenseRatio", 1),
}
_TEXT = {
    "name": "longName",
    "quote_type": "quoteType",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "currency": "currency",
    "recommendation": "recommendationKey",
    "category": "category",
    "fund_family": "fundFamily",
}


def _num(v: Any, scale: float = 1) -> Optional[float]:
    try:
        f = float(v) * scale
    except (TypeError, ValueError):
        return None
    return round(f, 4) if math.isfinite(f) else None


def parse_info(info: dict) -> dict:
    """Map Yahoo's `info` dict onto our flat, unit-consistent fields."""
    out: dict[str, Any] = {k: (str(info[src]) if info.get(src) not in (None, "") else None) for k, src in _TEXT.items()}
    for k, (src, scale) in _FIELDS.items():
        out[k] = _num(info.get(src), scale)
    if out["sector"] is None and out["quote_type"] == "ETF":
        out["sector"] = "Fund"
    return out


def _kind(text: str) -> str:
    t = (text or "").strip().lower()
    if t.startswith("purchase"):
        return "buy"
    if t.startswith("sale"):
        return "sell"
    return "other"  # awards, gifts, option exercises: not open-market trades


def summarize_insiders(rows: list[dict], today: Optional[date] = None, days: int = 365, recent: int = 8) -> dict:
    """Open-market insider buying vs selling (Form 4 filings) over the last `days`.

    `rows` are dicts with Start Date, Text, Shares, Value, Insider, Position.
    """
    today = today or datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=days)
    out = {"window_days": days, "buy_value": 0.0, "sell_value": 0.0, "buy_shares": 0.0, "sell_shares": 0.0,
           "buy_count": 0, "sell_count": 0, "recent": []}
    for r in rows:
        d = r.get("Start Date")
        d = d.date() if hasattr(d, "date") else (date.fromisoformat(str(d)[:10]) if d else None)
        if d is None:
            continue
        kind = _kind(str(r.get("Text") or ""))
        value = _num(r.get("Value")) or 0.0
        shares = _num(r.get("Shares")) or 0.0
        if d >= cutoff and kind != "other":
            out[f"{kind}_value"] += value
            out[f"{kind}_shares"] += shares
            out[f"{kind}_count"] += 1
        if len(out["recent"]) < recent:
            out["recent"].append(
                {
                    "date": d.isoformat(),
                    "insider": str(r.get("Insider") or "").title(),
                    "position": str(r.get("Position") or ""),
                    "type": kind,
                    "text": str(r.get("Text") or "")[:80],
                    "shares": shares,
                    "value": value,
                }
            )
    out["net_value"] = out["buy_value"] - out["sell_value"]
    return out


def fetch_fundamentals(ticker: str) -> dict:
    """Fetch and normalise one ticker's fundamentals (+ insider summary for companies)."""
    import yfinance as yf

    tk = yf.Ticker(ticker)
    data = parse_info(tk.info or {})
    data["insider"] = None
    if data.get("quote_type") != "ETF":
        try:
            df = tk.insider_transactions
            if df is not None and len(df):
                data["insider"] = summarize_insiders(df.to_dict("records"))
        except Exception:  # noqa: BLE001 - insider data is optional
            pass
    return data


def ingest_fundamentals(ticker: str, db_path: Optional[str] = None) -> bool:
    data = fetch_fundamentals(ticker)
    if not any(v is not None for k, v in data.items() if k not in ("insider",)):
        return False
    upsert_fundamentals(ticker, datetime.now(timezone.utc).date().isoformat(), data, db_path=db_path)
    return True
