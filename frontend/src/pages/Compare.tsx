import { useEffect, useState } from "react";
import { navigate } from "../router";
import { api, type Risk } from "../api";
import { LineChart } from "../components/Charts";
import { Markdown } from "../components/Markdown";
import { Sources, focusSource } from "../components/Sources";
import { Card, ErrorBox, Skeleton, Spinner, ToneBadge, useAction, useAsync } from "../components/ui";
import { fmtNum, fmtPct, tickerColor } from "../format";

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

export default function Compare({ tickers, initialA, initialB, onUsage }: {
  tickers: string[];
  initialA?: string;
  initialB?: string;
  onUsage: () => void;
}) {
  const [a, setA] = useState((initialA || tickers[0] || "AAPL").toUpperCase());
  const [b, setB] = useState((initialB || tickers[1] || "MSFT").toUpperCase());
  useEffect(() => {
    if (!initialA && tickers.length) setA((x) => (tickers.includes(x) ? x : tickers[0]));
    if (!initialB && tickers.length > 1) setB((x) => (tickers.includes(x) && x !== tickers[0] ? x : tickers[1]));
  }, [tickers, initialA, initialB]);

  const wl = useAsync(() => api.watchlist([a, b]), [a, b]);
  const ai = useAction(async (x: string, y: string) => {
    try {
      return await api.compare(x, y);
    } finally {
      onUsage();
    }
  });
  const result = ai.result && ai.result.a === a && ai.result.b === b ? ai.result : null;
  const cite = (id: string) => focusSource("cmp", id);
  const rows = wl.data?.tickers ?? [];
  const metric = (label: string, get: (r: (typeof rows)[number]) => string) => (
    <tr>
      <td className="muted">{label}</td>
      {rows.map((r) => (
        <td key={r.ticker} className="num">
          {get(r)}
        </td>
      ))}
    </tr>
  );

  const pick = (which: "a" | "b", t: string) => {
    const na = which === "a" ? t : a;
    const nb = which === "b" ? t : b;
    navigate(`compare/${na}/${nb}`);
    which === "a" ? setA(t) : setB(t);
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Side by side</div>
          <h1>Compare companies</h1>
          <p>Rebased performance and risk metrics instantly; an AI comparison of disclosed 10-K risk factors on demand.</p>
        </div>
      </div>

      <Card>
        <div className="row">
          <select className="select" value={a} onChange={(e) => pick("a", e.target.value)} aria-label="First company">
            {tickers.map((t) => (
              <option key={t} value={t} disabled={t === b}>
                {t}
              </option>
            ))}
          </select>
          <span className="muted">vs</span>
          <select className="select" value={b} onChange={(e) => pick("b", e.target.value)} aria-label="Second company">
            {tickers.map((t) => (
              <option key={t} value={t} disabled={t === a}>
                {t}
              </option>
            ))}
          </select>
          <span className="spacer" />
          <button className="btn btn-primary" disabled={ai.busy || a === b} onClick={() => ai.run(a, b)}>
            {ai.busy ? <Spinner /> : "✦"} Compare risk factors with AI
          </button>
        </div>
      </Card>

      <ErrorBox message={wl.error} />
      <div className="grid grid-main">
        <Card title="Performance, rebased to 100" subtitle="Growth of $100 invested at the start of the stored history">
          {wl.loading && !wl.data ? (
            <Skeleton height={280} />
          ) : (
            <LineChart
              height={300}
              baseline={100}
              series={Object.entries(wl.data?.performance ?? {}).map(([t, pts]) => ({
                name: t,
                color: tickerColor(t),
                points: pts.map((p) => ({ x: p.date, y: p.value })),
              }))}
              yFormat={(v) => v.toFixed(0)}
            />
          )}
        </Card>
        <Card title="Key metrics">
          {rows.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th />
                  {rows.map((r) => (
                    <th key={r.ticker} className="num">
                      <span className="swatch" style={{ display: "inline-block", width: 10, height: 10, borderRadius: 3, background: tickerColor(r.ticker), marginRight: 6 }} />
                      {r.ticker}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metric("Last close", (r) => (r.has_data ? `$${fmtNum(r.last_close)}` : "—"))}
                {metric("Period return", (r) => fmtPct(r.return_period_pct))}
                {metric("1-month return", (r) => fmtPct(r.return_1m_pct))}
                {metric("Volatility (ann.)", (r) => fmtPct(r.volatility_ann_pct, 1, false))}
                {metric("Max drawdown", (r) => fmtPct(r.max_drawdown_pct))}
                {metric("Net sentiment", (r) => (r.sentiment.net_index === null ? "—" : r.sentiment.net_index.toFixed(2)))}
                <tr>
                  <td className="muted">Tone</td>
                  {rows.map((r) => (
                    <td key={r.ticker} className="num">
                      <ToneBadge tone={r.sentiment.tone} />
                    </td>
                  ))}
                </tr>
                {wl.data?.correlation.matrix[0]?.[1] !== undefined && (
                  <tr>
                    <td className="muted">Return correlation</td>
                    <td className="num" colSpan={2} style={{ textAlign: "center" }}>
                      {wl.data.correlation.matrix[0][1]?.toFixed(2) ?? "—"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          ) : (
            <Skeleton height={200} />
          )}
        </Card>
      </div>

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
            {result.comparison.takeaway && <div className="alert info"><b>Takeaway:</b>&nbsp;{result.comparison.takeaway}</div>}
            <Sources sources={result.sources} scope="cmp" title="Filing excerpts used" />
          </div>
        </Card>
      )}
    </div>
  );
}
