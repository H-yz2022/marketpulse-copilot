# Architecture and design decisions

Each section below records one decision, the alternative that was rejected and the reason, with a pointer to the code that implements it.

## 1. Request path for `/api/agent`

```
POST /api/agent ─► _llm_guard (AI enabled? per-client + global daily caps)
               ─► orchestrator.run_orchestrated
                    ├─ route()            rules → (ambiguous only) LLM classifier
                    ├─ direct: run_agent() one ReAct loop with all tools
                    └─ plan:   plan() → _waves() → _run_executor() × N in a thread pool
                               → _synthesize() → verify() → (one revision if needed)
               ─► Server-Sent Events: route, plan, task_start, tool_call, tool_result,
                                      task_done, verify, final
```

The **synthesizer** (plan route) or the **ReAct agent** (direct route) produces the answer. The **verifier** is always the last step before `final`.

## 2. Routing: rules first, LLM second
*Rejected: always asking the LLM.* That costs a model call and ~1s on every request, and it adds non-determinism to decisions that a regex can make perfectly (one ticker, one intent). The LLM is only used when the rules can't decide. The `route` event records `method: rules|llm|user`, so routing quality can be audited.

## 3. Plan-and-execute only for complex questions
*Rejected: planning everything.* For "What's AAPL's volatility?" a planner adds an LLM round trip and a synthesis step, and gives the model more chances to go wrong. ReAct already interleaves reasoning and acting. Planning pays off when a question has **independent sub-tasks** that can run in parallel, or when a single agent's context would fill up with unrelated tool output.

## 4. Specialist executors instead of one agent with every tool
Each executor gets a **narrow prompt and a restricted tool subset** (`SPECIALISTS`). This gives fewer wrong-tool choices, shorter prompts, independent failure and parallelism.
*Trade-off:* more LLM calls in total, a synthesis step that can lose nuance, and harder debugging. That is why simple questions still go to a single agent.

## 5. Context isolation and communication
Executors **never share transcripts**. An executor receives the user question (for context only), its own goal, and the **structured `result` strings** of the tasks it depends on. The synthesizer sees only `{task, agent, goal, status, result}` for each task. This keeps every context short and stops one agent's dead ends from biasing another. Citation ids are shared through a thread-safe `SourceRegistry`, so parallel agents never hand out the same `[F#]` id twice.

## 6. Failure handling

| Failure | Handling |
|---|---|
| Tool raises a validation or data error | Returned to the model as `is_error: true` with a helpful message; the model adapts |
| Tool times out or hits a network error | **One automatic retry**, then reported as an error |
| Unknown tool or bad arguments | Error that lists the valid tools; the loop continues |
| Tool not allowed for this executor | Error naming the allowed tools |
| Identical call repeated | Not re-executed: the earlier result is returned with an instruction to move on. After more than 2 loop hits, the run is forced to answer |
| Step budget exhausted | Final call with `tool_choice: none`, asking for a best-effort answer |
| Executor crashes | Becomes a `failed` task result; the synthesizer is told what's missing |
| Answer cites unknown sources or invents numbers | The verifier flags it and the synthesizer gets one revision |

## 7. Model portability
All model calls go through `llm/client.py` plus the Messages API tool-use format. Swapping models means changing `ANTHROPIC_MODEL`. Swapping *vendors* means writing an adapter for `messages.create` and the tool-use content blocks. The orchestration, tools, guardrails and verifier stay the same, because they only depend on "a function that returns text and tool calls". Prompts are the part that needs re-tuning. The offline test suite (scripted fake client) pins the orchestration logic independently of any model.

## 8. RAG pipeline
- **Extraction:** the *last* "Item 1A. Risk Factors" header, read up to "Item 1B". The first header is usually the table of contents.
- **Chunking:** sentence-aware windows of about 800 characters with 100 characters of overlap. Chunks are stored in Chroma for dense search and mirrored in SQLite for BM25.
- **Retrieval:** dense and BM25 for the original query, plus the LLM rewrite and its keywords when enabled. All ranked lists are fused with RRF (k=60).
- **Evaluation:** `scripts/eval_retrieval.py` reports Recall@k and MRR for each retriever and chunking setting.
- **Refresh semantics:** re-ingesting a ticker deletes its filings, sentiment rows, vectors and BM25 chunks first. Without this, stale chunks from older filings kept winning retrieval.

## 9. What I'd add next
Cross-encoder reranking; contextual chunk headers; an LLM-as-judge answer eval; tracing (OpenTelemetry spans per agent and tool) and token cost per request; caching of tool results across requests; Postgres + pgvector to replace SQLite + Chroma.
