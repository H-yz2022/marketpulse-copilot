"""Router, planner, parallel executors, verifier, loop guard, tool timeouts and hybrid retrieval."""
import threading
import time

import pytest

from marketpulse import db
from marketpulse.llm import orchestrator as orch
from marketpulse.llm.agent import Toolbox, ToolError, run_agent
from marketpulse.rag import hybrid
from tests.fakes import FakeClient, fake_retrieve, message, seed_db, text_block, tool_block

KNOWN = ["AAPL", "MSFT", "JPM", "NVDA"]


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "ma.db")
    seed_db(path)
    return path


# ------------------------------------------------------------------ router
def test_router_rules_direct_without_llm():
    r = orch.route("What is AAPL's volatility?", KNOWN, client=FakeClient())  # no scripted replies needed
    assert r == {"route": "direct", "method": "rules", "reason": "single company, single intent", "tickers": ["AAPL"]}


def test_router_rules_plan_for_multi_company_compare():
    r = orch.route("Compare AAPL vs MSFT drawdowns and also summarise NVDA supply-chain risks", KNOWN, FakeClient())
    assert r["route"] == "plan" and r["method"] == "rules"


def test_router_falls_back_to_llm_when_ambiguous():
    client = FakeClient({"route": "plan", "reason": "two asks"})
    r = orch.route("How do AAPL risks compare with its price action?", KNOWN, client=client)
    assert r["method"] == "llm" and r["route"] == "plan"
    assert len(client.calls) == 1


# ------------------------------------------------------------------ planner
def test_plan_validation_drops_bad_agents_forward_deps_and_caps_tasks():
    raw = {
        "tasks": [
            {"id": "t1", "agent": "market", "goal": "a", "depends_on": ["t2"]},  # forward edge -> dropped
            {"id": "t2", "agent": "wizard", "goal": "b", "depends_on": ["t1"]},  # unknown agent -> filings
            {"id": "t3", "agent": "sql", "goal": "c"},
            {"id": "t4", "agent": "sql", "goal": "d"},
            {"id": "t5", "agent": "sql", "goal": "e"},
        ]
    }
    tasks = orch._validate_plan(raw)
    assert len(tasks) == orch.MAX_TASKS
    assert tasks[0]["depends_on"] == [] and tasks[1] == {"id": "t2", "agent": "filings", "goal": "b",
                                                         "depends_on": ["t1"]}
    assert [[t["id"] for t in w] for w in orch._waves(tasks)] == [["t1", "t3", "t4"], ["t2"]]


# ------------------------------------------------------------------ verifier
def test_verifier_flags_unknown_citations_and_made_up_numbers():
    sources = [{"id": "F1"}]
    obs = ['{"last_close": 187.42, "return_period_pct": 12.5}']
    ok = orch.verify("AAPL closed at 187.42, up 12.5% [F1].", sources, obs)
    assert ok["passed"] is True
    bad = orch.verify("AAPL is up 40.2% [F1][F9], across 3 risks in 2025.", sources, obs)
    assert bad["passed"] is False
    assert bad["unknown_citations"] == ["F9"] and bad["unverified_numbers"] == ["40.2%"]


# ------------------------------------------------------------------ agent guardrails
def test_loop_guard_skips_identical_calls_and_ends_run(db_path):
    same = message(tool_block("x", "get_price_summary", {"ticker": "AAPL"}), stop_reason="tool_use")
    client = FakeClient(same, same, same, same, same, message(text_block("answer")))
    events = list(run_agent("q", client=client, toolbox=Toolbox(db_path=db_path, retrieve_fn=fake_retrieve),
                            max_steps=6, db_path=db_path))
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["is_error"] is False
    assert all("loop guard" in r["summary"] for r in results[1:])
    assert any(e["type"] == "status" and "Loop detected" in e["message"] for e in events)
    assert events[-1]["type"] == "final" and events[-1]["steps"] < 6


def test_tool_timeout_is_retried_once_then_reported(db_path):
    calls = []

    def slow_retrieve(*a, **k):
        calls.append(1)
        time.sleep(0.3)
        return []

    tb = Toolbox(db_path=db_path, retrieve_fn=slow_retrieve, timeout_s=0.05)
    with pytest.raises(ToolError, match="timed out"):
        tb.run("search_filings", {"query": "x"})
    time.sleep(0.4)
    assert len(calls) == 2


def test_executor_tool_restriction(db_path):
    client = FakeClient(
        message(tool_block("a", "run_sql", {"sql": "SELECT 1"}), stop_reason="tool_use"),
        message(text_block("ok")),
    )
    events = list(run_agent("q", client=client, toolbox=Toolbox(db_path=db_path, retrieve_fn=fake_retrieve),
                            allowed_tools={"search_filings"}, task_id="t1", db_path=db_path))
    res = [e for e in events if e["type"] == "tool_result"][0]
    assert res["is_error"] and "not available" in res["summary"] and res["task_id"] == "t1"
    assert [t["name"] for t in client.calls[0]["tools"]] == ["search_filings"]


