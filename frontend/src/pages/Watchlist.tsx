import { useEffect, useMemo, useState, type ReactNode } from "react";
import { navigate } from "../router";
import { api, type AnalyticsRow, type Benchmark } from "../api";
import {
  analyticsSeries,
  benchmarkRow,
  BenchmarkSelect,
  FieldLabel,
  FlowsCard,
  fmtMetric,
  InsidersCard,
  MetricLabel,
  RangeSelect,
  ReturnsCard,
  riskReturnPoints,
  useBenchmark,
  useRange,
  windowLabel,
} from "../components/Analytics";
import { BarChart, Heatmap, LineChart, ScatterChart } from "../components/Charts";
import { MultiTickerPicker } from "../components/TickerPicker";
import { Card, ErrorBox, Kpi, Segmented, Skeleton, ToneBadge, useAsync, useStored } from "../components/ui";
import { BENCH_COLOR, deltaClass, fmtNum, fmtPct, fmtRatio, tickerColor } from "../format";
import { FIELD, fieldsIn, type FieldDef, type MetricKey } from "../metrics";

const METRIC_COLS: MetricKey[] = ["return_pct", "excess_return_pct", "ann_vol_pct", "beta", "sharpe", "max_drawdown_pct", "var95_pct"];

type Tab = "risk" | "valuation" | "growth" | "trading" | "technicals" | "ownership";
const TABS: { value: Tab; label: string; fields?: FieldDef[] }[] = [
  { value: "risk", label: "Performance & risk" },
  { value: "valuation", label: "Valuation", fields: fieldsIn("Valuation") },
  { value: "growth", label: "Growth & profitability", fields: fieldsIn("Growth & profitability") },
  { value: "trading", label: "Trading & flows", fields: fieldsIn("Trading & flows") },
  { value: "technicals", label: "Technicals & analysts", fields: fieldsIn("Technicals", "Analysts") },
  { value: "ownership", label: "Ownership & insiders", fields: fieldsIn("Ownership & insiders") },
];
// Look-through values the portfolio row can show in the field tabs.
const PORTFOLIO_FIELDS: Record<string, "pe_trailing" | "pe_forward" | "dividend_yield_pct" | "analyst_upside_pct" | "beta_5y"> = {
  pe_trailing: "pe_trailing",
  pe_forward: "pe_forward",
  dividend_yield_pct: "dividend_yield_pct",
  upside_pct: "analyst_upside_pct",
  beta_5y: "beta_5y",
};

