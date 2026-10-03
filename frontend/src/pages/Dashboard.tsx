import { useMemo, useState } from "react";
import { navigate } from "../router";
import { api, type Analytics, type AnalyticsRow, type AskResult, type Benchmark, type BriefResult } from "../api";
import { analyticsSeries, BenchmarkSelect, FieldLabel, fmtMetric, InsidersCard, MetricLabel, useBenchmark, windowLabel } from "../components/Analytics";
import { BarChart, LineChart } from "../components/Charts";
import { Markdown } from "../components/Markdown";
import { Sources, focusSource } from "../components/Sources";
import { TickerPicker } from "../components/TickerPicker";
import { Card, ErrorBox, Kpi, Segmented, Skeleton, Spinner, ToneBadge, useAction, useAsync } from "../components/ui";
import { deltaClass, fmtCompact, fmtDate, fmtNum, fmtPct, tickerColor, toneClass } from "../format";
import { fieldsIn, marketRead, type FieldGroup, type MetricKey } from "../metrics";

type Range = "1M" | "3M" | "6M" | "1Y" | "5Y" | "MAX";
const RANGE_DAYS: Record<Range, number> = { "1M": 22, "3M": 66, "6M": 132, "1Y": 253, "5Y": 1261, MAX: Infinity };
const MAX_BARS = 260;

/** Sum volume into equal buckets so multi-year volume charts stay readable (one bar per ~week or month). */
function bucketVolume(prices: { trade_date: string; volume: number }[]) {
  const k = Math.max(1, Math.ceil(prices.length / MAX_BARS));
  const out: { date: string; volume: number }[] = [];
  for (let i = 0; i < prices.length; i += k) {
    const chunk = prices.slice(i, i + k);
    out.push({ date: chunk[chunk.length - 1].trade_date, volume: chunk.reduce((t, p) => t + p.volume, 0) });
  }
  return { bars: out, perBar: k };
}

const MARKET_KEYS: MetricKey[] = ["beta", "correlation", "r_squared_pct", "alpha_pct", "excess_return_pct", "tracking_error_pct", "up_capture_pct", "down_capture_pct"];

