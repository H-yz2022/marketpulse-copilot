"""HTTP-level tests for the FastAPI app, with a fake LLM and retriever injected."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from marketpulse import db  # noqa: E402
from marketpulse.api import main  # noqa: E402
from marketpulse.config import settings  # noqa: E402
from tests.fakes import FakeClient, fake_retrieve, message, seed_db, text_block, tool_block  # noqa: E402


@pytest.fixture()
def client():
    seed_db(settings.db_path)
    with db.connect() as conn:
        conn.execute("DELETE FROM llm_usage")
    main.app.state.retrieve_fn = fake_retrieve
    main.app.state.llm_client = None
    with TestClient(main.app) as c:
        yield c
    main.app.state.llm_client = None


def test_health_and_tickers(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["ai_enabled"] is False
    assert {"AAPL", "MSFT"} <= set(client.get("/api/tickers").json()["all"])


def test_overview(client):
    r = client.get("/api/tickers/aapl/overview")
    assert r.status_code == 200
    assert r.json()["summary"]["has_data"] is True


def test_invalid_ticker_rejected(client):
    assert client.get("/api/tickers/bad!sym/overview").status_code == 400


def test_watchlist(client):
    r = client.get("/api/watchlist", params={"tickers": "AAPL,MSFT,AAPL"})
    assert r.status_code == 200
    assert [t["ticker"] for t in r.json()["tickers"]] == ["AAPL", "MSFT"]


def test_ai_endpoints_503_without_key(client):
    r = client.post("/api/sql", json={"question": "average close"})
    assert r.status_code == 503
    with db.connect() as conn:  # a disabled feature must not burn quota
        assert conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 0


def test_sql_endpoint(client):
    main.app.state.llm_client = FakeClient(
        {"sql": "SELECT ticker, COUNT(*) AS n FROM price_history GROUP BY ticker", "explanation": "e",
         "chart": {"type": "bar", "x": "ticker", "y": ["n"]}}
    )
    r = client.post("/api/sql", json={"question": "rows per ticker"})
    assert r.status_code == 200, r.text
    assert r.json()["chart"]["type"] == "bar"


def test_sql_endpoint_blocks_unsafe(client):
    main.app.state.llm_client = FakeClient({"sql": "DROP TABLE filings", "explanation": "", "chart": None})
    r = client.post("/api/sql", json={"question": "drop it"})
    assert r.status_code == 422


def test_agent_streams_sse(client):
    main.app.state.llm_client = FakeClient(
        message(tool_block("t1", "get_price_summary", {"ticker": "AAPL"}), stop_reason="tool_use"),
        message(text_block("Final answer")),
    )
    with client.stream("POST", "/api/agent", json={"question": "How is AAPL?"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events] == ["route", "status", "tool_call", "tool_result", "verify", "final"]
    assert events[0]["route"] == "direct"


def test_ask_uses_rewrite_and_hybrid_retrieval(client):
    main.app.state.llm_client = FakeClient({"query": "AAPL supply chain risk", "keywords": ["supplier"]}, "Answer [1]")
    r = client.post("/api/ask", json={"question": "what could break apple's supply chain?", "ticker": "AAPL"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rewrite"]["query"] == "AAPL supply chain risk"
    assert body["answer"] == "Answer [1]" and body["sources"][0]["n"] == 1


def test_brief_and_compare(client):
    main.app.state.llm_client = FakeClient({"headline": "H"}, {"overview": "O"})
    assert client.post("/api/brief", json={"ticker": "AAPL"}).json()["brief"]["headline"] == "H"
    r = client.post("/api/compare", json={"a": "AAPL", "b": "MSFT"})
    assert r.json()["comparison"]["overview"] == "O"
    assert client.post("/api/compare", json={"a": "AAPL", "b": "aapl"}).status_code == 400


def test_rate_limit_per_client(client, monkeypatch):
    import dataclasses

    from marketpulse.api import ratelimit

    monkeypatch.setattr(ratelimit, "settings", dataclasses.replace(settings, max_llm_calls_per_client_per_day=2))
    main.app.state.llm_client = FakeClient({"headline": "1"}, {"headline": "2"}, {"headline": "3"})
    codes = [client.post("/api/brief", json={"ticker": "AAPL"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_tickers_lists_benchmarks_separately(client):
    body = client.get("/api/tickers").json()
    symbols = [b["symbol"] for b in body["benchmarks"]]
    assert "SPY" in symbols and body["default_benchmark"] == "SPY"
    assert not set(symbols) & set(body["all"])  # benchmarks are references, not company dashboards


def test_analytics_endpoint(client):
    r = client.get("/api/analytics", params={"tickers": "AAPL,MSFT", "benchmark": "spy", "range": "1Y",
                                             "weights": "1,1", "rf": 4})
    assert r.status_code == 200
    body = r.json()
    assert body["benchmark"]["symbol"] == "SPY" and body["rf_pct"] == 4
    assert body["portfolio"]["weights"] == {"AAPL": 50.0, "MSFT": 50.0}
    assert client.get("/api/analytics", params={"tickers": "AAPL,MSFT", "weights": "1"}).status_code == 400
    assert client.get("/api/analytics", params={"tickers": "AAPL", "range": "2Y"}).status_code == 422


def test_refresh_benchmark_is_prices_only(client, monkeypatch):
    import marketpulse.pipeline as pipeline

    called = []
    monkeypatch.setattr(pipeline, "refresh_prices", lambda t: called.append(t) or {"ticker": t, "prices": 5})
    monkeypatch.setattr(pipeline, "refresh_ticker", lambda t: pytest.fail("benchmarks have no filings to fetch"))
    main._last_refresh.pop("QQQ", None)
    assert client.post("/api/tickers/QQQ/refresh").json()["prices"] == 5 and called == ["QQQ"]
