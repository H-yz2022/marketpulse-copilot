import dataclasses

import pytest

from marketpulse.llm import client as llm_client
from marketpulse.llm.agent import Toolbox, run_agent
from marketpulse.llm.briefs import compare_companies, research_brief
from tests.fakes import FakeClient, fake_retrieve, message, seed_db, text_block, tool_block


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "llm.db")
    seed_db(path)
    return path


def test_parse_json_object_handles_fences_and_preamble():
    assert llm_client.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm_client.parse_json_object('Sure! Here it is: {"a": {"b": 2}} Thanks') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        llm_client.parse_json_object("no json here")


def test_get_client_without_key_raises(monkeypatch):
    monkeypatch.setattr(llm_client, "settings", dataclasses.replace(llm_client.settings, anthropic_api_key=""))
    with pytest.raises(llm_client.LLMUnavailableError):
        llm_client.get_client(None)


def test_agent_calls_tools_then_answers(db_path):
    client = FakeClient(
        message(
            text_block("Let me pull the numbers."),
            tool_block("t1", "get_price_summary", {"ticker": "aapl"}),
            tool_block("t2", "search_filings", {"query": "supply chain", "ticker": "AAPL", "k": 2}),
            stop_reason="tool_use",
        ),
        message(tool_block("t3", "run_sql", {"sql": "DELETE FROM filings"}), stop_reason="tool_use"),
        message(text_block("AAPL rose over the period [F1]."), stop_reason="end_turn"),
    )
    toolbox = Toolbox(db_path=db_path, retrieve_fn=fake_retrieve)
    events = list(run_agent("How is AAPL doing?", client=client, toolbox=toolbox, db_path=db_path))
    types = [e["type"] for e in events]
    assert types[0] == "status" and types[-1] == "final"
    assert types.count("tool_call") == 3

    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["is_error"] is False and "AAPL" in results[0]["summary"]
    assert results[2]["is_error"] is True and "SQL guard" in results[2]["summary"]

    final = events[-1]
    assert final["answer"].startswith("AAPL rose") and final["steps"] == 3
    assert [s["id"] for s in final["sources"]] == ["F1", "F2"]

    # The tool results were sent back to the model paired with their tool_use ids.
    second_call_msgs = client.calls[1]["messages"]
    assert second_call_msgs[-1]["content"][0]["tool_use_id"] == "t1"
    assert "AAPL" in client.calls[0]["system"] and "MSFT" in client.calls[0]["system"]


def test_agent_respects_step_limit(db_path):
    loop = message(tool_block("t", "get_sentiment_summary", {"ticker": "MSFT"}), stop_reason="tool_use")
    client = FakeClient(loop, loop, message(text_block("Best effort answer.")))
    events = list(run_agent("q", client=client, toolbox=Toolbox(db_path=db_path, retrieve_fn=fake_retrieve),
                            max_steps=2, db_path=db_path))
    assert events[-1] == {"type": "final", "answer": "Best effort answer.", "sources": [], "steps": 2}
    assert client.calls[-1]["tool_choice"] == {"type": "none"}


def test_agent_rejects_bad_ticker_and_unknown_tool(db_path):
    client = FakeClient(
        message(tool_block("a", "get_price_summary", {"ticker": "'; DROP"}), tool_block("b", "hack", {}),
                stop_reason="tool_use"),
        message(text_block("done")),
    )
    events = list(run_agent("q", client=client, toolbox=Toolbox(db_path=db_path, retrieve_fn=fake_retrieve),
                            db_path=db_path))
    errors = [e for e in events if e["type"] == "tool_result" and e["is_error"]]
    assert len(errors) == 2


def test_research_brief_grounds_prompt_in_data(db_path):
    client = FakeClient({"headline": "H", "summary": "S", "bull_points": [], "bear_points": [], "key_risks": []})
    r = research_brief("aapl", client=client, retrieve_fn=fake_retrieve, db_path=db_path)
    assert r["ticker"] == "AAPL" and r["brief"]["headline"] == "H"
    assert [s["n"] for s in r["sources"]] == [1, 2, 3]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "[1] (AAPL 10-K 2025-11-01)" in prompt and '"last_close"' in prompt


def test_research_brief_unknown_ticker(tmp_path):
    with pytest.raises(LookupError):
        research_brief("ZZZ", client=FakeClient(), retrieve_fn=lambda *a, **k: [], db_path=str(tmp_path / "e.db"))


def test_compare_numbers_citations_across_both_companies(db_path):
    client = FakeClient({"overview": "O", "shared_risks": [], "unique_to_a": [], "unique_to_b": []})
    r = compare_companies("AAPL", "MSFT", client=client, retrieve_fn=fake_retrieve, db_path=db_path)
    assert [s["n"] for s in r["sources"]] == [1, 2, 3, 4, 5, 6]
    assert {s["ticker"] for s in r["sources"][3:]} == {"MSFT"}
    assert set(r["performance"]) == {"AAPL", "MSFT"}
    with pytest.raises(ValueError):
        compare_companies("AAPL", "aapl", client=client, retrieve_fn=fake_retrieve, db_path=db_path)
