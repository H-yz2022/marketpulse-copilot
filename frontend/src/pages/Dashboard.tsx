import { useMemo, useState } from "react";
import { navigate } from "../router";
import { api, type AskResult, type BriefResult } from "../api";
import { BarChart, LineChart } from "../components/Charts";
import { Markdown } from "../components/Markdown";
import { Sources, focusSource } from "../components/Sources";
import { TickerPicker } from "../components/TickerPicker";
import { Card, ErrorBox, Kpi, Segmented, Skeleton, Spinner, ToneBadge, useAction, useAsync } from "../components/ui";
import { fmtCompact, fmtDate, fmtNum, fmtPct, tickerColor, toneClass } from "../format";

type Range = "1M" | "3M" | "6M" | "1Y";
const RANGE_DAYS: Record<Range, number> = { "1M": 22, "3M": 66, "6M": 132, "1Y": 260 };

export default function Dashboard({ tickers, ticker, onMeta }: { tickers: string[]; ticker: string; onMeta: () => void }) {
  const ov = useAsync(() => api.overview(ticker), [ticker]);
  const [range, setRange] = useState<Range>("6M");
  const refresh = useAction(api.refresh);
  const brief = useAction(api.brief);
  const ask = useAction(api.ask);
  const [question, setQuestion] = useState("");

  const options = useMemo(() => Array.from(new Set([...tickers, ticker])), [tickers, ticker]);
  const prices = useMemo(() => (ov.data?.prices ?? []).slice(-RANGE_DAYS[range]), [ov.data, range]);
  const s = ov.data?.summary;
  const sent = ov.data?.sentiment;
  const hasData = !!s?.has_data;
  const briefData: BriefResult | null = brief.result?.ticker === ticker ? brief.result : null;
  const askData: AskResult | null = ask.result;

  const doRefresh = async (t = ticker) => {
    const r = await refresh.run(t);
    if (r) {
      onMeta();
      if (t === ticker) ov.reload();
      else navigate(`dashboard/${t}`);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Company dashboard</div>
          <h1>{ticker}</h1>
          <p>Prices, NLP sentiment on 10-K risk factors, and AI research tools for one company.</p>
        </div>
        <button className="btn" onClick={() => doRefresh()} disabled={refresh.busy}>
          {refresh.busy ? <Spinner /> : "↻"} {refresh.busy ? "Fetching SEC + market data…" : "Refresh live data"}
        </button>
      </div>

      <TickerPicker
        options={options}
        value={ticker}
        onChange={(t) => navigate(`dashboard/${t}`)}
        onAdd={(t) => (options.includes(t) ? navigate(`dashboard/${t}`) : doRefresh(t))}
        colorOf={tickerColor}
      />
      <ErrorBox message={refresh.error || ov.error} />
      {refresh.result && !refresh.busy && (
        <div className="alert info">
          ✓ Refreshed {refresh.result.ticker}: {refresh.result.prices} price rows, {refresh.result.filings} filings, {refresh.result.chunks} indexed chunks.
        </div>
      )}

      {ov.loading && !ov.data ? (
        <div className="kpi-grid">{Array.from({ length: 6 }, (_, i) => <div className="card kpi" key={i}><Skeleton height={48} /></div>)}</div>
      ) : !hasData ? (
        <Card>
          <div className="empty">
            <p>No stored data for <b>{ticker}</b> yet.</p>
            <button className="btn btn-primary" onClick={() => doRefresh()} disabled={refresh.busy}>
              {refresh.busy ? <Spinner /> : null} Fetch prices and 10-K filings
            </button>
          </div>
        </Card>
      ) : (
        <>
          <div className="kpi-grid">
            <Kpi label="Last close" value={`$${fmtNum(s?.last_close)}`} delta={s?.change_1d_pct} sub="1 day" />
            <Kpi label="1-month return" value={fmtPct(s?.return_1m_pct)} />
            <Kpi label="Period return" value={fmtPct(s?.return_period_pct)} sub={s?.start_date ? `since ${fmtDate(s.start_date)}` : undefined} />
            <Kpi label="Volatility (ann.)" value={fmtPct(s?.volatility_ann_pct, 1, false)} />
            <Kpi label="Max drawdown" value={fmtPct(s?.max_drawdown_pct)} />
            <Kpi
              label="Filing sentiment"
              value={sent?.net_index === null || sent?.net_index === undefined ? "—" : (sent.net_index > 0 ? "+" : "") + sent.net_index.toFixed(2)}
              sub={sent ? <ToneBadge tone={sent.tone} /> : undefined}
            />
          </div>

          <div className="grid grid-main">
            <Card
              title="Price"
              subtitle={`Daily close · ${prices.length} trading days`}
              actions={
                <Segmented
                  value={range}
                  onChange={setRange}
                  options={(["1M", "3M", "6M", "1Y"] as Range[]).map((r) => ({ value: r, label: r }))}
                />
              }
            >
              <LineChart
                area
                height={280}
                series={[{ name: ticker, color: "var(--s1)", points: prices.map((p) => ({ x: p.trade_date, y: p.close })) }]}
                yFormat={(v) => `$${v.toFixed(0)}`}
              />
              <div className="small muted" style={{ margin: "10px 0 4px" }}>Volume</div>
              <BarChart
                height={90}
                compactX
                categories={prices.map((p) => p.trade_date)}
                series={[{ name: "Volume", color: "var(--brand-1)", values: prices.map((p) => p.volume) }]}
                yFormat={fmtCompact}
              />
            </Card>

            <Card title="Filing sentiment" subtitle="NLP scores on 10-K risk-factor text">
              {sent && sent.n > 0 ? (
                <div className="stack">
                  <div className="sentbar" aria-label="Sentiment mix">
                    {(["positive", "neutral", "negative"] as const).map((k) =>
                      sent.counts[k] ? (
                        <div key={k} title={`${k}: ${sent.counts[k]}`} style={{ flex: sent.counts[k], background: `var(--${toneClass(k)})` }} />
                      ) : null,
                    )}
                  </div>
                  <div className="row small">
                    <span className="badge pos">▲ {sent.counts.positive} positive</span>
                    <span className="badge neu">● {sent.counts.neutral} neutral</span>
                    <span className="badge neg">▼ {sent.counts.negative} negative</span>
                  </div>
                  <div className="stack" style={{ maxHeight: 250, overflow: "auto" }}>
                    {ov.data?.sentiment_rows.slice(0, 8).map((r, i) => (
                      <div key={i} className="small" style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                        <span className={`badge ${toneClass(r.label)}`}>{r.label} · {r.score.toFixed(2)}</span>
                        <div className="muted" style={{ marginTop: 4 }}>{r.text_snippet}</div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="empty">No sentiment scores yet.</div>
              )}
            </Card>
          </div>

          <Card
            className=""
            title={<>✦ AI research brief</>}
            subtitle="Claude writes a grounded one-pager from the KPIs above and retrieved 10-K excerpts, with citations."
            actions={
              <button className="btn btn-primary" onClick={() => brief.run(ticker)} disabled={brief.busy}>
                {brief.busy ? <Spinner /> : "✦"} {briefData ? "Regenerate" : "Generate brief"}
              </button>
            }
          >
            <ErrorBox message={brief.error} />
            {brief.busy && !briefData && <div className="stack"><Skeleton height={22} width="60%" /><Skeleton height={60} /><Skeleton height={90} /></div>}
            {briefData && <BriefView data={briefData} />}
            {!briefData && !brief.busy && !brief.error && <div className="muted small">Takes ~10 seconds. Uses 1 AI request.</div>}
          </Card>

          <div className="grid grid-2">
            <Card title="Ask the filings" subtitle="Hybrid RAG: query rewrite → BM25 + vectors → rank fusion → cited answer">
              <form
                className="row"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (question.trim().length >= 3) ask.run(question.trim(), ticker);
                }}
              >
                <input className="input" style={{ flex: 1 }} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={`e.g. What supply-chain risks does ${ticker} disclose?`} />
                <button className="btn btn-soft" disabled={ask.busy}>{ask.busy ? <Spinner /> : "Ask"}</button>
              </form>
              <ErrorBox message={ask.error} />
              {askData && (
                <div className="stack" style={{ marginTop: 12 }}>
                  {askData.rewrite && (
                    <div className="small muted">
                      Rewritten query: <code>{askData.rewrite.query}</code>
                      {askData.rewrite.keywords.length > 0 && <> · keywords: {askData.rewrite.keywords.map((k) => <span key={k} className="badge outline" style={{ marginLeft: 4 }}>{k}</span>)}</>}
                    </div>
                  )}
                  <Markdown text={askData.answer} onCite={(id) => focusSource("ask", id)} />
                  <Sources sources={askData.sources} scope="ask" />
                </div>
              )}
            </Card>

            <Card title="Recent filings" subtitle="SEC EDGAR 10-K risk-factor sections">
              {ov.data?.filings.length ? (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr><th>Filed</th><th>Form</th><th>Excerpt</th></tr>
                    </thead>
                    <tbody>
                      {ov.data.filings.map((f) => (
                        <tr key={f.filing_id}>
                          <td style={{ whiteSpace: "nowrap" }}>{f.filed_date ? fmtDate(f.filed_date, true) : "—"}</td>
                          <td><span className="badge brand">{f.form_type || "—"}</span></td>
                          <td className="small">
                            <div className="muted">{f.excerpt_preview.slice(0, 180)}…</div>
                            {f.url && <a href={f.url} target="_blank" rel="noreferrer">Open on SEC ↗</a>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="empty">No filings indexed yet.</div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}

function BriefView({ data }: { data: BriefResult }) {
  const b = data.brief;
  const cite = (id: string) => focusSource("brief", id);
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="card hero" style={{ boxShadow: "none" }}>
        <div className="eyebrow" style={{ color: "#2d5557" }}>{data.ticker} · AI brief</div>
        <h2 style={{ fontSize: 19, marginTop: 4 }}>{b.headline}</h2>
        {b.summary && <div style={{ marginTop: 6 }}><Markdown text={b.summary} onCite={cite} /></div>}
      </div>
      <div className="grid grid-2">
        <div>
          <h3 className="delta-pos">▲ Bull case</h3>
          <ul className="bullets">{(b.bull_points ?? []).map((p, i) => <li key={i}><Markdown text={p} onCite={cite} /></li>)}</ul>
        </div>
        <div>
          <h3 className="delta-neg">▼ Bear case</h3>
          <ul className="bullets">{(b.bear_points ?? []).map((p, i) => <li key={i}><Markdown text={p} onCite={cite} /></li>)}</ul>
        </div>
      </div>
      {!!b.key_risks?.length && (
        <div className="stack">
          <h3>Key disclosed risks</h3>
          {b.key_risks.map((r, i) => (
            <div key={i} className={`risk ${r.severity ?? ""}`}>
              <div className="row">
                <b>{r.risk}</b>
                {r.severity && <span className={`badge ${r.severity === "high" ? "neg" : r.severity === "medium" ? "warn" : "pos"}`}>{r.severity}</span>}
              </div>
              <Markdown text={r.detail} onCite={cite} />
            </div>
          ))}
        </div>
      )}
      <div className="grid grid-2">
        {b.sentiment_read && (
          <div>
            <h3>Sentiment read</h3>
            <Markdown text={b.sentiment_read} onCite={cite} />
          </div>
        )}
        {!!b.watch_items?.length && (
          <div>
            <h3>What to watch</h3>
            <ul className="bullets">{b.watch_items.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </div>
        )}
      </div>
      <Sources sources={data.sources} scope="brief" title="Filing excerpts used" />
    </div>
  );
}
