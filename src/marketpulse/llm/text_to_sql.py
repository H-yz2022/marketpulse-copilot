"""Natural-language questions -> safe, read-only SQL -> table + chart spec.

Flow:
  1. Claude sees the public schema (never the internal tables) and returns
     JSON: the SQL, a one-line explanation and a suggested chart.
  2. The SQL runs through `sql_guard.run_readonly` (4 layers of protection).
  3. If SQLite rejects it with an ordinary error (bad column name, etc.) the
     error is fed back to Claude for **one** self-repair attempt. Safety
     rejections are *not* retried - those are final.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

from marketpulse.db import PUBLIC_SCHEMA_DOC
from marketpulse.llm.client import complete_json
from marketpulse.llm.sql_guard import UnsafeSQLError, run_readonly

SYSTEM = f"""You translate an analyst's question into ONE SQLite SELECT query.

Database schema:
{PUBLIC_SCHEMA_DOC}

Rules:
- SQLite dialect. Read-only: a single SELECT (CTEs with WITH are fine). No PRAGMA.
- Dates are TEXT 'YYYY-MM-DD'; use date('now', '-30 day') style arithmetic.
- Tickers are upper-case strings like 'AAPL'.
- Prefer returning at most 200 rows; aggregate when the question is about trends.
- Name computed columns clearly (e.g. avg_close, pct_change).

Return JSON with keys:
  "sql": the query,
  "explanation": one plain-English sentence describing what the query computes,
  "chart": {{"type": "line" | "bar" | "none", "x": column name or null, "y": [column names], "series": column name
  that splits lines/bars by group (e.g. ticker) or null}}"""


def _ask(question: str, client: Any, repair_note: str = "") -> dict:
    prompt = f"Question: {question}"
    if repair_note:
        prompt += f"\n\n{repair_note}"
    return complete_json(SYSTEM, prompt, max_tokens=800, client=client)


def _clean_chart(chart: Any, columns: list[str]) -> dict:
    if not isinstance(chart, dict) or chart.get("type") not in {"line", "bar"}:
        return {"type": "none", "x": None, "y": [], "series": None}
    x = chart.get("x") if chart.get("x") in columns else None
    ys = [y for y in (chart.get("y") or []) if y in columns and y != x]
    series = chart.get("series") if chart.get("series") in columns else None
    if not x or not ys:
        return {"type": "none", "x": None, "y": [], "series": None}
    return {"type": chart["type"], "x": x, "y": ys, "series": series}


def answer_with_sql(question: str, client: Optional[Any] = None, db_path: Optional[str] = None) -> dict:
    plan = _ask(question, client)
    attempts = 1
    try:
        result = run_readonly(str(plan.get("sql", "")), db_path=db_path)
    except UnsafeSQLError:
        raise
    except sqlite3.Error as exc:
        attempts += 1
        plan = _ask(
            question,
            client,
            repair_note=f"Your previous query:\n{plan.get('sql')}\nfailed with SQLite error: {exc}\nFix it.",
        )
        result = run_readonly(str(plan.get("sql", "")), db_path=db_path)

    return {
        "question": question,
        "explanation": str(plan.get("explanation", "")),
        "chart": _clean_chart(plan.get("chart"), result["columns"]),
        "attempts": attempts,
        **result,
    }
