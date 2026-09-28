import { useMemo, useState } from "react";
import { navigate } from "../router";
import { api, type WatchlistRow } from "../api";
import { Heatmap, LineChart } from "../components/Charts";
import { MultiTickerPicker } from "../components/TickerPicker";
import { Card, ErrorBox, Kpi, Skeleton, ToneBadge, useAsync, useStored } from "../components/ui";
import { deltaClass, fmtNum, fmtPct, tickerColor } from "../format";

type SortKey = "ticker" | "last_close" | "return_period_pct" | "return_1m_pct" | "volatility_ann_pct" | "max_drawdown_pct" | "sentiment";

const COLS: { key: SortKey; label: string }[] = [
  { key: "ticker", label: "Ticker" },
  { key: "last_close", label: "Last close" },
  { key: "return_1m_pct", label: "1M" },
  { key: "return_period_pct", label: "Period" },
  { key: "volatility_ann_pct", label: "Volatility" },
  { key: "max_drawdown_pct", label: "Max DD" },
  { key: "sentiment", label: "Net sentiment" },
];

function sortVal(r: WatchlistRow, k: SortKey): number | string {
  if (k === "ticker") return r.ticker;
  if (k === "sentiment") return r.sentiment.net_index ?? -Infinity;
  const v = r[k];
  return typeof v === "number" ? v : -Infinity;
}

export default function Watchlist({ tickers }: { tickers: string[] }) {
  const [selected, setSelected] = useStored<string[]>("mp-watchlist", []);
  const active = selected.length ? selected : tickers.slice(0, 4);
  const wl = useAsync(() => (active.length ? api.watchlist(active) : Promise.resolve(null)), [active.join(",")]);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "return_period_pct", dir: -1 });

  const rows = useMemo(() => {
    const rs = [...(wl.data?.tickers ?? [])];
    rs.sort((x, y) => {
      const a = sortVal(x, sort.key);
      const b = sortVal(y, sort.key);
      return (a < b ? -1 : a > b ? 1 : 0) * sort.dir;
    });
    return rs;
  }, [wl.data, sort]);
  const p = wl.data?.portfolio;
  const missing = (wl.data?.tickers ?? []).filter((r) => !r.has_data).map((r) => r.ticker);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Portfolio view</div>
          <h1>Watchlist</h1>
          <p>Aggregate performance, risk and filing sentiment across up to six companies, plus how their daily returns move together.</p>
        </div>
      </div>

      <Card>
        <MultiTickerPicker options={tickers} selected={active} onChange={setSelected} colorOf={tickerColor} />
      </Card>
      <ErrorBox message={wl.error} />
      {missing.length > 0 && (
        <div className="alert warn">
          No stored data for {missing.join(", ")} yet - open {missing.map((t, i) => (
            <span key={t}>
              {i ? ", " : ""}
              <a href={`#/dashboard/${t}`}>{t}</a>
            </span>
          ))} on the dashboard and click "Refresh live data".
        </div>
      )}

      {wl.loading && !wl.data ? (
        <Skeleton height={320} />
      ) : (
        wl.data && (
          <>
            <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
              <Kpi label="Equal-weight return" value={fmtPct(p?.equal_weight_return_pct)} />
              <Kpi label="Average net sentiment" value={p?.avg_net_sentiment === null || p?.avg_net_sentiment === undefined ? "—" : p.avg_net_sentiment.toFixed(2)} />
              <Kpi label="Best performer" value={p?.best ?? "—"} />
              <Kpi label="Worst performer" value={p?.worst ?? "—"} />
            </div>
            <div className="grid grid-main">
              <Card title="Performance, rebased to 100">
                <LineChart
                  height={300}
                  baseline={100}
                  yFormat={(v) => v.toFixed(0)}
                  series={Object.entries(wl.data.performance).map(([t, pts]) => ({ name: t, color: tickerColor(t), points: pts.map((q) => ({ x: q.date, y: q.value })) }))}
                />
              </Card>
              <Card title="Return correlation" subtitle="Pearson correlation of daily returns on common trading days">
                <Heatmap labels={wl.data.correlation.tickers} matrix={wl.data.correlation.matrix} />
              </Card>
            </div>
            <Card title="Holdings" subtitle="Click a column to sort · click a ticker to open its dashboard">
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      {COLS.map((c) => (
                        <th
                          key={c.key}
                          className={`sortable ${c.key === "ticker" ? "" : "num"}`}
                          onClick={() => setSort((s) => ({ key: c.key, dir: s.key === c.key ? ((-s.dir) as 1 | -1) : -1 }))}
                          aria-sort={sort.key === c.key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
                        >
                          {c.label} {sort.key === c.key ? (sort.dir === 1 ? "↑" : "↓") : ""}
                        </th>
                      ))}
                      <th>Tone</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.ticker} style={{ cursor: "pointer" }} onClick={() => navigate(`dashboard/${r.ticker}`)}>
                        <td>
                          <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: tickerColor(r.ticker), marginRight: 8 }} />
                          <b>{r.ticker}</b>
                        </td>
                        <td className="num">{r.has_data ? `$${fmtNum(r.last_close)}` : "—"}</td>
                        <td className={`num ${deltaClass(r.return_1m_pct)}`}>{fmtPct(r.return_1m_pct)}</td>
                        <td className={`num ${deltaClass(r.return_period_pct)}`}>{fmtPct(r.return_period_pct)}</td>
                        <td className="num">{fmtPct(r.volatility_ann_pct, 1, false)}</td>
                        <td className="num">{fmtPct(r.max_drawdown_pct)}</td>
                        <td className="num">{r.sentiment.net_index === null ? "—" : r.sentiment.net_index.toFixed(2)}</td>
                        <td>
                          <ToneBadge tone={r.sentiment.tone} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </>
        )
      )}
    </div>
  );
}
