"""Multi-agent orchestration: Router -> (ReAct | Planner -> parallel Executors -> Synthesizer) -> Verifier.

                  +-------------------------- simple --------------------------+
    question -> Router                                                         v
    (rules, then   +-- complex --> Planner --> Executors (parallel,     --> Synthesizer --> Verifier --> answer
     LLM fallback)                 (JSON      isolated contexts,              (sees only        (citations +
                                    task DAG)  structured results)             task results)     numbers check;
                                                                                                one revision)
Design choices (and the interview answers behind them):

* **Routing is rules-first, LLM-second.** Cheap deterministic rules catch the
  obvious cases (one ticker + one intent -> direct; "compare X vs Y and ..." ->
  plan). Only ambiguous questions pay for an LLM classification call.
* **Simple questions skip planning.** A single ReAct agent answers them - a
  plan for "what's AAPL's volatility?" would only add latency and cost.
* **Executors are isolated.** Each gets a fresh context: its own sub-goal, a
  restricted tool subset for its specialty, and the *structured results* (not
  transcripts) of any tasks it depends on. That keeps every context short and
  stops one agent's noise from derailing another.
* **Tasks run in parallel** when they have no dependencies (a DAG executed in
  topological "waves").
* **Failure is contained.** An executor that errors is reported as a failed
  task result; the synthesizer is told what's missing instead of the whole
  request crashing.
* **"Done" is not trusted blindly.** A deterministic verifier checks that every
  [F#] citation exists and that figures in the answer appear in real tool
  outputs; on failure the synthesizer gets one revision attempt with the
  verifier's findings.
"""
from __future__ import annotations

import json
import queue
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator, Optional

from marketpulse import db
from marketpulse.llm.agent import SourceRegistry, Toolbox, run_agent
from marketpulse.llm.client import complete_json, complete_text, get_client

MAX_TASKS = 4

# --------------------------------------------------------------------------- specialists
SPECIALISTS: dict[str, dict] = {
    "market": {
        "tools": {"get_price_summary", "compare_tickers", "run_sql"},
        "prompt": "You are the Market Data agent. You analyse prices, returns, volatility, drawdowns and "
        "correlations using your tools. Report exact figures from tool results only.",
    },
    "filings": {
        "tools": {"search_filings", "get_sentiment_summary"},
        "prompt": "You are the Filings agent. You find and summarise evidence from SEC 10-K risk-factor text "
        "and the filing sentiment scores. Cite every excerpt you rely on as [F#].",
    },
    "sql": {
        "tools": {"run_sql"},
        "prompt": "You are the SQL Analyst agent. You answer quantitative questions by writing read-only "
        "SQLite queries. Show the key numbers you found.",
    },
}

_EXECUTOR_SUFFIX = """

Tickers in the database: {tickers}.
You are one agent in a team working on a larger question. Do ONLY your assigned task.
Finish with a compact result: 3-6 bullets of findings with exact figures and [F#] citations.

Database schema for run_sql:
""" + db.PUBLIC_SCHEMA_DOC

# --------------------------------------------------------------------------- router
_COMPARE_RE = re.compile(r"\b(compare|comparison|versus|vs\.?|relative to|against|better|worse)\b", re.I)
_MULTI_INTENT_RE = re.compile(r"\b(and also|as well as|then|additionally|plus)\b|;|\?.+\?", re.I)
_TICKER_TOKEN_RE = re.compile(r"\b[A-Z]{1,5}\b")

ROUTER_SYSTEM = """Classify an equity-research question.
"direct": answerable by one agent with a few tool calls (one company, one topic).
"plan": needs several distinct sub-tasks (multiple companies AND topics, or several separate asks).
Return JSON: {"route": "direct"|"plan", "reason": short reason}"""


def route(question: str, known_tickers: list[str], client: Any = None) -> dict:
    tickers = sorted({t for t in _TICKER_TOKEN_RE.findall(question) if t in known_tickers})
    multi_intent = bool(_MULTI_INTENT_RE.search(question))
    compare = bool(_COMPARE_RE.search(question))
    words = len(question.split())

    if len(tickers) <= 1 and not multi_intent and not compare and words <= 25:
        return {"route": "direct", "method": "rules", "reason": "single company, single intent", "tickers": tickers}
    if len(tickers) >= 3 or (len(tickers) >= 2 and (multi_intent or compare) and words > 8):
        reason = f"{len(tickers)} companies, multi-part"
        return {"route": "plan", "method": "rules", "reason": reason, "tickers": tickers}

    out = complete_json(ROUTER_SYSTEM, question, max_tokens=120, client=client)
    r = out.get("route") if out.get("route") in {"direct", "plan"} else "direct"
    return {"route": r, "method": "llm", "reason": str(out.get("reason", ""))[:200], "tickers": tickers}


