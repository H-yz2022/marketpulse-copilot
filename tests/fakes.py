"""Offline stand-ins for the Anthropic client, so no test needs a key or network."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_block(id: str, name: str, input: dict) -> SimpleNamespace:  # noqa: A002 - mirror the SDK field names
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def message(*blocks: Any, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


class FakeClient:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *responses: Any):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(copy.deepcopy(kwargs))  # snapshot: callers mutate `messages` later
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        r = self._responses.pop(0)
        if isinstance(r, dict):
            return message(text_block(json.dumps(r)))
        if isinstance(r, str):
            return message(text_block(r))
        return r


def seed_db(db_path: str) -> None:
    """Two tickers of deterministic prices, sentiment and filings."""
    from marketpulse import db

    for t, base, step in (("AAPL", 100.0, 1.0), ("MSFT", 200.0, -0.5)):
        rows = []
        for i in range(30):
            close = base + step * i + (1.5 if i % 3 == 0 else 0)
            rows.append(
                {"ticker": t, "trade_date": f"2026-03-{i + 1:02d}", "open": close, "high": close + 1,
                 "low": close - 1, "close": close, "volume": 1000 + i}
            )
        db.upsert_price_history(rows, db_path=db_path)
        db.upsert_filing(
            {"filing_id": f"{t}-1", "ticker": t, "form_type": "10-K", "filed_date": "2025-11-01",
             "title": f"{t} 10-K", "url": f"https://sec.example/{t}", "excerpt": "Risk factors text"},
            db_path=db_path,
        )
        for label, score in (("negative", 0.8), ("positive", 0.6), ("neutral", 0.5)):
            db.insert_sentiment_score(
                {"ticker": t, "source_type": "filing", "source_id": f"{t}-1", "scored_date": "2026-03-30",
                 "label": label, "score": score, "text_snippet": "..."},
                db_path=db_path,
            )


def fake_retrieve(query: str, n_results: int = 4, where: dict | None = None) -> list[dict]:
    ticker = (where or {}).get("ticker", "AAPL")
    return [
        {"text": f"{ticker} risk excerpt {i} about {query}",
         "metadata": {"ticker": ticker, "form_type": "10-K", "filed_date": "2025-11-01", "url": "https://x"},
         "distance": 0.1 * i}
        for i in range(1, min(n_results, 3) + 1)
    ]
