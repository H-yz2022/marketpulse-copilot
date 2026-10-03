// Building blocks shared by the analytics views (watchlist, compare, markets, dashboard).
import { Fragment } from "react";
import type { Analytics, AnalyticsRow, Benchmark, Metrics, Range, SeriesPoint } from "../api";
import { BENCH_COLOR, PORTFOLIO_COLOR, fmtCompact, fmtDate, fmtRatio, tickerColor } from "../format";
import { FIELD, METRIC, METRICS, RANGES, bestFieldIndex, bestIndex, type FieldDef, type MetricKey } from "../metrics";
import { BarChart, LineChart, ReturnsGrid, type LineSeries, type ScatterPoint } from "./Charts";
import { Card, Segmented, useStored } from "./ui";

/** The market reference the user last picked, shared across pages. */
export function useBenchmark(fallback = "SPY"): [string, (b: string) => void] {
  return useStored<string>("mp-benchmark", fallback);
}

export function useRange(fallback: Range = "1Y"): [Range, (r: Range) => void] {
  return useStored<Range>("mp-range", fallback);
}

export function BenchmarkSelect({ benchmarks, value, onChange, label = "Benchmark" }: {
  benchmarks: Benchmark[];
  value: string;
  onChange: (b: string) => void;
  label?: string;
}) {
  const known = benchmarks.some((b) => b.symbol === value);
  return (
    <label>
      {label}
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
        {!known && <option value={value}>{value}</option>}
        {benchmarks.map((b) => (
          <option key={b.symbol} value={b.symbol}>
            {b.symbol} · {b.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export function RangeSelect({ value, onChange }: { value: Range; onChange: (r: Range) => void }) {
  return <Segmented value={value} onChange={onChange} options={RANGES.map((r) => ({ value: r as Range, label: r }))} />;
}

export function MetricLabel({ k }: { k: MetricKey }) {
  const d = METRIC[k];
  return (
    <span className="help" title={d.help}>
      {d.label}
    </span>
  );
}

export function fmtMetric(k: MetricKey, v: number | null | undefined): string {
  return METRIC[k].fmt(v);
}

export interface MetricColumn {
  name: string;
  metrics?: Metrics | null;
  color?: string;
  reference?: boolean;
}

/** Rows = metrics grouped by theme, columns = series; the best non-reference value per row is highlighted. */
export function MetricsTable({ columns, keys }: { columns: MetricColumn[]; keys?: MetricKey[] }) {
  const defs = keys ? METRICS.filter((m) => keys.includes(m.key)) : METRICS;
  const groups = Array.from(new Set(defs.map((d) => d.group)));
  return (
    <div className="table-wrap" style={{ maxHeight: "none" }}>
      <table className="table">
        <thead>
          <tr>
            <th>Metric</th>
            {columns.map((c) => (
              <th key={c.name} className={`num ${c.reference ? "ref" : ""}`}>
                {c.color && <span className="swatch" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: c.color, marginRight: 6 }} />}
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <GroupRows key={g} group={g} defs={defs.filter((d) => d.group === g)} columns={columns} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function GroupRows({ group, defs, columns }: { group: string; defs: typeof METRICS; columns: MetricColumn[] }) {
  return (
    <>
      <tr className="metric-group">
        <td colSpan={columns.length + 1}>{group}</td>
      </tr>
      {defs.map((d) => {
        const values = columns.map((c) => (c.reference ? null : c.metrics?.[d.key]));
        const best = bestIndex(values, d.better);
        return (
          <tr key={d.key}>
            <td>
              <MetricLabel k={d.key} />
            </td>
            {columns.map((c, i) => (
              <td key={c.name} className={`num ${c.reference ? "ref" : ""} ${best === i ? "best" : ""}`}>
                {d.fmt(c.metrics?.[d.key])}
              </td>
            ))}
          </tr>
        );
      })}
    </>
  );
}

const toPoints = (pts: SeriesPoint[]) => pts.map((p) => ({ x: p.date, y: p.value }));

/** Line series for one of the analytics' per-ticker series, with the benchmark (and optionally the portfolio) as reference lines. */
export function analyticsSeries(
  a: Analytics,
  kind: "performance" | "drawdown" | "relative" | "rolling_beta" | "money_flow",
  {
    portfolio = false,
    benchmark = true,
    all = false,
    colorOf = tickerColor,
  }: { portfolio?: boolean; benchmark?: boolean; all?: boolean; colorOf?: (t: string) => string } = {},
): LineSeries[] {
  const bm = a.benchmark.symbol;
  const data = a.series[kind];
  // `all`: every requested ticker as a coloured line, even the one that is also the benchmark.
  const held = a.tickers.filter((r) => data[r.ticker] && (all || r.ticker !== bm));
  const out: LineSeries[] = held.map((r) => ({ name: r.ticker, color: colorOf(r.ticker), points: toPoints(data[r.ticker]) }));
  if (portfolio) {
    const p = kind === "performance" ? a.portfolio.series : kind === "drawdown" ? a.portfolio.drawdown : undefined;
    if (p?.length) out.push({ name: "Portfolio", color: PORTFOLIO_COLOR, width: 3, points: toPoints(p) });
  }
  if (benchmark && data[bm]) out.push({ name: bm, color: BENCH_COLOR, dashed: true, points: toPoints(data[bm]) });
  return out;
}

/** Risk (annualised vol) vs return points for each holding, plus portfolio and benchmark. */
export function riskReturnPoints(a: Analytics, { portfolio = false, colorOf = tickerColor }: { portfolio?: boolean; colorOf?: (t: string) => string } = {}): ScatterPoint[] {
  const bm = a.benchmark.symbol;
  const pts: ScatterPoint[] = [];
  for (const r of a.tickers) {
    const m = r.metrics;
    if (r.ticker === bm || m?.ann_vol_pct == null || m.return_pct == null) continue;
    pts.push({ name: r.ticker, x: m.ann_vol_pct, y: m.return_pct, color: colorOf(r.ticker) });
  }
  const pm = a.portfolio.metrics;
  if (portfolio && pm?.ann_vol_pct != null && pm.return_pct != null) {
    pts.push({ name: "Portfolio", x: pm.ann_vol_pct, y: pm.return_pct, color: PORTFOLIO_COLOR, kind: "portfolio" });
  }
  const bmm = a.benchmark_metrics;
  if (bmm?.ann_vol_pct != null && bmm.return_pct != null) {
    pts.push({ name: bm, x: bmm.ann_vol_pct, y: bmm.return_pct, color: BENCH_COLOR, kind: "reference" });
  }
  return pts;
}

export function windowLabel(a: Analytics | null): string {
  if (!a?.start_date || !a.end_date) return "";
  return `${a.start_date} → ${a.end_date} · ${a.n_days} trading days`;
}

// ---------------------------------------------------------------- detail fields, flows, insiders, returns

/** A pseudo-row for the benchmark so field tables can show its fund data (P/E, yield, fees) alongside holdings. */
export function benchmarkRow(a: Analytics): AnalyticsRow | null {
  if (!a.benchmark_metrics && !a.benchmark_fundamentals) return null;
  return {
    ticker: a.benchmark.symbol,
    has_data: true,
    is_benchmark: true,
    metrics: a.benchmark_metrics ?? undefined,
    fundamentals: a.benchmark_fundamentals ?? null,
    activity: a.benchmark_activity ?? undefined,
    technicals: a.benchmark_technicals ?? undefined,
    last_close: a.benchmark_last_close ?? undefined,
    sentiment: { counts: { positive: 0, negative: 0, neutral: 0 }, n: 0, net_index: null, tone: "no data" },
  };
}

export function FieldLabel({ f }: { f: FieldDef }) {
  return (
    <span className="help" title={f.help}>
      {f.label}
    </span>
  );
}

/** Fields as rows, tickers as columns (compare view); best non-reference value per row highlighted. */
export function FieldTable({ rows, fields, reference }: { rows: AnalyticsRow[]; fields: FieldDef[]; reference?: AnalyticsRow | null }) {
  const cols = reference ? [...rows, reference] : rows;
  const groups = Array.from(new Set(fields.map((f) => f.group)));
  return (
    <div className="table-wrap" style={{ maxHeight: "none" }}>
      <table className="table">
        <thead>
          <tr>
            <th>Field</th>
            {cols.map((r) => (
              <th key={r.ticker} className={`num ${r === reference ? "ref" : ""}`}>
                <span className="swatch" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: r === reference ? BENCH_COLOR : tickerColor(r.ticker), marginRight: 6 }} />
                {r.ticker}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <Fragment key={g}>
              <tr className="metric-group">
                <td colSpan={cols.length + 1}>{g}</td>
              </tr>
              {fields
                .filter((f) => f.group === g)
                .map((f) => {
                  const values = cols.map((r) => f.get(r));
                  const best = bestFieldIndex(values.map((v, i) => (cols[i] === reference ? null : v)), f.better);
                  return (
                    <tr key={f.id}>
                      <td>
                        <FieldLabel f={f} />
                      </td>
                      {cols.map((r, i) => (
                        <td key={r.ticker} className={`num ${r === reference ? "ref" : ""} ${best === i ? "best" : ""}`}>
                          {f.fmt(values[i])}
                        </td>
                      ))}
                    </tr>
                  );
                })}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Buying vs selling pressure (volume on up vs down days, money flow) and liquidity per ticker. */
export function FlowsCard({ a, rows }: { a: Analytics; rows: AnalyticsRow[] }) {
  const withFlow = rows.filter((r) => r.activity?.up_volume_pct != null);
  const flow = analyticsSeries(a, "money_flow", { benchmark: false });
  return (
    <Card
      title="Buying vs selling pressure"
      subtitle="Estimated from daily OHLCV: exchanges don't publish who started each trade, so volume on up-close vs down-close days and Chaikin Money Flow are the standard proxies"
    >
      <div className="grid grid-2">
        <div className="stack">
          <div className="small muted">Share of the window's volume traded on up days (buying) vs down days (selling)</div>
          {withFlow.map((r) => {
            const up = Math.round(r.activity?.up_volume_pct ?? 50);
            const cmf = r.activity?.cmf_window;
            return (
              <div key={r.ticker} className="row" style={{ flexWrap: "nowrap" }}>
                <b style={{ width: 52 }}>{r.ticker}</b>
                <div className="splitbar" style={{ flex: 1 }} title={`${up}% of volume on up days, ${100 - up}% on down days`}>
                  <div style={{ width: `${up}%`, background: "var(--pos)" }} />
                  <div style={{ width: `${100 - up}%`, background: "var(--neg)" }} />
                </div>
                <span className="small" style={{ width: 70, textAlign: "right" }}>
                  {up}% / {100 - up}%
                </span>
                <span className={`badge ${cmf == null ? "neu" : cmf > 0.05 ? "pos" : cmf < -0.05 ? "neg" : "neu"}`} style={{ width: 118, justifyContent: "center" }} title={FIELD.cmf_window.help}>
                  {cmf == null ? "—" : cmf > 0.05 ? "accumulation" : cmf < -0.05 ? "distribution" : "neutral"} {cmf == null ? "" : fmtRatio(cmf)}
                </span>
              </div>
            );
          })}
          <div className="legend" style={{ marginTop: 0 }}>
            <span>
              <i style={{ background: "var(--pos)", height: 10 }} /> Up-day volume (buying)
            </span>
            <span>
              <i style={{ background: "var(--neg)", height: 10 }} /> Down-day volume (selling)
            </span>
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>
            Average daily value traded, last 3 months (liquidity)
          </div>
          <BarChart
            height={170}
            categories={withFlow.map((r) => r.ticker)}
            series={[{ name: "Avg $ volume", color: "var(--s3)", values: withFlow.map((r) => r.activity?.avg_dollar_volume ?? NaN) }]}
            yFormat={(v) => `$${fmtCompact(v)}`}
          />
        </div>
        <div>
          <div className="small muted" style={{ marginBottom: 6 }}>
            20-day Chaikin Money Flow: above 0 = closes near the day&apos;s highs on volume (accumulation)
          </div>
          {flow.length ? <LineChart height={330} baseline={0} yFormat={(v) => v.toFixed(2)} series={flow} /> : <div className="empty">Pick a range of 1M or more.</div>}
        </div>
      </div>
    </Card>
  );
}

/** Reported (Form 4) open-market insider buying vs selling, plus the latest transactions. */
export function InsidersCard({ rows }: { rows: AnalyticsRow[] }) {
  const companies = rows.filter((r) => r.fundamentals?.insider);
  if (!companies.length) return null;
  const recent = companies
    .flatMap((r) => (r.fundamentals?.insider?.recent ?? []).map((t) => ({ ...t, ticker: r.ticker })))
    .filter((t) => t.type !== "other")
    .sort((x, y) => (x.date < y.date ? 1 : -1))
    .slice(0, 10);
  return (
    <Card title="Insider buying vs selling" subtitle="Open-market trades by officers and directors reported to the SEC on Form 4, last 12 months (awards and gifts excluded)">
      <div className="grid grid-2">
        <BarChart
          height={240}
          categories={companies.map((r) => r.ticker)}
          series={[
            { name: "Bought", color: "var(--pos)", values: companies.map((r) => r.fundamentals?.insider?.buy_value ?? 0) },
            { name: "Sold", color: "var(--neg)", values: companies.map((r) => r.fundamentals?.insider?.sell_value ?? 0) },
          ]}
          yFormat={(v) => `$${fmtCompact(v)}`}
        />
        <div className="table-wrap" style={{ maxHeight: 280 }}>
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Ticker</th>
                <th>Insider</th>
                <th>Type</th>
                <th className="num">Value</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((t, i) => (
                <tr key={i} title={t.text}>
                  <td style={{ whiteSpace: "nowrap" }}>{fmtDate(t.date, true)}</td>
                  <td>
                    <b>{t.ticker}</b>
                  </td>
                  <td className="small">
                    {t.insider}
                    <div className="muted">{t.position}</div>
                  </td>
                  <td>
                    <span className={`badge ${t.type === "buy" ? "pos" : "neg"}`}>{t.type === "buy" ? "Buy" : "Sell"}</span>
                  </td>
                  <td className="num">${fmtCompact(t.value)}</td>
                </tr>
              ))}
              {!recent.length && (
                <tr>
                  <td colSpan={5} className="muted">
                    No recent open-market insider trades.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

const monthLabel = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: "short", year: "2-digit" });

/** Calendar-year returns (full stored history, with CAGR) or monthly returns (within the window). */
export function ReturnsCard({ a, order }: { a: Analytics; order: string[] }) {
  const [mode, setMode] = useStored<"yearly" | "monthly">("mp-returns-mode", "yearly");
  const months = a.monthly.months.slice(-24);
  const cut = a.monthly.months.length - months.length;
  const monthlyRows = Object.fromEntries(Object.entries(a.monthly.rows).map(([k, v]) => [k, v.slice(cut)]));
  const years = a.yearly.years;
  const thisYear = years[years.length - 1];
  const first = Object.values(a.yearly.first_date).sort()[0];
  return (
    <Card
      title={mode === "yearly" ? "Yearly returns" : "Monthly returns"}
      subtitle={
        mode === "yearly"
          ? `% per calendar year over each ticker's full stored history (since ${first ? fmtDate(first, true) : "—"}; the first year is partial, ${thisYear} is year-to-date)${order.includes("Portfolio") ? " · Portfolio rebalanced to its weights each January" : ""}`
          : `% per calendar month${cut ? ", last 24 months of the window" : " within the window"} (first and last months may be partial)`
      }
      actions={
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: "yearly", label: "Yearly" },
            { value: "monthly", label: "Monthly" },
          ]}
        />
      }
    >
      {mode === "yearly" ? (
        <ReturnsGrid
          periods={years}
          rows={a.yearly.rows}
          order={order}
          labelOf={(y) => (y === thisYear ? `${y} YTD` : y)}
          scale={40}
          totalLabel={null}
          extra={{ label: "CAGR", values: a.yearly.cagr_pct }}
        />
      ) : (
        <ReturnsGrid periods={months} rows={monthlyRows} order={order} labelOf={monthLabel} />
      )}
    </Card>
  );
}