# --------------------------------------------------------------------------- planner
PLANNER_SYSTEM = f"""You are the Planner in a team of research agents. Split the user's question into at most
{MAX_TASKS} small, independent tasks. Available specialist agents:
- "market": prices, returns, volatility, drawdown, correlations
- "filings": 10-K risk-factor evidence and filing sentiment
- "sql": any other quantitative question answerable by SQL over prices/filings/sentiment
Tasks may depend on earlier tasks ("depends_on") only when they truly need their output; prefer
independent tasks so they run in parallel. Do not add a final "combine" task - a synthesizer does that.

Return JSON: {{"tasks": [{{"id": "t1", "agent": "market"|"filings"|"sql", "goal": one-sentence task,
"depends_on": []}}]}}"""


def _validate_plan(raw: dict) -> list[dict]:
    tasks, ids = [], set()
    for i, t in enumerate((raw.get("tasks") or [])[:MAX_TASKS], start=1):
        agent = t.get("agent") if t.get("agent") in SPECIALISTS else "filings"
        tid = str(t.get("id") or f"t{i}")
        if tid in ids:
            tid = f"t{i}"
        deps = [d for d in (t.get("depends_on") or []) if d in ids]  # only backwards edges -> no cycles
        tasks.append({"id": tid, "agent": agent, "goal": str(t.get("goal", ""))[:300], "depends_on": deps})
        ids.add(tid)
    if not tasks:
        raise ValueError("Planner returned no tasks")
    return tasks


def plan(question: str, client: Any = None) -> list[dict]:
    return _validate_plan(complete_json(PLANNER_SYSTEM, question, max_tokens=600, client=client))


def _waves(tasks: list[dict]) -> list[list[dict]]:
    """Group tasks into dependency levels; each wave runs in parallel."""
    done: set[str] = set()
    remaining = list(tasks)
    waves = []
    while remaining:
        ready = [t for t in remaining if set(t["depends_on"]) <= done]
        if not ready:  # defensive: shouldn't happen after _validate_plan
            ready = remaining[:]
        waves.append(ready)
        done |= {t["id"] for t in ready}
        remaining = [t for t in remaining if t["id"] not in done]
    return waves


# --------------------------------------------------------------------------- verifier
_CITE_RE = re.compile(r"\[(F\d+)\]")
_NUM_RE = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?(?![\w])")


def _num_variants(token: str) -> set[str]:
    raw = token.replace(",", "").rstrip("%")
    try:
        v = float(raw)
    except ValueError:
        return {raw}
    return {raw, f"{v:.1f}", f"{v:.2f}", f"{v:.0f}", str(v)}


def verify(answer: str, sources: list[dict], observations: list[str]) -> dict:
    """Deterministic checks on the final answer. Returns issues found (empty = passed)."""
    valid_ids = {s["id"] for s in sources}
    unknown = sorted(set(_CITE_RE.findall(answer)) - valid_ids)

    evidence = " ".join(observations)
    evidence_nums: set[str] = set()
    for tok in _NUM_RE.findall(evidence):
        evidence_nums |= _num_variants(tok)
    unverified = []
    for tok in _NUM_RE.findall(answer):
        plain = tok.replace(",", "").rstrip("%").lstrip("-")
        if len(plain.replace(".", "")) < 2 or re.fullmatch(r"(19|20)\d\d", plain):
            continue  # skip tiny numbers ("3 risks") and years
        if not (_num_variants(tok) & evidence_nums) and not (_num_variants(tok.lstrip("-")) & evidence_nums):
            unverified.append(tok)
    return {
        "passed": not unknown and not unverified,
        "unknown_citations": unknown,
        "unverified_numbers": sorted(set(unverified))[:10],
        "citations_checked": len(_CITE_RE.findall(answer)),
    }


# --------------------------------------------------------------------------- synthesizer
SYNTH_SYSTEM = """You are the Synthesizer. Combine the task results from specialist agents into one answer to the
user's question. Use ONLY facts and figures present in the task results; keep their [F#] citations.
If a task failed or found nothing, say what is missing. Format: a one-sentence headline, then concise bullets
or a small markdown table, then a one-line caveat. Research support, not investment advice."""


