"""Daily caps on billed LLM calls - checked *before* the Anthropic API is called.

Two layers, both persisted in SQLite so they survive restarts:
  * per client (keyed by IP) - stops one visitor burning the budget
  * global - a hard ceiling on total daily spend for a public demo
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

from marketpulse import db
from marketpulse.config import settings

_lock = threading.Lock()


class RateLimitExceeded(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def check_and_record(client_id: str, feature: str, db_path: Optional[str] = None) -> dict:
    """Raise RateLimitExceeded if either cap is hit; otherwise count this call."""
    today = _today()
    with _lock:  # make check+insert atomic across request threads
        used_client = db.count_llm_usage(today, client_id=client_id, db_path=db_path)
        used_total = db.count_llm_usage(today, db_path=db_path)
        if used_total >= settings.max_llm_calls_per_day:
            raise RateLimitExceeded(
                "This public demo has reached its daily AI budget. It resets at 00:00 UTC - "
                "or clone the repo and run it with your own API key."
            )
        if used_client >= settings.max_llm_calls_per_client_per_day:
            raise RateLimitExceeded(
                f"You've used all {settings.max_llm_calls_per_client_per_day} AI requests for today. "
                "Limits reset at 00:00 UTC."
            )
        db.record_llm_usage(client_id, feature, today, db_path=db_path)
    return usage(client_id, db_path=db_path)


def usage(client_id: str, db_path: Optional[str] = None) -> dict:
    today = _today()
    return {
        "client_used": db.count_llm_usage(today, client_id=client_id, db_path=db_path),
        "client_limit": settings.max_llm_calls_per_client_per_day,
        "global_used": db.count_llm_usage(today, db_path=db_path),
        "global_limit": settings.max_llm_calls_per_day,
    }
