import { useEffect, useState } from "react";
import { navigate } from "../router";
import { api, type Benchmark, type Risk } from "../api";
import {
  analyticsSeries,
  benchmarkRow,
  BenchmarkSelect,
  FieldTable,
  FlowsCard,
  InsidersCard,
  MetricsTable,
  RangeSelect,
  ReturnsCard,
  riskReturnPoints,
  useBenchmark,
  useRange,
  windowLabel,
} from "../components/Analytics";
import { Heatmap, LineChart, ScatterChart } from "../components/Charts";
import { Markdown } from "../components/Markdown";
import { Sources, focusSource } from "../components/Sources";
import { MultiTickerPicker } from "../components/TickerPicker";
import { Card, ErrorBox, Segmented, Skeleton, Spinner, ToneBadge, useAction, useAsync, useStored } from "../components/ui";
import { BENCH_COLOR, tickerColor } from "../format";
import { fieldsIn, type FieldGroup } from "../metrics";

const DETAIL_TABS: { value: string; label: string; groups: FieldGroup[] }[] = [
  { value: "valuation", label: "Valuation", groups: ["Valuation"] },
  { value: "growth", label: "Growth & profitability", groups: ["Growth & profitability"] },
  { value: "trading", label: "Trading & flows", groups: ["Trading & flows"] },
  { value: "technicals", label: "Technicals & analysts", groups: ["Technicals", "Analysts"] },
  { value: "ownership", label: "Ownership & insiders", groups: ["Ownership & insiders"] },
];

function RiskList({ items, cite }: { items?: Risk[]; cite: (id: string) => void }) {
  if (!items?.length) return <div className="muted small">None identified.</div>;
  return (
    <div className="stack">
      {items.map((r, i) => (
        <div className="risk" key={i}>
          <b>{r.risk}</b>
          <Markdown text={r.detail} onCite={cite} />
        </div>
      ))}
    </div>
  );
}

