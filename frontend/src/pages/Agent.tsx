import { useEffect, useRef, useState } from "react";
import { streamAgent, type AgentEvent, type AgentMode, type PlanTask, type Source } from "../api";
import { Markdown } from "../components/Markdown";
import { Sources, focusSource } from "../components/Sources";
import { Card, ErrorBox, Segmented, Spinner, errMsg } from "../components/ui";

interface Step {
  id: string;
  name: string;
  input: Record<string, unknown>;
  summary?: string;
  isError?: boolean;
}

interface Lane {
  task: PlanTask;
  status: "queued" | "running" | "done" | "failed" | "empty";
  steps: Step[];
  summary?: string;
}

interface Turn {
  question: string;
  route?: { route: string; method: string; reason: string };
  steps: Step[]; // direct-route trace
  plan?: PlanTask[];
  lanes: Record<string, Lane>;
  status?: string;
  verify?: { attempt: number; passed: boolean; unknown_citations: string[]; unverified_numbers: string[] }[];
  answer?: string;
  sources: Source[];
  error?: string;
  done: boolean;
}

const SUGGESTIONS = [
  "What are NVDA's biggest disclosed risks, and how volatile has the stock been?",
  "Compare AAPL vs MSFT on return, drawdown and filing sentiment, and also summarise JPM's regulatory risks.",
  "Which ticker had the largest max drawdown, and what risks might explain it?",
  "How correlated are the daily returns of AAPL, MSFT and NVDA?",
];

const TOOL_LABEL: Record<string, string> = {
  get_price_summary: "Price KPIs",
  get_sentiment_summary: "Sentiment",
  search_filings: "Search 10-Ks",
  run_sql: "SQL",
  compare_tickers: "Compare",
};

const AGENT_LABEL: Record<string, string> = { market: "Market Data agent", filings: "Filings agent", sql: "SQL Analyst agent" };

function reduce(turn: Turn, e: AgentEvent): Turn {
  const t: Turn = { ...turn, lanes: { ...turn.lanes } };
  switch (e.type) {
    case "route":
      t.route = { route: e.route, method: e.method, reason: e.reason };
      break;
    case "status":
      t.status = e.message;
      break;
    case "plan":
      t.plan = e.tasks;
      e.tasks.forEach((task) => (t.lanes[task.id] = { task, status: "queued", steps: [] }));
      break;
    case "task_start":
      if (t.lanes[e.task_id]) t.lanes[e.task_id] = { ...t.lanes[e.task_id], status: "running" };
      break;
    case "task_done":
      if (t.lanes[e.task_id])
        t.lanes[e.task_id] = { ...t.lanes[e.task_id], status: e.status as Lane["status"], summary: e.summary };
      break;
    case "tool_call": {
      const step: Step = { id: e.id, name: e.name, input: e.input };
      if (e.task_id && t.lanes[e.task_id]) {
        const lane = t.lanes[e.task_id];
        t.lanes[e.task_id] = { ...lane, steps: [...lane.steps, step] };
      } else t.steps = [...t.steps, step];
      break;
    }
    case "tool_result": {
      const patch = (steps: Step[]) => steps.map((s) => (s.id === e.id ? { ...s, summary: e.summary, isError: e.is_error } : s));
      if (e.task_id && t.lanes[e.task_id]) {
        const lane = t.lanes[e.task_id];
        t.lanes[e.task_id] = { ...lane, steps: patch(lane.steps) };
      } else t.steps = patch(t.steps);
      break;
    }
    case "verify":
      t.verify = [...(t.verify ?? []), e];
      break;
    case "final":
      t.answer = e.answer;
      t.sources = e.sources;
      t.done = true;
      t.status = undefined;
      break;
    case "error":
      t.error = e.message;
      t.done = true;
      break;
  }
  return t;
}

function StepRow({ s }: { s: Step }) {
  const pending = s.summary === undefined;
  const arg = Object.entries(s.input)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(", ");
  return (
    <div className="step">
      <span className={`ico ${pending ? "" : s.isError ? "err" : "ok"}`}>{pending ? <Spinner /> : s.isError ? "!" : "✓"}</span>
      <div style={{ minWidth: 0 }}>
        <b>{TOOL_LABEL[s.name] ?? s.name}</b> <code title={arg}>{arg.length > 90 ? arg.slice(0, 90) + "…" : arg}</code>
        {s.summary && <div className={s.isError ? "delta-neg" : "muted"}>{s.summary}</div>}
      </div>
    </div>
  );
}

