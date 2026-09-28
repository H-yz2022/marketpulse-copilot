"""Safely execute LLM-generated SQL.

Defense in depth - an LLM's SQL is untrusted input, so four independent layers
each have to agree before a query returns data:

1. **Static check** - exactly one statement, starting with SELECT/WITH, and no
   write/DDL/PRAGMA/ATTACH keywords (string literals are stripped first so a
   filter like `title LIKE '%drop%'` isn't a false positive).
2. **Read-only connection** - SQLite opened with `mode=ro`, so the engine
   itself refuses writes.
3. **Authorizer callback** - SQLite asks us about every table/column the
   compiled statement touches; only the public tables are readable (so
   internal tables like `llm_usage` and `sqlite_master` are off-limits even
   via a sub-query), and recursive CTEs are denied.
4. **Resource limits** - a wall-clock timeout via the progress handler and a
   hard row cap.
"""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Optional

from marketpulse.db import PUBLIC_TABLES, get_readonly_connection


class UnsafeSQLError(ValueError):
    """The SQL was rejected before or during execution for safety reasons."""


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|analyze|"
    r"begin|commit|rollback|savepoint|release|load_extension)\b",
    re.IGNORECASE,
)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def normalize_sql(sql: str) -> str:
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    sql = sql.strip().rstrip(";").strip()
    return sql


def validate_sql(sql: str) -> str:
    """Static checks. Returns the normalized SQL or raises UnsafeSQLError."""
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty query")
    cleaned = normalize_sql(sql)
    no_strings = _STRING_LITERAL.sub("''", cleaned)
    if ";" in no_strings:
        raise UnsafeSQLError("Only a single statement is allowed")
    first = no_strings.lstrip("( \n\t").split(None, 1)[0].lower() if no_strings.strip() else ""
    if first not in {"select", "with"}:
        raise UnsafeSQLError("Only SELECT queries are allowed")
    bad = _FORBIDDEN.search(no_strings)
    if bad:
        raise UnsafeSQLError(f"Keyword not allowed: {bad.group(1).upper()}")
    return cleaned


def _authorizer(action: int, arg1: Optional[str], arg2: Optional[str], db_name: Optional[str], trigger: Optional[str]):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        # arg1 is the table name. CTE/sub-query aliases resolve to real tables.
        return sqlite3.SQLITE_OK if (arg1 or "").lower() in PUBLIC_TABLES else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or "").lower() == "load_extension" else sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY  # everything else, incl. SQLITE_RECURSIVE, PRAGMA, ATTACH, writes


def run_readonly(sql: str, max_rows: int = 500, timeout_s: float = 3.0, db_path: Optional[str] = None) -> dict:
    """Validate and execute a query. Returns columns, rows (as lists) and a truncation flag."""
    cleaned = validate_sql(sql)
    conn = get_readonly_connection(db_path)
    deadline = time.monotonic() + timeout_s
    try:
        conn.set_authorizer(_authorizer)
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            cur = conn.execute(cleaned)
            rows = cur.fetchmany(max_rows + 1)
        except sqlite3.DatabaseError as exc:
            msg = str(exc)
            if "not authorized" in msg or "prohibited" in msg:
                raise UnsafeSQLError("Query touches a table or operation that isn't allowed") from exc
            if "interrupted" in msg:
                raise UnsafeSQLError(f"Query exceeded the {timeout_s:.0f}s time limit") from exc
            raise
        columns = [d[0] for d in (cur.description or [])]
        truncated = len(rows) > max_rows
        return {
            "sql": cleaned,
            "columns": columns,
            "rows": [list(r) for r in rows[:max_rows]],
            "row_count": min(len(rows), max_rows),
            "truncated": truncated,
        }
    finally:
        conn.close()