export default function Compare({ tickers, benchmarks, defaultBenchmark, initial, onUsage }: {
  tickers: string[];
  benchmarks: Benchmark[];
  defaultBenchmark: string;
  initial: string[];
  onUsage: () => void;
}) {
  const fromUrl = initial.map((t) => t.toUpperCase()).filter(Boolean);
  const [selected, setSelected] = useState<string[]>(fromUrl.length ? fromUrl : tickers.slice(0, 3));
  useEffect(() => {
    if (!fromUrl.length && tickers.length) setSelected((s) => (s.length ? s : tickers.slice(0, 3)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tickers]);
  const [benchmark, setBenchmark] = useBenchmark(defaultBenchmark);
  const [range, setRange] = useRange("1Y");
  const [detail, setDetail] = useStored<string>("mp-compare-detail", "valuation");
  const detailTab = DETAIL_TABS.find((t) => t.value === detail) ?? DETAIL_TABS[0];

  const an = useAsync(
    () => (selected.length ? api.analytics(selected, { benchmark, range }) : Promise.resolve(null)),
    [selected.join(","), benchmark, range],
  );
  const a = an.data;
  const bm = a?.benchmark.symbol ?? benchmark;
  const pair = selected.length === 2 ? selected : null;

  const ai = useAction(async (x: string, y: string) => {
    try {
      return await api.compare(x, y);
    } finally {
      onUsage();
    }
  });
  const result = ai.result && pair && ai.result.a === pair[0] && ai.result.b === pair[1] ? ai.result : null;
  const cite = (id: string) => focusSource("cmp", id);

  const pick = (ts: string[]) => {
    setSelected(ts);
    navigate(`compare/${ts.join("/")}`);
  };
  const rows = (a?.tickers ?? []).filter((r) => r.has_data && r.ticker !== bm);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Side by side</div>
          <h1>Compare companies</h1>
          <p>
            Put up to six companies next to a market index: performance, 20+ risk and return metrics, valuation and profitability, trading activity
            and buying vs selling pressure, insider trades and yearly returns, with the best in each row highlighted. Pick exactly two for an AI
            comparison of their disclosed 10-K risk factors.
          </p>
        </div>
      </div>

      <Card>
        <MultiTickerPicker options={tickers} selected={selected} onChange={pick} colorOf={tickerColor} max={6} />
        <div className="controls">
          <BenchmarkSelect benchmarks={benchmarks} value={benchmark} onChange={setBenchmark} />
          <RangeSelect value={range} onChange={setRange} />
          <span className="small muted">{windowLabel(a)}</span>
          <span className="spacer" />
          <button
            className="btn btn-primary btn-sm"
            disabled={ai.busy || !pair}
            onClick={() => pair && ai.run(pair[0], pair[1])}
            title={pair ? undefined : "Select exactly two companies to compare their risk factors with AI"}
          >
            {ai.busy ? <Spinner /> : "✦"} {pair ? `AI risk-factor comparison: ${pair[0]} vs ${pair[1]}` : "AI comparison needs exactly 2"}
          </button>
        </div>
      </Card>

      <ErrorBox message={an.error} />
      {a && a.missing.length > 0 && <div className="alert warn">No stored data for {a.missing.join(", ")} - refresh it from its dashboard first.</div>}

      {an.loading && !a ? (
        <Skeleton height={320} />
      ) : (
        a && (
          <>
            <div className="grid grid-main">
              <Card title="Growth of 100" subtitle={`Rebased to the start of the window · ${bm} dashed`}>
                <LineChart height={300} baseline={100} yFormat={(v) => v.toFixed(0)} series={analyticsSeries(a, "performance")} />
              </Card>
              <Card title="Risk vs return" subtitle="Annualised volatility against period return">
                <ScatterChart
                  height={300}
                  points={riskReturnPoints(a)}
                  xLabel="Volatility (ann.)"
                  yLabel="Return"
                  xFormat={(v) => `${v.toFixed(0)}%`}
                  yFormat={(v) => `${v.toFixed(0)}%`}
                />
              </Card>
            </div>

            <Card title="Key metrics" subtitle="Hover a metric for its definition · green = best among the companies in that row">
              <MetricsTable
                columns={[
                  ...rows.map((r) => ({ name: r.ticker, metrics: r.metrics, color: tickerColor(r.ticker) })),
                  ...(a.benchmark_metrics ? [{ name: bm, metrics: a.benchmark_metrics, color: BENCH_COLOR, reference: true }] : []),
                ]}
              />
              <div className="row small" style={{ marginTop: 10 }}>
                <span className="muted">Filing tone:</span>
                {rows.map((r) => (
                  <span key={r.ticker} className="row" style={{ gap: 4 }}>
                    <b>{r.ticker}</b> <ToneBadge tone={r.sentiment.tone} />
                  </span>
                ))}
              </div>
            </Card>

            <Card
              title="Company detail"
              subtitle="Fundamentals, trading activity, technicals and ownership side by side · hover a field for its definition · green = best in the row"
              actions={<Segmented value={detail} onChange={setDetail} options={DETAIL_TABS.map((t) => ({ value: t.value, label: t.label }))} />}
            >
              <FieldTable rows={rows} fields={fieldsIn(...detailTab.groups)} reference={["valuation", "trading", "technicals"].includes(detailTab.value) ? benchmarkRow(a) : null} />
            </Card>

            <FlowsCard a={a} rows={rows} />

            <div className="grid grid-2">
              <Card title={`Relative strength vs ${bm}`} subtitle={`Each company's growth divided by ${bm}'s · above 100 = outperforming since the window start`}>
                <LineChart height={260} baseline={100} yFormat={(v) => v.toFixed(0)} series={analyticsSeries(a, "relative", { benchmark: false })} />
              </Card>
              <Card title={`Rolling beta to ${bm}`} subtitle={`Trailing ${a.series.rolling_window}-day beta · 1 = moves with the market`}>
                {Object.keys(a.series.rolling_beta).length ? (
                  <LineChart height={260} baseline={1} yFormat={(v) => v.toFixed(1)} series={analyticsSeries(a, "rolling_beta", { benchmark: false })} />
                ) : (
                  <div className="empty">Pick a longer range (3M or more) to see rolling beta.</div>
                )}
              </Card>
            </div>

            <div className="grid grid-2">
              <Card title="Drawdowns" subtitle="% below each series' running peak">
                <LineChart height={260} yFormat={(v) => `${v.toFixed(0)}%`} series={analyticsSeries(a, "drawdown")} />
              </Card>
              <Card title="Return correlation" subtitle="Pearson correlation of daily returns">
                <Heatmap labels={a.correlation.tickers} matrix={a.correlation.matrix} />
              </Card>
            </div>

            <InsidersCard rows={rows} />
            <ReturnsCard a={a} order={[...rows.map((r) => r.ticker), bm]} />
          </>
        )
      )}

      <ErrorBox message={ai.error} />
      {ai.busy && !result && (
        <Card>
          <div className="stack">
            <Skeleton height={20} width="50%" />
            <Skeleton height={80} />
          </div>
        </Card>
      )}
      {result && (
        <Card title={`✦ AI risk comparison: ${result.a} vs ${result.b}`} subtitle="Grounded in retrieved 10-K risk-factor excerpts; citations link to the sources below.">
          <div className="stack" style={{ gap: 16 }}>
            {result.comparison.overview && (
              <div className="card hero" style={{ boxShadow: "none" }}>
                <Markdown text={result.comparison.overview} onCite={cite} />
              </div>
            )}
            <div className="grid grid-3">
              <div className="stack">
                <h3>Shared risks</h3>
                <RiskList items={result.comparison.shared_risks} cite={cite} />
              </div>
              <div className="stack">
                <h3>
                  <span className="swatch" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: tickerColor(result.a), marginRight: 6 }} />
                  Only {result.a}
                </h3>
                <RiskList items={result.comparison.unique_to_a} cite={cite} />
              </div>
              <div className="stack">
                <h3>
                  <span className="swatch" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: tickerColor(result.b), marginRight: 6 }} />
                  Only {result.b}
                </h3>
                <RiskList items={result.comparison.unique_to_b} cite={cite} />
              </div>
            </div>
            {result.comparison.market_comparison && (
              <div>
                <h3>Market behaviour</h3>
                <Markdown text={result.comparison.market_comparison} onCite={cite} />
              </div>
            )}
            {result.comparison.takeaway && (
              <div className="alert info">
                <b>Takeaway:</b>&nbsp;{result.comparison.takeaway}
              </div>
            )}
            <Sources sources={result.sources} scope="cmp" title="Filing excerpts used" />
          </div>
        </Card>
      )}
    </div>
  );
}