# ------------------------------------------------------------------ full orchestration
class RoutingFakeClient:
    """Answers by *role* (inferred from the system prompt), so parallel executors
    can call it in any order. Thread-safe."""

    def __init__(self):
        self.messages = self
        self.lock = threading.Lock()
        self.calls = []

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
        system = kw.get("system", "")
        if "Planner" in system:
            return message(text_block(
                '{"tasks": [{"id": "t1", "agent": "market", "goal": "AAPL vs MSFT returns"},'
                ' {"id": "t2", "agent": "filings", "goal": "AAPL risks"}]}'))
        if "Synthesizer" in system:
            return message(text_block("AAPL beat MSFT; key risk is supply chain [F1]."))
        has_tool_result = any(isinstance(m["content"], list) for m in kw["messages"])
        if has_tool_result:
            return message(text_block("- finding [F1]"))
        if "Market Data" in system:
            return message(tool_block("m1", "compare_tickers", {"tickers": ["AAPL", "MSFT"]}), stop_reason="tool_use")
        return message(tool_block("f1", "search_filings", {"query": "supply chain", "ticker": "AAPL"}),
                       stop_reason="tool_use")


def test_orchestrated_plan_runs_executors_in_parallel_and_verifies(db_path):
    client = RoutingFakeClient()
    events = list(orch.run_orchestrated("Compare AAPL vs MSFT returns and also AAPL supply chain risks",
                                        client=client, retrieve_fn=fake_retrieve, db_path=db_path))
    types = [e["type"] for e in events]
    assert types[0] == "route" and events[0]["route"] == "plan"
    assert "plan" in types and types.count("task_start") == 2 and types.count("task_done") == 2
    assert {e["task_id"] for e in events if e["type"] == "tool_call"} == {"t1", "t2"}
    verify = [e for e in events if e["type"] == "verify"]
    assert verify[0]["passed"] is True
    final = events[-1]
    assert final["type"] == "final" and "[F1]" in final["answer"] and final["sources"][0]["id"] == "F1"
    # Context isolation: the filings executor never saw the market executor's tool traffic.
    filings_calls = [c for c in client.calls if "Filings agent" in c.get("system", "")]
    assert all("compare_tickers" not in str(c["messages"]) for c in filings_calls)


def test_orchestrated_direct_route(db_path):
    client = FakeClient(message(text_block("AAPL answer")))
    events = list(orch.run_orchestrated("AAPL volatility?", client=client, retrieve_fn=fake_retrieve,
                                        db_path=db_path))
    assert events[0]["route"] == "direct" and events[-1]["answer"] == "AAPL answer"


# ------------------------------------------------------------------ hybrid retrieval
def test_bm25_prefers_exact_rare_terms():
    idx = hybrid.BM25(["general supply chain risk", "export controls under the CHIPS Act", "risk risk risk"])
    scores = idx.scores("CHIPS Act")
    assert scores.index(max(scores)) == 1


def test_rrf_fuses_and_tracks_sources():
    dense = [{"id": "a", "text": "A", "_source": "dense"}, {"id": "b", "text": "B", "_source": "dense"}]
    sparse = [{"id": "b", "text": "B", "_source": "bm25"}, {"id": "c", "text": "C", "_source": "bm25"}]
    fused = hybrid.rrf_fuse([dense, sparse])
    assert fused[0]["id"] == "b" and sorted(fused[0]["matched_by"]) == ["bm25", "dense"]


def test_hybrid_retrieve_combines_dense_bm25_and_rewrite(db_path):
    db.upsert_chunks(
        [
            {"chunk_id": "k1", "doc_id": "d", "ticker": "NVDA", "chunk_index": 0,
             "text": "Export controls under the CHIPS Act may restrict sales", "metadata_json": '{"ticker": "NVDA"}'},
            {"chunk_id": "k2", "doc_id": "d", "ticker": "NVDA", "chunk_index": 1,
             "text": "Competition is intense", "metadata_json": '{"ticker": "NVDA"}'},
        ],
        db_path=db_path,
    )
    seen_queries = []

    def dense(q, n_results, where):
        seen_queries.append(q)
        return [{"id": "k2", "text": "Competition is intense", "metadata": {"ticker": "NVDA"}}]

    hits = hybrid.hybrid_retrieve("chip export rules?", n_results=2, where={"ticker": "NVDA"},
                                  rewrite={"query": "export controls CHIPS Act", "keywords": ["CHIPS Act"]},
                                  dense_fn=dense, db_path=db_path)
    assert {h["id"] for h in hits} == {"k1", "k2"}
    assert seen_queries[0] == "chip export rules?"  # the original query is always searched
    assert len(seen_queries) == 3
