"""Structured AI research artifacts: a one-page brief per ticker, and a two-company comparison.

Both follow the same pattern - assemble grounded evidence ourselves (KPIs from
SQL, risk-factor excerpts from the vector store), then ask Claude for strict
JSON so the frontend can render real UI components instead of a text blob.
Every excerpt is numbered so claims can cite [1], [2] ... back to a filing.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from marketpulse import analytics, db
from marketpulse.llm.client import complete_json

BRIEF_SYSTEM = """You are a sell-side equity research associate writing a concise, balanced one-page brief.
Ground every statement in the provided KPIs and numbered filing excerpts; cite excerpts as [n].
Do not invent figures. This is research support, not investment advice.

JSON keys:
  "headline": one sentence,
  "summary": 2-3 sentences,
  "bull_points": [3 short strings],
  "bear_points": [3 short strings],
  "key_risks": [{"risk": short title, "detail": one sentence with [n] citations, "severity": "high"|"medium"|"low"}]
               (3-5 items),
  "sentiment_read": one sentence interpreting the sentiment data,
  "watch_items": [2-3 things an analyst should monitor next]"""

COMPARE_SYSTEM = """You are an equity research associate comparing two companies' disclosed risk profiles
and recent market behaviour. Ground every statement in the provided data; cite excerpts as [n].
Do not invent figures. This is research support, not investment advice.

JSON keys:
  "overview": 2-3 sentences,
  "shared_risks": [{"risk": title, "detail": one sentence with citations}] (2-4 items),
  "unique_to_a": [{"risk": title, "detail": ...}] (2-3 items),
  "unique_to_b": [{"risk": title, "detail": ...}] (2-3 items),
  "market_comparison": 2 sentences comparing return, volatility and drawdown using the KPIs,
  "takeaway": one sentence"""

RISK_QUERY = "most significant business, regulatory, competitive and financial risk factors"


def _default_retrieve(query: str, n_results: int, where: Optional[dict]) -> list[dict]:
    from marketpulse.rag.pipeline import retrieve

    return retrieve(query, n_results=n_results, where=where)


def _evidence(ticker: str, retrieve_fn: Callable, start: int, k: int) -> tuple[list[dict], str]:
    hits = retrieve_fn(RISK_QUERY, n_results=k, where={"ticker": ticker})
    sources, lines = [], []
    for i, h in enumerate(hits, start=start):
        m = h.get("metadata") or {}
        sources.append(
            {
                "n": i,
                "ticker": ticker,
                "form_type": m.get("form_type"),
                "filed_date": m.get("filed_date"),
                "url": m.get("url"),
                "text": h["text"][:600],
            }
        )
        lines.append(f"[{i}] ({ticker} {m.get('form_type', '')} {m.get('filed_date', '')})\n{h['text']}")
    return sources, "\n\n".join(lines)


def _kpis(ticker: str, db_path: Optional[str]) -> dict:
    return {
        "price": analytics.price_summary([dict(r) for r in db.fetch_price_history(ticker, db_path=db_path)]),
        "sentiment": analytics.sentiment_summary([dict(r) for r in db.fetch_sentiment_scores(ticker, db_path=db_path)]),
    }


def research_brief(
    ticker: str,
    client: Optional[Any] = None,
    retrieve_fn: Optional[Callable] = None,
    db_path: Optional[str] = None,
) -> dict:
    t = ticker.upper()
    kpis = _kpis(t, db_path)
    sources, excerpts = _evidence(t, retrieve_fn or _default_retrieve, start=1, k=6)
    if not kpis["price"].get("has_data") and not sources:
        raise db.DataNotFoundError(f"No stored data for {t}. Refresh it first.")
    prompt = (
        f"Company ticker: {t}\n\nKPIs (JSON):\n{json.dumps(kpis)}\n\n"
        f"Filing excerpts:\n{excerpts or '(none indexed)'}\n\nWrite the brief."
    )
    brief = complete_json(BRIEF_SYSTEM, prompt, max_tokens=1600, client=client)
    return {"ticker": t, "kpis": kpis, "brief": brief, "sources": sources}


def compare_companies(
    ticker_a: str,
    ticker_b: str,
    client: Optional[Any] = None,
    retrieve_fn: Optional[Callable] = None,
    db_path: Optional[str] = None,
) -> dict:
    a, b = ticker_a.upper(), ticker_b.upper()
    if a == b:
        raise ValueError("Pick two different tickers")
    fn = retrieve_fn or _default_retrieve
    src_a, ex_a = _evidence(a, fn, start=1, k=4)
    src_b, ex_b = _evidence(b, fn, start=len(src_a) + 1, k=4)
    kpis = {a: _kpis(a, db_path), b: _kpis(b, db_path)}
    prompt = (
        f"Company A: {a}\nCompany B: {b}\n\nKPIs (JSON):\n{json.dumps(kpis)}\n\n"
        f"Company A filing excerpts:\n{ex_a or '(none indexed)'}\n\n"
        f"Company B filing excerpts:\n{ex_b or '(none indexed)'}\n\nWrite the comparison."
    )
    comparison = complete_json(COMPARE_SYSTEM, prompt, max_tokens=1600, client=client)
    performance = analytics.watchlist([a, b], db_path=db_path)["performance"]
    return {
        "a": a,
        "b": b,
        "kpis": kpis,
        "comparison": comparison,
        "sources": src_a + src_b,
        "performance": performance,
    }