function TurnView({ turn, index }: { turn: Turn; index: number }) {
  const scope = `agent${index}`;
  const lanes = Object.values(turn.lanes);
  const lastVerify = turn.verify?.[turn.verify.length - 1];
  return (
    <div className="chat">
      <div className="msg-user">{turn.question}</div>
      <div className="msg-ai">
        <div className="trace">
          <div className="trace-h">
            {turn.route ? (
              <>
                <span className="badge brand">{turn.route.route === "plan" ? "Planner → parallel executors" : "Single ReAct agent"}</span>
                <span className="muted small" style={{ fontWeight: 400 }}>
                  routed by {turn.route.method === "rules" ? "rules" : turn.route.method === "llm" ? "LLM classifier" : "you"} · {turn.route.reason}
                </span>
              </>
            ) : (
              <span className="muted">Routing…</span>
            )}
            {!turn.done && turn.status && (
              <span className="muted small pulse" style={{ marginLeft: "auto", fontWeight: 400 }}>
                {turn.status}
              </span>
            )}
          </div>
          {turn.steps.map((s) => (
            <StepRow key={s.id} s={s} />
          ))}
          {lanes.length > 0 && (
            <div className="lanes">
              {lanes.map((l) => (
                <div className="lane" key={l.task.id}>
                  <div className="lane-h">
                    <span className={`badge ${l.status === "done" ? "pos" : l.status === "failed" ? "neg" : l.status === "running" ? "brand" : "neu"}`}>
                      {l.status === "running" ? <span className="pulse">running</span> : l.status}
                    </span>
                    {AGENT_LABEL[l.task.agent] ?? l.task.agent}
                    <span className="muted" style={{ marginLeft: "auto", fontWeight: 400 }}>{l.task.id}{l.task.depends_on.length ? ` ← ${l.task.depends_on.join(", ")}` : ""}</span>
                  </div>
                  <div className="lane-goal">{l.task.goal}</div>
                  {l.steps.map((s) => (
                    <StepRow key={s.id} s={s} />
                  ))}
                </div>
              ))}
            </div>
          )}
          {lastVerify && (
            <div className="step">
              <span className={`ico ${lastVerify.passed ? "ok" : "err"}`}>{lastVerify.passed ? "✓" : "!"}</span>
              <div>
                <b>Verifier</b>{" "}
                {lastVerify.passed
                  ? `passed${turn.verify && turn.verify.length > 1 ? " after 1 revision" : ""} - citations exist and figures match tool outputs`
                  : `flagged: ${[...lastVerify.unknown_citations.map((c) => `unknown citation ${c}`), ...lastVerify.unverified_numbers.map((n) => `unverified figure ${n}`)].join(", ")}`}
              </div>
            </div>
          )}
        </div>
        <ErrorBox message={turn.error ?? null} />
        {turn.answer !== undefined && (
          <div className="card">
            <Markdown text={turn.answer} onCite={(id) => focusSource(scope, id)} />
            {turn.sources.length > 0 && (
              <div style={{ marginTop: 12 }}>
                <Sources sources={turn.sources} scope={scope} title="Evidence the agents retrieved" />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Agent({ tickers, onUsage }: { tickers: string[]; onUsage: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [mode, setMode] = useState<AgentMode>("auto");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (q: string) => {
    const question = q.trim();
    if (question.length < 3 || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);
    const history = turns
      .filter((t) => t.answer)
      .flatMap((t) => [
        { role: "user" as const, content: t.question },
        { role: "assistant" as const, content: t.answer as string },
      ]);
    const idx = turns.length;
    setTurns((ts) => [...ts, { question, steps: [], lanes: {}, sources: [], done: false }]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamAgent(question, history, mode, (e) => setTurns((ts) => ts.map((t, i) => (i === idx ? reduce(t, e) : t))), ctrl.signal);
    } catch (e) {
      if (!ctrl.signal.aborted) {
        const msg = errMsg(e);
        setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, error: msg, done: true } : t)));
      }
    } finally {
      setBusy(false);
      onUsage();
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Multi-agent analyst</div>
          <h1>Ask the research team</h1>
          <p>
            A router sends simple questions to one ReAct agent and complex ones to a planner that splits the work
            across specialist agents running in parallel with isolated contexts. A synthesizer merges their
            structured results and a verifier checks every citation and figure before you see it.
          </p>
        </div>
        <div className="stack" style={{ alignItems: "flex-end" }}>
          <span className="small muted">Orchestration</span>
          <Segmented
            value={mode}
            onChange={setMode}
            options={[
              { value: "auto", label: "Auto-route" },
              { value: "direct", label: "Single agent" },
              { value: "plan", label: "Plan + execute" },
            ]}
          />
        </div>
      </div>

      {turns.length === 0 && (
        <Card title="Try one of these" subtitle={tickers.length ? `Data available for ${tickers.join(", ")}` : undefined}>
          <div className="grid grid-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="suggestion" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </Card>
      )}

      {turns.map((t, i) => (
        <TurnView key={i} turn={t} index={i} />
      ))}
      <div ref={endRef} />
      <ErrorBox message={error} />

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <textarea
          rows={1}
          value={draft}
          placeholder="Ask about prices, risks, sentiment - or several things at once…"
          aria-label="Question for the analyst agents"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(draft);
            }
          }}
        />
        {busy ? (
          <button type="button" className="btn" onClick={() => abortRef.current?.abort()}>
            Stop
          </button>
        ) : (
          <button className="btn btn-primary" disabled={draft.trim().length < 3}>
            Send
          </button>
        )}
      </form>
    </div>
  );
}
