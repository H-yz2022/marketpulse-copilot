import { navigate } from "../router";
import { api, type Benchmark } from "../api";
import { analyticsSeries, BenchmarkSelect, FieldLabel, fmtMetric, MetricLabel, RangeSelect, ReturnsCard, useBenchmark, useRange, windowLabel } from "../components/Analytics";
import { BarChart, Heatmap, LineChart } from "../components/Charts";
import { Card, ErrorBox, Kpi, Skeleton, useAsync } from "../components/ui";
import { deltaClass, fmtPct, tickerColor } from "../format";
import { FIELD, type MetricKey } from "../metrics";

const INDEX_COLS: MetricKey[] = ["return_pct", "ann_vol_pct", "sharpe", "max_drawdown_pct", "var95_pct", "beta", "correlation"];
const FUND_FIELDS = [FIELD.expense_ratio_pct, FIELD.total_assets, FIELD.pe_trailing, FIELD.dividend_yield_pct];
const COMPANY_COLS: MetricKey[] = ["beta", "idio_vol_pct", "alpha_pct", "excess_return_pct", "up_capture_pct", "down_capture_pct"];

export default function Markets({ tickers, benchmarks, defaultBenchmark }: { tickers: string[]; benchmarks: Benchmark[]; defaultBenchmark: string }) {
  const [reference, setReference] = useBenchmark(defaultBenchmark);
  const [range, setRange] = useRange("1Y");
  const symbols = benchmarks.map((b) => b.symbol);
  const name = (s: string) => benchmarks.find((b) => b.symbol === s)?.name ?? s;

  const idx = useAsync(
    () => (symbols.length ? api.analytics(symbols, { benchmark: reference, range }) : Promise.resolve(null)),
    [symbols.join(","), reference, range],
  );
  const cos = useAsync(
    () => (tickers.length ? api.analytics(tickers.slice(0, 12), { benchmark: reference, range }) : Promise.resolve(null)),
    [tickers.join(","), reference, range],
  );
  const a = idx.data;
  const c = cos.data;
  const indexRows = (a?.tickers ?? []).filter((r) => r.has_data);
  const companyRows = (c?.tickers ?? []).filter((r) => r.has_data && r.metrics?.beta != null);
  const noData = (a?.tickers ?? []).filter((r) => !r.has_data).map((r) => r.ticker);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Market reference</div>
          <h1>Markets</h1>
          <p>
            Index ETFs as the yardstick for everything else: how the broad market, large-cap tech, small caps and sectors have done, and how much of
            each tracked company's risk is systematic (moves with the market) versus company-specific.
          </p>
        </div>
      </div>

      <Card>
        <div className="controls" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>
          <BenchmarkSelect benchmarks={benchmarks} value={reference} onChange={setReference} label="Measure beta against" />
          <RangeSelect value={range} onChange={setRange} />
          <span className="small muted">{windowLabel(a)}</span>
        </div>
      </Card>
      <ErrorBox message={idx.error || cos.error} />
      {noData.length > 0 && <div className="alert warn">No price data yet for {noData.join(", ")}.</div>}

      {idx.loading && !a ? (
        <Skeleton height={320} />
      ) : (
        a && (
          <>
            <div className="kpi-grid">
              {indexRows.slice(0, 6).map((r) => (
                <Kpi
                  key={r.ticker}
                  label={`${r.ticker} · ${name(r.ticker)}`}
                  value={<span className={deltaClass(r.metrics?.return_pct)}>{fmtPct(r.metrics?.return_pct)}</span>}
                  sub={`vol ${fmtPct(r.metrics?.ann_vol_pct, 1, false)} · ${range}`}
                />
              ))}
            </div>

            <div className="grid grid-2">
              <Card title="Index performance, growth of 100" subtitle="Total-return ETFs rebased to the start of the window">
                <LineChart height={320} baseline={100} yFormat={(v) => v.toFixed(0)} series={analyticsSeries(a, "performance", { benchmark: false, all: true })} />
              </Card>
              <Card title="How the indices move together" subtitle="Correlation of daily returns">
                <Heatmap labels={a.correlation.tickers} matrix={a.correlation.matrix} />
              </Card>
            </div>

            <Card title="Index scorecard" subtitle={`Beta and correlation measured against ${reference}`}>
              <div className="table-wrap" style={{ maxHeight: "none" }}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Index ETF</th>
                      <th>Tracks</th>
                      {INDEX_COLS.map((k) => (
                        <th key={k} className="num">
                          <MetricLabel k={k} />
                        </th>
                      ))}
                      {FUND_FIELDS.map((f) => (
                        <th key={f.id} className="num">
                          <FieldLabel f={f} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {indexRows.map((r) => (
                      <tr key={r.ticker}>
                        <td>
                          <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: tickerColor(r.ticker), marginRight: 8 }} />
                          <b>{r.ticker}</b>
                        </td>
                        <td className="muted">{name(r.ticker)}</td>
                        {INDEX_COLS.map((k) => (
                          <td key={k} className={`num ${k === "return_pct" ? deltaClass(r.metrics?.[k]) : ""}`}>
                            {fmtMetric(k, r.metrics?.[k])}
                          </td>
                        ))}
                        {FUND_FIELDS.map((f) => (
                          <td key={f.id} className="num">
                            {f.fmt(f.get(r))}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <ReturnsCard a={a} order={indexRows.map((r) => r.ticker)} />
          </>
        )
      )}

      <Card
        title="How market-driven is each company?"
        subtitle={`Systematic risk vs ${reference}: beta, and the split of each stock's daily variance into market-driven (R²) and company-specific parts`}
      >
        {cos.loading && !c ? (
          <Skeleton height={220} />
        ) : companyRows.length ? (
          <div className="stack" style={{ gap: 16 }}>
            <div className="grid grid-2">
              <div>
                <div className="small muted" style={{ marginBottom: 6 }}>
                  Beta to {reference} (1 = moves one-for-one with the market)
                </div>
                <BarChart
                  height={220}
                  categories={companyRows.map((r) => r.ticker)}
                  series={[{ name: "Beta", color: "var(--s3)", values: companyRows.map((r) => r.metrics?.beta ?? NaN) }]}
                  yFormat={(v) => v.toFixed(1)}
                />
              </div>
              <div className="stack">
                <div className="small muted">Share of daily variance</div>
                {companyRows.map((r) => {
                  const sys = Math.round(r.metrics?.r_squared_pct ?? 0);
                  return (
                    <div key={r.ticker} className="row" style={{ flexWrap: "nowrap" }}>
                      <b style={{ width: 52 }}>{r.ticker}</b>
                      <div className="splitbar" style={{ flex: 1 }} title={`${sys}% market-driven, ${100 - sys}% company-specific`}>
                        <div className="sys" style={{ width: `${sys}%` }} />
                        <div className="idio" style={{ width: `${100 - sys}%` }} />
                      </div>
                      <span className="small" style={{ width: 92, textAlign: "right" }}>
                        {sys}% / {100 - sys}%
                      </span>
                    </div>
                  );
                })}
                <div className="legend" style={{ marginTop: 0 }}>
                  <span>
                    <i style={{ background: "var(--s3)", height: 10 }} /> Market-driven (systematic)
                  </span>
                  <span>
                    <i style={{ background: "var(--brand-1)", height: 10 }} /> Company-specific (diversifiable)
                  </span>
                </div>
              </div>
            </div>
            <div className="table-wrap" style={{ maxHeight: "none" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Company</th>
                    {COMPANY_COLS.map((k) => (
                      <th key={k} className="num">
                        <MetricLabel k={k} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {companyRows.map((r) => (
                    <tr key={r.ticker} style={{ cursor: "pointer" }} onClick={() => navigate(`dashboard/${r.ticker}`)}>
                      <td>
                        <b>{r.ticker}</b>
                      </td>
                      {COMPANY_COLS.map((k) => (
                        <td key={k} className={`num ${k === "alpha_pct" || k === "excess_return_pct" ? deltaClass(r.metrics?.[k]) : ""}`}>
                          {fmtMetric(k, r.metrics?.[k])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              Systematic risk can't be diversified away - it's what you're paid (or not) for holding the market. Company-specific risk shrinks as you
              add holdings that don't move together; the watchlist's diversification ratio measures how much of it your mix cancels out.
            </p>
          </div>
        ) : (
          <div className="empty">No company data to measure yet.</div>
        )}
      </Card>
    </div>
  );
}