/** Commits on blur / Enter so typing doesn't refetch on every keystroke. */
function WeightInput({ value, onCommit, label }: { value: number; onCommit: (v: number) => void; label: string }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  const commit = () => {
    const v = Number(draft);
    if (Number.isFinite(v) && v >= 0 && v !== value) onCommit(v);
    else setDraft(String(value));
  };
  return (
    <input
      className="input weight-input"
      inputMode="decimal"
      aria-label={label}
      value={draft}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

const Swatch = ({ color, line = false }: { color: string; line?: boolean }) => (
  <span style={{ display: "inline-block", width: 10, height: line ? 3 : 10, borderRadius: 3, background: color, marginRight: 8, verticalAlign: "middle" }} />
);

export default function Watchlist({ tickers, benchmarks, defaultBenchmark }: { tickers: string[]; benchmarks: Benchmark[]; defaultBenchmark: string }) {
  const [selected, setSelected] = useStored<string[]>("mp-watchlist", []);
  const [raw, setRaw] = useStored<Record<string, number>>("mp-weights", {});
  const [benchmark, setBenchmark] = useBenchmark(defaultBenchmark);
  const [range, setRange] = useRange("1Y");
  const [rf, setRf] = useStored<number>("mp-rf", 0);
  const [tab, setTab] = useStored<Tab>("mp-holdings-tab", "risk");
  const active = selected.length ? selected : tickers.slice(0, 4);
  const custom = active.some((t) => raw[t] !== undefined);
  const weights = custom ? active.map((t) => raw[t] ?? 100 / active.length) : undefined;

  const wl = useAsync(
    () => (active.length ? api.analytics(active, { benchmark, range, weights, rf }) : Promise.resolve(null)),
    [active.join(","), benchmark, range, (weights ?? []).join(","), rf],
  );
  const a = wl.data;
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 }>({ key: "weight", dir: -1 });
  const bm = a?.benchmark.symbol ?? benchmark;
  const p = a?.portfolio;
  const pm = p?.metrics;
  const pf = p?.fundamentals;
  const bmm = a?.benchmark_metrics;
  const bmRow = a ? benchmarkRow(a) : null;
  const tabDef = TABS.find((t) => t.value === tab) ?? TABS[0];

  const holdings = useMemo(() => (a?.tickers ?? []).filter((r) => r.has_data), [a]);
  const sortVal = (r: AnalyticsRow, k: string): number | string => {
    if (k === "ticker") return r.ticker;
    if (k === "weight") return p?.weights[r.ticker] ?? -Infinity;
    if (k === "risk") return p?.risk_contribution_pct?.[r.ticker] ?? -Infinity;
    if (k === "last_close") return r.last_close ?? -Infinity;
    if (k in FIELD) {
      const v = FIELD[k].get(r);
      return typeof v === "number" ? v : typeof v === "string" ? v : -Infinity;
    }
    return r.metrics?.[k as MetricKey] ?? -Infinity;
  };
  const rows = [...holdings].sort((x, y) => {
    const u = sortVal(x, sort.key);
    const v = sortVal(y, sort.key);
    return (u < v ? -1 : u > v ? 1 : 0) * sort.dir;
  });
  const missing = a?.missing ?? [];
  const maxRisk = Math.max(1, ...Object.values(p?.risk_contribution_pct ?? {}));
  const sectors = Object.entries(pf?.sectors ?? {});

  const header = (key: string, label: ReactNode, num = true) => (
    <th
      key={key}
      className={`sortable ${num ? "num" : ""}`}
      onClick={() => setSort((s) => ({ key, dir: s.key === key ? ((-s.dir) as 1 | -1) : -1 }))}
      aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
    >
      {label} {sort.key === key ? (sort.dir === 1 ? "↑" : "↓") : ""}
    </th>
  );
  const metricCell = (k: MetricKey, v: number | null | undefined, ref = false) => (
    <td key={k} className={`num ${ref ? "ref" : ""} ${!ref && (k === "return_pct" || k === "excess_return_pct") ? deltaClass(v) : ""}`}>
      {fmtMetric(k, v)}
    </td>
  );

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Portfolio view</div>
          <h1>Watchlist</h1>
          <p>
            Treat your watchlist as a portfolio: set weights, then compare it with an index on return, risk, valuation, trading activity and insider
            behaviour, see which holdings drive the risk, and look back across 10 years of yearly returns.
          </p>
        </div>
      </div>

      <Card>
        <MultiTickerPicker options={tickers} selected={active} onChange={setSelected} colorOf={tickerColor} max={10} />
        <div className="controls">
          <BenchmarkSelect benchmarks={benchmarks} value={benchmark} onChange={setBenchmark} />
          <RangeSelect value={range} onChange={setRange} />
          <label title="Annual risk-free rate used for Sharpe, Sortino and alpha (e.g. the T-bill yield).">
            Risk-free %
            <input
              className="input"
              style={{ width: 70 }}
              type="number"
              min={0}
              max={20}
              step={0.25}
              value={rf}
              onChange={(e) => setRf(Math.min(20, Math.max(0, Number(e.target.value) || 0)))}
            />
          </label>
          <span className="spacer" />
          {custom && (
            <button className="btn btn-sm" onClick={() => setRaw({})}>
              Reset to equal weight
            </button>
          )}
          <span className="small muted">{windowLabel(a)}</span>
        </div>
      </Card>
      <ErrorBox message={wl.error} />
      {missing.length > 0 && (
        <div className="alert warn">
          No stored data for {missing.join(", ")} yet - open{" "}
          {missing.map((t, i) => (
            <span key={t}>
              {i ? ", " : ""}
              <a href={`#/dashboard/${t}`}>{t}</a>
            </span>
          ))}{" "}
          on the dashboard and click "Refresh live data".
        </div>
      )}
      {a && !a.benchmark.has_data && <div className="alert warn">No price data for benchmark {bm} yet, so market-relative metrics are hidden.</div>}

      {wl.loading && !a ? (
        <Skeleton height={320} />
      ) : (
        a && (
          <>
            <div className="kpi-grid">
              <Kpi
                label="Portfolio return"
                value={fmtPct(pm?.return_pct)}
                delta={pm?.excess_return_pct ?? undefined}
                sub={pm?.excess_return_pct != null ? `vs ${bm}` : undefined}
              />
              <Kpi label="Volatility (ann.)" value={fmtPct(pm?.ann_vol_pct, 1, false)} sub={bmm ? `${bm} ${fmtPct(bmm.ann_vol_pct, 1, false)}` : undefined} />
              <Kpi label="Sharpe ratio" value={fmtRatio(pm?.sharpe)} sub={bmm ? `${bm} ${fmtRatio(bmm.sharpe)}` : undefined} />
              <Kpi label={`Beta to ${bm}`} value={fmtRatio(pm?.beta)} sub={pm?.r_squared_pct != null ? `R² ${pm.r_squared_pct.toFixed(0)}% market-driven` : undefined} />
              <Kpi label="Max drawdown" value={fmtPct(pm?.max_drawdown_pct)} sub={bmm ? `${bm} ${fmtPct(bmm.max_drawdown_pct)}` : undefined} />
              <Kpi
                label="Diversification ratio"
                value={fmtRatio(p?.diversification_ratio)}
                sub={<span title="Weighted average of the holdings' volatilities divided by the portfolio's volatility. 1.0 = no diversification benefit; higher = correlations are cancelling risk out.">1.0 = no benefit</span>}
              />
            </div>

            <div className="grid grid-main">
              <Card title="Growth of 100" subtitle={`Holdings, the weighted portfolio (bold) and ${bm} (dashed)`}>
                <LineChart height={300} baseline={100} yFormat={(v) => v.toFixed(0)} series={analyticsSeries(a, "performance", { portfolio: true })} />
              </Card>
              <Card title="Risk vs return" subtitle="Top-left is best: more return per unit of volatility">
                <ScatterChart
                  height={300}
                  points={riskReturnPoints(a, { portfolio: true })}
                  xLabel="Volatility (ann.)"
                  yLabel="Return"
                  xFormat={(v) => `${v.toFixed(0)}%`}
                  yFormat={(v) => `${v.toFixed(0)}%`}
                />
              </Card>
            </div>

            <Card
              title="Holdings"
              subtitle="Edit weights (any units - they're normalised) · switch tabs for valuation, trading and ownership detail · hover a column for its definition · click a row to open its dashboard"
            >
              <div style={{ marginBottom: 12, overflowX: "auto" }}>
                <Segmented value={tab} onChange={setTab} options={TABS.map((t) => ({ value: t.value, label: t.label }))} />
              </div>
              <div className="table-wrap" style={{ maxHeight: "none" }}>
                <table className="table">
                  <thead>
                    <tr>
                      {header("ticker", "Ticker", false)}
                      {header("weight", <span className="help" title="Target weight at the start of the window (buy-and-hold afterwards).">Weight</span>)}
                      {tab === "risk" ? (
                        <>
                          {header("risk", <span className="help" title="Share of the portfolio's variance this holding contributes. Compare with its weight: a holding whose risk share far exceeds its weight dominates the portfolio's swings.">Risk share</span>)}
                          {header("last_close", "Last close")}
                          {METRIC_COLS.map((k) => header(k, k === "excess_return_pct" ? <span className="help" title={`Return minus ${bm}'s return over the window.`}>vs {bm}</span> : <MetricLabel k={k} />))}
                          <th>Filing tone</th>
                        </>
                      ) : (
                        tabDef.fields?.map((f) => header(f.id, <FieldLabel f={f} />))
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => {
                      const risk = p?.risk_contribution_pct?.[r.ticker];
                      return (
                        <tr key={r.ticker} style={{ cursor: "pointer" }} onClick={() => navigate(`dashboard/${r.ticker}`)}>
                          <td style={{ whiteSpace: "nowrap" }}>
                            <Swatch color={tickerColor(r.ticker)} />
                            <b>{r.ticker}</b>
                          </td>
                          <td className="num">
                            <WeightInput
                              label={`Weight for ${r.ticker}`}
                              value={Math.round((raw[r.ticker] ?? 100 / active.length) * 100) / 100}
                              onCommit={(v) => setRaw({ ...Object.fromEntries(active.map((t) => [t, raw[t] ?? 100 / active.length])), [r.ticker]: v })}
                            />
                            <div className="small muted">{fmtPct(p?.weights[r.ticker], 1, false)}</div>
                          </td>
                          {tab === "risk" ? (
                            <>
                              <td className="num" style={{ whiteSpace: "nowrap" }}>
                                {risk == null ? (
                                  "—"
                                ) : (
                                  <>
                                    <span className="minibar" style={{ width: `${Math.max(2, (Math.abs(risk) / maxRisk) * 48)}px`, background: tickerColor(r.ticker) }} />
                                    {fmtPct(risk, 1, false)}
                                  </>
                                )}
                              </td>
                              <td className="num">${fmtNum(r.last_close)}</td>
                              {METRIC_COLS.map((k) => metricCell(k, r.metrics?.[k]))}
                              <td>
                                <ToneBadge tone={r.sentiment.tone} />
                              </td>
                            </>
                          ) : (
                            tabDef.fields?.map((f) => (
                              <td key={f.id} className="num" style={{ whiteSpace: "nowrap" }}>
                                {f.fmt(f.get(r))}
                              </td>
                            ))
                          )}
                        </tr>
                      );
                    })}
                    <tr style={{ fontWeight: 700 }}>
                      <td>Portfolio</td>
                      <td className="num">100%</td>
                      {tab === "risk" ? (
                        <>
                          <td className="num">100%</td>
                          <td />
                          {METRIC_COLS.map((k) => metricCell(k, pm?.[k]))}
                          <td />
                        </>
                      ) : (
                        tabDef.fields?.map((f) => {
                          const k = PORTFOLIO_FIELDS[f.id];
                          return (
                            <td key={f.id} className="num" title={k ? "Weighted look-through of the holdings" : undefined}>
                              {k && pf ? f.fmt(pf[k]) : ""}
                            </td>
                          );
                        })
                      )}
                    </tr>
                    {bmRow && (
                      <tr>
                        <td className="ref" style={{ whiteSpace: "nowrap" }}>
                          <Swatch color={BENCH_COLOR} line />
                          {bm} <span className="small">· {a.benchmark.name}</span>
                        </td>
                        <td />
                        {tab === "risk" ? (
                          <>
                            <td />
                            <td />
                            {METRIC_COLS.map((k) => metricCell(k, bmm?.[k], true))}
                            <td />
                          </>
                        ) : (
                          tabDef.fields?.map((f) => (
                            <td key={f.id} className="num ref">
                              {f.fmt(f.get(bmRow))}
                            </td>
                          ))
                        )}
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Card>

            <div className="grid grid-2">
              <Card title="Portfolio composition" subtitle={`Weighted look-through of the holdings vs ${bm}`}>
                <div className="stack">
                  <div className="mlist">
                    <div>
                      <span className="muted help" title={FIELD.pe_trailing.help}>P/E (trailing)</span>
                      <b>
                        {FIELD.pe_trailing.fmt(pf?.pe_trailing)} <span className="muted small">{bm} {FIELD.pe_trailing.fmt(bmRow?.fundamentals?.pe_trailing)}</span>
                      </b>
                    </div>
                    <div>
                      <span className="muted help" title={FIELD.pe_forward.help}>P/E (forward)</span>
                      <b>{FIELD.pe_forward.fmt(pf?.pe_forward)}</b>
                    </div>
                    <div>
                      <span className="muted help" title={FIELD.dividend_yield_pct.help}>Dividend yield</span>
                      <b>
                        {FIELD.dividend_yield_pct.fmt(pf?.dividend_yield_pct)}{" "}
                        <span className="muted small">{bm} {FIELD.dividend_yield_pct.fmt(bmRow?.fundamentals?.dividend_yield_pct)}</span>
                      </b>
                    </div>
                    <div>
                      <span className="muted help" title={FIELD.upside_pct.help}>Analyst upside</span>
                      <b className={deltaClass(pf?.analyst_upside_pct)}>{fmtPct(pf?.analyst_upside_pct)}</b>
                    </div>
                    <div>
                      <span className="muted help" title={FIELD.beta_5y.help}>Beta (5y, Yahoo)</span>
                      <b>{fmtRatio(pf?.beta_5y)}</b>
                    </div>
                    <div>
                      <span className="muted">Avg filing sentiment</span>
                      <b>{p?.avg_net_sentiment == null ? "—" : p.avg_net_sentiment.toFixed(2)}</b>
                    </div>
                  </div>
                  <div className="small muted" style={{ marginTop: 6 }}>
                    Sector allocation
                  </div>
                  {sectors.map(([s, w]) => (
                    <div key={s} className="row" style={{ flexWrap: "nowrap" }}>
                      <span style={{ width: 150 }} className="small">
                        {s}
                      </span>
                      <div className="splitbar" style={{ flex: 1 }}>
                        <div style={{ width: `${w}%`, background: "var(--s3)" }} />
                      </div>
                      <span className="small" style={{ width: 52, textAlign: "right" }}>
                        {fmtPct(w, 1, false)}
                      </span>
                    </div>
                  ))}
                </div>
              </Card>
              <Card title="Where the risk comes from" subtitle="Each holding's weight vs its share of portfolio variance">
                <BarChart
                  height={260}
                  categories={holdings.map((r) => r.ticker)}
                  series={[
                    { name: "Weight", color: "var(--brand-1)", values: holdings.map((r) => p?.weights[r.ticker] ?? NaN) },
                    { name: "Risk share", color: "var(--s3)", values: holdings.map((r) => p?.risk_contribution_pct?.[r.ticker] ?? NaN) },
                  ]}
                  yFormat={(v) => `${v.toFixed(0)}%`}
                />
              </Card>
            </div>

            <FlowsCard a={a} rows={holdings} />
            <InsidersCard rows={holdings} />

            <div className="grid grid-2">
              <Card title="Return correlation" subtitle={`Daily returns over the window, including ${bm}`}>
                <Heatmap labels={a.correlation.tickers} matrix={a.correlation.matrix} />
              </Card>
              <Card title={`Rolling beta to ${bm}`} subtitle={`Trailing ${a.series.rolling_window}-day beta: how market sensitivity changes over time`}>
                {Object.keys(a.series.rolling_beta).length ? (
                  <LineChart height={260} baseline={1} yFormat={(v) => v.toFixed(1)} series={analyticsSeries(a, "rolling_beta", { benchmark: false })} />
                ) : (
                  <div className="empty">Pick a longer range (3M or more) to see rolling beta.</div>
                )}
              </Card>
            </div>

            <Card title="Drawdowns" subtitle="% below each series' running peak">
              <LineChart height={260} yFormat={(v) => `${v.toFixed(0)}%`} series={analyticsSeries(a, "drawdown", { portfolio: true })} />
            </Card>

            <ReturnsCard a={a} order={["Portfolio", ...holdings.map((r) => r.ticker), bm]} />
          </>
        )
      )}
    </div>
  );
}
