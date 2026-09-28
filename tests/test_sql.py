import pytest

from marketpulse.llm.sql_guard import UnsafeSQLError, run_readonly, validate_sql
from marketpulse.llm.text_to_sql import answer_with_sql
from tests.fakes import FakeClient, seed_db


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "sql.db")
    seed_db(path)
    return path


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM filings",
        "select 1; drop table filings",
        "UPDATE price_history SET close = 0",
        "PRAGMA table_info(filings)",
        "ATTACH DATABASE 'x.db' AS x",
        "",
    ],
)
def test_validate_rejects_writes_and_multi_statements(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validate_allows_keywords_inside_strings():
    assert validate_sql("SELECT * FROM filings WHERE title LIKE '%drop%';") == (
        "SELECT * FROM filings WHERE title LIKE '%drop%'"
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM llm_usage",
        "SELECT name FROM sqlite_master",
        "SELECT * FROM (SELECT * FROM llm_usage)",
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT x FROM c",
    ],
)
def test_authorizer_blocks_internal_tables_and_recursion(db_path, sql):
    with pytest.raises(UnsafeSQLError):
        run_readonly(sql, db_path=db_path)


def test_run_readonly_returns_rows_and_truncates(db_path):
    r = run_readonly("SELECT ticker, trade_date, close FROM price_history ORDER BY 1, 2", max_rows=5, db_path=db_path)
    assert r["columns"] == ["ticker", "trade_date", "close"]
    assert r["row_count"] == 5 and r["truncated"] is True


def test_text_to_sql_happy_path(db_path):
    client = FakeClient(
        {
            "sql": "SELECT ticker, AVG(close) AS avg_close FROM price_history GROUP BY ticker",
            "explanation": "Average close per ticker.",
            "chart": {"type": "bar", "x": "ticker", "y": ["avg_close", "not_a_column"], "series": None},
        }
    )
    r = answer_with_sql("average close by ticker", client=client, db_path=db_path)
    assert r["attempts"] == 1
    assert {row[0] for row in r["rows"]} == {"AAPL", "MSFT"}
    assert r["chart"] == {"type": "bar", "x": "ticker", "y": ["avg_close"], "series": None}
    assert "llm_usage" not in client.calls[0]["system"]  # internal tables are never shown to the model


def test_text_to_sql_self_repairs_once(db_path):
    client = FakeClient(
        {"sql": "SELECT closing_price FROM price_history", "explanation": "x", "chart": None},
        {"sql": "SELECT close FROM price_history LIMIT 3", "explanation": "fixed", "chart": None},
    )
    r = answer_with_sql("closes", client=client, db_path=db_path)
    assert r["attempts"] == 2 and r["row_count"] == 3
    assert "no such column" in client.calls[1]["messages"][0]["content"]
    assert r["chart"]["type"] == "none"


def test_text_to_sql_does_not_retry_unsafe(db_path):
    client = FakeClient({"sql": "DELETE FROM filings", "explanation": "", "chart": None})
    with pytest.raises(UnsafeSQLError):
        answer_with_sql("delete everything", client=client, db_path=db_path)
    assert len(client.calls) == 1