export default function Dashboard({ tickers, benchmarks, defaultBenchmark, ticker, onMeta }: {
  tickers: string[];
  benchmarks: Benchmark[];
  defaultBenchmark: string;
  ticker: string;
  onMeta: () => void;
}) {
  const ov = useAsync(() => api.overview(ticker), [ticker]);
  const [range, setRange] = useState<Range>("6M");
  const [benchmark, setBenchmark] = useBenchmark(defaultBenchmark);
  const vs = useAsync(() => api.analytics([ticker], { benchmark, range }), [ticker, benchmark, range]);
  const refresh = useAction(api.refresh);
  const brief = useAction(api.brief);
  const ask = useAction(api.ask);
  const [question, setQuestion] = useState("");

  const options = useMemo(() => Array.from(new Set([...tickers, ticker])), [tickers, ticker]);
  const prices = useMemo(() => (ov.data?.prices ?? []).slice(-RANGE_DAYS[range]), [ov.data, range]);
  const volume = useMemo(() => bucketVolume(prices), [prices]);
  const s = ov.data?.summary;
  const sent = ov.data?.sentiment;
  const hasData = !!s?.has_data;
  const briefData: BriefResult | null = brief.result?.ticker === ticker ? brief.result : null;
  const askData: AskResult | null = ask.result;

  const doRefresh = async (t = ticker) => {
    const r = await refresh.run(t);
    if (r) {
      onMeta();
      if (t === ticker) {
        ov.reload();
        vs.reload();
      } else navigate(`dashboard/${t}`);
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
        <div className="stack" style={{ alignItems: "flex-end", gap: 6 }}>
          <button className="btn" onClick={() => doRefresh()} disabled={refresh.busy}>
            {refresh.busy ? <Spinner /> : "↻"} {refresh.busy ? "Fetching SEC + market data (~30s)…" : "Refresh live data"}
          </button>
          {ov.data?.data_status && ov.data.data_status.source !== "unknown" && (
            <span
              className={`badge ${ov.data.data_status.source === "live" ? "pos" : "outline"}`}
              title={
                ov.data.data_status.source === "snapshot"
                  ? "Built-in snapshot that loads instantly. Click Refresh live data for real-time prices and filings."
                  : "Fetched live from Yahoo Finance and SEC EDGAR."
              }
            >
              {ov.data.data_status.source === "live" ? "● Live data" : "Snapshot data"}
              {ov.data.data_status.as_of ? ` · ${fmtDate(ov.data.data_status.as_of.slice(0, 10), true)}` : ""}
            </span>
          )}
        </div>
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
            <Kpi label="1-year return" value={fmtPct(s?.return_period_pct)} sub={s?.start_date ? `since ${fmtDate(s.start_date)}` : undefined} />
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
                  options={(["1M", "3M", "6M", "1Y", "5Y", "MAX"] as Range[]).map((r) => ({ value: r, label: r }))}
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
                categories={volume.bars.map((b) => b.date)}
                series={[{ name: volume.perBar > 1 ? `Volume (${volume.perBar}-day sums)` : "Volume", color: "var(--brand-1)", values: volume.bars.map((b) => b.volume) }]}
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

          <MarketCard ticker={ticker} benchmarks={benchmarks} benchmark={benchmark} setBenchmark={setBenchmark} vs={vs} range={range} />
          {vs.data?.tickers[0] && <KeyStats row={vs.data.tickers[0]} range={range} />}
          {vs.data?.tickers[0]?.fundamentals?.insider && <InsidersCard rows={vs.data.tickers.slice(0, 1)} />}

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

function MarketCard({ ticker, benchmarks, benchmark, setBenchmark, vs, range }: {
  ticker: string;
  benchmarks: Benchmark[];
  benchmark: string;
  setBenchmark: (b: string) => void;
  vs: ReturnType<typeof useAsync<Analytics>>;
  range: Range;
}) {
  const a = vs.data;
  const row = a?.tickers[0];
  const m = row?.metrics;
  const bm = a?.benchmark.symbol ?? benchmark;
  const read = marketRead(ticker, bm, m);
  return (
    <Card
      title={`${ticker} versus the market`}
      subtitle={`${range} window, matching the price chart${a ? ` · ${windowLabel(a)}` : ""}`}
      actions={
        <div className="controls" style={{ margin: 0, padding: 0, border: "none" }}>
          <BenchmarkSelect benchmarks={benchmarks} value={benchmark} onChange={setBenchmark} />
        </div>
      }
    >
      <ErrorBox message={vs.error} />
      {vs.loading && !a ? (
        <Skeleton height={220} />
      ) : a && !a.benchmark.has_data ? (
        <div className="empty">No price data for {bm} yet.</div>
      ) : (
        a && (
          <div className="grid grid-main">
            <div>
              <LineChart
                height={240}
                baseline={100}
                yFormat={(v) => v.toFixed(0)}
                series={analyticsSeries(a, "performance", { colorOf: () => "var(--s1)" })}
              />
            </div>
            <div className="stack">
              <div className="row" style={{ gap: 16 }}>
                <div>
                  <div className="small muted">{ticker}</div>
                  <div className={`kpi-value ${deltaClass(m?.return_pct)}`}>{fmtPct(m?.return_pct)}</div>
                </div>
                <div>
                  <div className="small muted">{bm}</div>
                  <div className={`kpi-value ${deltaClass(a.benchmark_metrics?.return_pct)}`}>{fmtPct(a.benchmark_metrics?.return_pct)}</div>
                </div>
              </div>
              <div className="mlist">
                {MARKET_KEYS.map((k) => (
                  <div key={k}>
                    <span className="muted">
                      <MetricLabel k={k} />
                    </span>
                    <b>{fmtMetric(k, m?.[k])}</b>
                  </div>
                ))}
              </div>
              {read && <div className="read">{read}</div>}
            </div>
          </div>
        )
      )}
    </Card>
  );
}

const STAT_GROUPS: FieldGroup[] = ["Valuation", "Growth & profitability", "Trading & flows", "Technicals", "Analysts", "Ownership & insiders"];

function KeyStats({ row, range }: { row: AnalyticsRow; range: Range }) {
  const f = row.fundamentals;
  const isFund = f?.quote_type === "ETF";
  const groups: FieldGroup[] = isFund ? ["Fund", "Valuation", "Trading & flows", "Technicals"] : STAT_GROUPS;
  const about = [f?.sector, f?.industry, f?.country, f?.employees ? `${fmtCompact(f.employees)} employees` : null, f?.category, f?.fund_family]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card
      title={`Key statistics${f?.name ? ` · ${f.name}` : ""}`}
      subtitle={`${about ? `${about} · ` : ""}Fundamentals from Yahoo Finance${f?.as_of ? ` as of ${fmtDate(f.as_of, true)}` : ""} · trading activity over the ${range} window · hover a label for its definition`}
    >
      {!f && <div className="alert info">No fundamentals stored for {row.ticker} yet - "Refresh live data" fetches them.</div>}
      <div className="stats-grid">
        {groups.map((g) => (
          <div key={g}>
            <h3 style={{ marginBottom: 6 }}>{g}</h3>
            <div className="stack" style={{ gap: 0 }}>
              {fieldsIn(g).map((fd) => (
                <div key={fd.id} className="stat-row">
                  <span className="muted">
                    <FieldLabel f={fd} />
                  </span>
                  <b>{fd.fmt(fd.get(row))}</b>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
