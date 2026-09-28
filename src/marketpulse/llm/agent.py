"""A tool-using analyst agent built on Claude's native tool use.

Instead of one fixed retrieve-then-answer step, Claude is given a small set
of tools over our own data and decides which to call, in what order, until
it has enough evidence to answer. Each step is yielded as an event so the
frontend can stream the agent's reasoning trace live:

    {"type": "status",      "message": "..."}
    {"type": "tool_call",   "id", "name", "input"}
    {"type": "tool_result", "id", "name", "summary", "is_error"}
    {"type": "text",        "text"}           # interim narration between tool calls
    {"type": "final",       "answer", "sources", "steps"}
    {"type": "error",       "message"}

Every event may also carry "task_id" when the agent runs as one executor
inside the multi-agent orchestrator (see orchestrator.py).

Guardrails (each maps to a classic agent failure mode):
  * step budget      - hard cap on tool round trips (settings.agent_max_steps)
  * loop detection   - an identical (tool, arguments) call is not re-executed; the
                       model is told to reuse the earlier result, and repeated
                       loop hits end the run early
  * timeouts/retries - each tool runs with a timeout; transient failures
                       (timeouts, network errors) are retried once, anything else
                       goes back to the model as an error it can adapt to
  * wrong tool       - unknown tools / bad arguments return an error listing the
                       valid options instead of crashing the loop
  * least privilege  - every tool is read-only, SQL goes through the 4-layer
                       guard, and executors can be restricted to a tool subset
  * context budget   - tool output is truncated before going back to the model
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, Iterator, Optional

from marketpulse import analytics, db
from marketpulse.config import settings
from marketpulse.llm.client import get_client
from marketpulse.llm.sql_guard import UnsafeSQLError, run_readonly

_TICKER_RE = re.compile(r"^[A-Z][A-Z.\-]{0,9}$")
MAX_TOOL_OUTPUT_CHARS = 6000
TOOL_TIMEOUT_S = 25.0
MAX_LOOP_HITS = 2  # identical repeated calls tolerated before the run is ended
_TOOL_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent-tool")

SYSTEM = f"""You are MarketPulse Copilot, an equity research analyst assistant.
You have tools over a local research database of daily prices, SEC 10-K risk-factor excerpts and
NLP sentiment scores. Tickers currently in the database: {{tickers}}.

How to work:
- Plan briefly, then call tools to gather evidence. Prefer several small, targeted calls.
- Use get_price_summary / compare_tickers for performance and risk numbers, search_filings for
  qualitative risk-factor evidence, and run_sql for anything else quantitative.
- Never invent numbers: every figure you state must come from a tool result.
- When you quote filing evidence, cite it inline as [F1], [F2] ... using the ids that
  search_filings returns.
- Final answer: a short headline sentence, then concise bullets or a small markdown table, then a
  one-line caveat if data is limited. This is research support, not investment advice.