def _synthesize(question: str, results: list[dict], client: Any, feedback: str = "") -> str:
    payload = [
        {"task": r["id"], "agent": r["agent"], "goal": r["goal"], "status": r["status"], "result": r["result"]}
        for r in results
    ]
    prompt = f"User question: {question}\n\nTask results (JSON):\n{json.dumps(payload, indent=1)}"
    if feedback:
        prompt += f"\n\nA verifier found problems in your previous draft - fix them:\n{feedback}"
    return complete_text(SYNTH_SYSTEM, prompt, max_tokens=1500, client=client)


# --------------------------------------------------------------------------- orchestrator
def _run_executor(task: dict, question: str, deps: list[dict], client: Any, toolbox: Toolbox, out_q: queue.Queue):
    spec = SPECIALISTS[task["agent"]]
    brief = f"Overall user question (context only): {question}\n\nYOUR TASK: {task['goal']}"
    if deps:
        brief += "\n\nResults from tasks you depend on:\n" + json.dumps(
            [{"task": d["id"], "result": d["result"]} for d in deps], indent=1
        )
    final = {"answer": "", "steps": 0}
    try:
        for ev in run_agent(
            brief,
            client=client,
            toolbox=toolbox,
            max_steps=4,
            system_prompt=spec["prompt"] + _EXECUTOR_SUFFIX,
            allowed_tools=spec["tools"],
            task_id=task["id"],
        ):
            if ev["type"] == "final":
                final = ev
            else:
                out_q.put(ev)
        status = "done" if final["answer"] else "empty"
        result = final["answer"] or "(no findings)"
    except Exception as exc:  # noqa: BLE001 - a failed executor becomes a failed task, not a failed request
        status, result = "failed", f"{type(exc).__name__}: {exc}"
    return {**task, "status": status, "result": result[:3000], "steps": final.get("steps", 0)}


def run_orchestrated(
    question: str,
    history: Optional[list[dict]] = None,
    mode: str = "auto",
    client: Optional[Any] = None,
    retrieve_fn: Any = None,
    db_path: Optional[str] = None,
) -> Iterator[dict]:
    """Entry point for the /api/agent endpoint. Yields trace events for streaming."""
    c = get_client(client)
    registry = SourceRegistry()
    toolbox = Toolbox(db_path=db_path, retrieve_fn=retrieve_fn, registry=registry)

    if mode in {"direct", "plan"}:
        decision = {"route": mode, "method": "user", "reason": "forced by user", "tickers": []}
    else:
        decision = route(question, db.list_tickers(db_path=db_path), client=c)
    yield {"type": "route", **decision}

    if decision["route"] == "direct":
        final = None
        for ev in run_agent(question, history=history, client=c, toolbox=toolbox, db_path=db_path):
            if ev["type"] == "final":
                final = ev
            else:
                yield ev
        answer = (final or {}).get("answer", "")
    else:
        yield {"type": "status", "message": "Planner is splitting the question into tasks..."}
        tasks = plan(question, client=c)
        yield {"type": "plan", "tasks": tasks}

        results: dict[str, dict] = {}
        events: queue.Queue = queue.Queue()
        for wave in _waves(tasks):
            for t in wave:
                yield {"type": "task_start", "task_id": t["id"], "agent": t["agent"], "goal": t["goal"]}
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                futures = [
                    pool.submit(
                        _run_executor, t, question, [results[d] for d in t["depends_on"]], c, toolbox, events
                    )
                    for t in wave
                ]
                # Relay executor events live while the wave runs.
                while not all(f.done() for f in futures) or not events.empty():
                    try:
                        yield events.get(timeout=0.1)
                    except queue.Empty:
                        continue
                for f in futures:
                    r = f.result()
                    results[r["id"]] = r
                    yield {"type": "task_done", "task_id": r["id"], "status": r["status"], "summary": r["result"][:400]}

        yield {"type": "status", "message": "Synthesizer is combining task results..."}
        ordered = [results[t["id"]] for t in tasks]
        answer = _synthesize(question, ordered, c)
        check = verify(answer, registry.items, toolbox.observations)
        yield {"type": "verify", "attempt": 1, **check}
        if not check["passed"]:
            feedback = json.dumps({k: check[k] for k in ("unknown_citations", "unverified_numbers")})
            answer = _synthesize(question, ordered, c, feedback=feedback)
            check = verify(answer, registry.items, toolbox.observations)
            yield {"type": "verify", "attempt": 2, **check}

    if decision["route"] == "direct":
        check = verify(answer, registry.items, toolbox.observations)
        yield {"type": "verify", "attempt": 1, **check}

    yield {"type": "final", "answer": answer, "sources": registry.items, "route": decision["route"]}