Database schema for run_sql:
{db.PUBLIC_SCHEMA_DOC}"""

TOOLS: list[dict] = [
    {
        "name": "get_price_summary",
        "description": "Price KPIs for one ticker over the stored history: last close, 1-day change, 1-month "
        "and full-period return, annualised volatility, max drawdown, period high/low, average volume.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string", "description": "Upper-case symbol, e.g. AAPL"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "get_sentiment_summary",
        "description": "Aggregate NLP sentiment of a ticker's SEC filing text: counts by label and a net "
        "sentiment index from -1 (negative) to +1 (positive).",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
    {
        "name": "search_filings",
        "description": "Semantic search over indexed 10-K risk-factor text. Returns the most relevant "
        "excerpts with citation ids (F1, F2, ...). Optionally restrict to one ticker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in natural language"},
                "ticker": {"type": "string", "description": "Optional upper-case ticker filter"},
                "k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_sql",
        "description": "Run ONE read-only SQLite SELECT against price_history, filings and sentiment_scores. "
        "Returns up to 50 rows.",
        "input_schema": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
    {
        "name": "compare_tickers",
        "description": "Side-by-side KPIs, sentiment and pairwise return correlations for 2-6 tickers.",
        "input_schema": {
            "type": "object",
            "properties": {"tickers": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 6}},
            "required": ["tickers"],
        },
    },
]


class ToolError(Exception):
    """A tool failure the model should see and adapt to (bad args, no data, blocked SQL)."""


class TransientToolError(ToolError):
    """A failure worth one automatic retry (timeout, network blip)."""


class SourceRegistry:
    """Thread-safe citation registry shared by all executors of one request,
    so parallel agents never hand out the same [F#] id twice."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._lock = threading.Lock()

    def add(self, src: dict) -> str:
        with self._lock:
            sid = f"F{len(self.items) + 1}"
            self.items.append({"id": sid, **src})
            return sid


def _ticker(value: Any) -> str:
    t = str(value or "").strip().upper()
    if not _TICKER_RE.match(t):
        raise ToolError(f"Invalid ticker: {value!r}")
    return t


class Toolbox:
    """Executes the agent's tool calls. Collects filing citations as it goes."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        retrieve_fn: Optional[Callable[..., list[dict]]] = None,
        registry: Optional[SourceRegistry] = None,
        timeout_s: float = TOOL_TIMEOUT_S,
    ):
        self.db_path = db_path
        self.registry = registry or SourceRegistry()
        self.timeout_s = timeout_s
        # Raw tool outputs, kept so the verifier can check the final answer's numbers against them.
        self.observations: list[str] = []
        if retrieve_fn is None:
            from marketpulse.rag.hybrid import hybrid_retrieve as retrieve_fn  # lazy: pulls in chromadb
        self._retrieve = retrieve_fn

    @property
    def sources(self) -> list[dict]:
        return self.registry.items

    def run(self, name: str, args: dict) -> tuple[Any, str]:
        """Execute one tool with a timeout and one retry on transient errors.

        Returns (result for the model, one-line summary for the UI)."""
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            valid = ", ".join(t["name"] for t in TOOLS)
            raise ToolError(f"Unknown tool '{name}'. Valid tools: {valid}")
        last_exc: Exception = ToolError("tool failed")
        for _attempt in range(2):
            future = _TOOL_POOL.submit(handler, **(args or {}))
            try:
                output, summary = future.result(timeout=self.timeout_s)
                self.observations.append(json.dumps(output, default=str))
                return output, summary
            except FutureTimeout:
                last_exc = TransientToolError(f"{name} timed out after {self.timeout_s:.0f}s")
            except (ConnectionError, TimeoutError, TransientToolError) as exc:
                last_exc = TransientToolError(f"{name} failed transiently: {exc}")
            except TypeError as exc:  # wrong/missing arguments from the model
                raise ToolError(f"Bad arguments for {name}: {exc}") from exc
        raise last_exc

    def _tool_get_price_summary(self, ticker: str) -> tuple[Any, str]:
        t = _ticker(ticker)
        s = analytics.price_summary([dict(r) for r in db.fetch_price_history(t, db_path=self.db_path)])
        if not s.get("has_data"):
            return {"ticker": t, "error": "no price data stored"}, f"No price data for {t}"
        return {"ticker": t, **s}, f"{t}: last {s['last_close']}, period {s['return_period_pct']}%"

    def _tool_get_sentiment_summary(self, ticker: str) -> tuple[Any, str]:
        t = _ticker(ticker)
        s = analytics.sentiment_summary([dict(r) for r in db.fetch_sentiment_scores(t, db_path=self.db_path)])
        return {"ticker": t, **s}, f"{t}: {s['tone']} (net {s['net_index']}, n={s['n']})"

    def _tool_search_filings(self, query: str, ticker: Optional[str] = None, k: int = 4) -> tuple[Any, str]:
        k = max(1, min(int(k or 4), 8))
        where = {"ticker": _ticker(ticker)} if ticker else None
        hits = self._retrieve(query, n_results=k, where=where)
        out = []
        for h in hits:
            m = h.get("metadata") or {}
            meta = {"ticker": m.get("ticker"), "form_type": m.get("form_type"), "filed_date": m.get("filed_date")}
            sid = self.registry.add({**meta, "url": m.get("url"), "text": h["text"][:600]})
            out.append({"id": sid, **meta, "text": h["text"]})
        return out, f"{len(out)} excerpt(s) for '{query}'" + (f" in {ticker.upper()}" if ticker else "")

    def _tool_run_sql(self, sql: str) -> tuple[Any, str]:
        try:
            r = run_readonly(sql, max_rows=50, db_path=self.db_path)
        except UnsafeSQLError as exc:
            raise ToolError(f"Rejected by SQL guard: {exc}") from exc
        return r, f"{r['row_count']} row(s) x {len(r['columns'])} col(s)"

    def _tool_compare_tickers(self, tickers: list) -> tuple[Any, str]:
        ts = [_ticker(t) for t in (tickers or [])][:6]
        if len(ts) < 2:
            raise ToolError("Need at least two tickers")
        w = analytics.watchlist(ts, db_path=self.db_path)
        w.pop("performance", None)  # the daily series are too long to be useful to the model
        return w, f"Compared {', '.join(ts)}"


def _block_to_param(block: Any) -> dict:
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    raise ValueError(f"Unexpected content block type: {block.type}")


def _call_signature(name: str, args: Any) -> str:
    return name + ":" + json.dumps(args, sort_keys=True, default=str)


def run_agent(
    question: str,
    history: Optional[list[dict]] = None,
    client: Optional[Any] = None,
    toolbox: Optional[Toolbox] = None,
    max_steps: Optional[int] = None,
    db_path: Optional[str] = None,
    system_prompt: Optional[str] = None,
    allowed_tools: Optional[set[str]] = None,
    task_id: Optional[str] = None,
) -> Iterator[dict]:
    """Run a ReAct-style tool-use loop, yielding trace events (see module docstring).

    `system_prompt` / `allowed_tools` / `task_id` let the orchestrator reuse this
    same loop as a specialist executor with its own isolated context.
    """
    c = get_client(client)
    tools = toolbox or Toolbox(db_path=db_path)
    max_steps = max_steps or settings.agent_max_steps
    tool_specs = [t for t in TOOLS if allowed_tools is None or t["name"] in allowed_tools]
    system = system_prompt or SYSTEM
    system = system.replace("{tickers}", ", ".join(db.list_tickers(db_path=db_path)) or "none yet")
    tag = {"task_id": task_id} if task_id else {}

    messages: list[dict] = []
    for turn in (history or [])[-6:]:  # short memory of prior Q&A turns in this chat
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": str(turn["content"])[:4000]})
    messages.append({"role": "user", "content": question})

    seen: dict[str, str] = {}  # call signature -> earlier result content
    loop_hits = 0
    yield {"type": "status", "message": "Planning...", **tag}
    for step in range(1, max_steps + 1):
        response = c.messages.create(
            model=settings.anthropic_model, max_tokens=1800, system=system, tools=tool_specs, messages=messages
        )
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text = "".join(b.text for b in response.content if b.type == "text").strip()

        if response.stop_reason != "tool_use" or not tool_uses:
            yield {"type": "final", "answer": text, "sources": tools.sources, "steps": step, **tag}
            return

        if text:
            yield {"type": "text", "text": text, **tag}
        messages.append({"role": "assistant", "content": [_block_to_param(b) for b in response.content]})

        results = []
        for tu in tool_uses:
            yield {"type": "tool_call", "id": tu.id, "name": tu.name, "input": tu.input, **tag}
            sig = _call_signature(tu.name, tu.input)
            if allowed_tools is not None and tu.name not in allowed_tools:
                content = summary = (
                    f"Error: tool '{tu.name}' is not available to this agent. Use one of: {sorted(allowed_tools)}"
                )
                is_error = True
            elif sig in seen:
                loop_hits += 1
                content = (
                    "You already made this exact call. Its result was:\n" + seen[sig][:1500]
                    + "\nDo not repeat it - use this result, try something different, or answer."
                )
                summary, is_error = "Repeated identical call - skipped (loop guard)", True
            else:
                try:
                    output, summary = tools.run(tu.name, tu.input)
                    content = json.dumps(output, default=str)[:MAX_TOOL_OUTPUT_CHARS]
                    is_error = False
                    seen[sig] = content
                except (ToolError, ValueError) as exc:
                    content = summary = f"Error: {exc}"
                    is_error = True
            yield {"type": "tool_result", "id": tu.id, "name": tu.name, "summary": summary, "is_error": is_error, **tag}
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": content, "is_error": is_error})
        messages.append({"role": "user", "content": results})

        if loop_hits > MAX_LOOP_HITS:
            yield {"type": "status", "message": "Loop detected - forcing a final answer", **tag}
            break

    # Out of steps (or stuck in a loop): ask for a best-effort answer with no further tools.
    messages.append({"role": "user", "content": "Stop calling tools. Answer now with the evidence you have."})
    response = c.messages.create(
        model=settings.anthropic_model,
        max_tokens=1500,
        system=system,
        tools=tool_specs,
        tool_choice={"type": "none"},
        messages=messages,
    )
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    yield {"type": "final", "answer": text, "sources": tools.sources, "steps": step, **tag}
