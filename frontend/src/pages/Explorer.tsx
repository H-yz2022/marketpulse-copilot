import { useMemo, useState, type ReactNode } from "react";
import { api, type SqlResult } from "../api";
import { BarChart, LineChart, type BarSeries, type LineSeries } from "../components/Charts";
import { Card, ErrorBox, Spinner, useAction } from "../components/ui";
import { seriesColor, tickerColor } from "../format";

const EXAMPLES = [
  "Average closing price per ticker over the last 30 days",
  "Daily closing price of each ticker since the start of the year",
  "Which ticker had the most negative filing sentiment scores?",
  "Top 10 highest-volume trading days across all tickers",
  "Monthly average close for NVDA",
];

const KW = /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|LIMIT|WITH|AS|AND|OR|ON|JOIN|LEFT|INNER|HAVING|DESC|ASC|CASE|WHEN|THEN|ELSE|END|IN|NOT|NULL|DISTINCT|OVER|PARTITION BY|BETWEEN|LIKE)\b/gi;
const FN = /\b(AVG|SUM|COUNT|MIN|MAX|ROUND|DATE|STRFTIME|LAG|LEAD|ROW_NUMBER|ABS)\b(?=\s*\()/gi;

/** Minimal SQL highlighter that returns React nodes (no innerHTML). */
function highlight(sql: string) {
  const out: ReactNode[] = [];
  const re = new RegExp(`('(?:[^']|'')*')|${KW.source}|${FN.source}`, "gi");
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(sql)) !== null) {
    if (m.index > last) out.push(sql.slice(last, m.index));
    const cls = m[1] ? "str" : FN.test(m[0]) ? "fn" : "kw";
    FN.lastIndex = 0;
    out.push(
      <span key={k++} className={cls}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  out.push(sql.slice(last));
  return out;
}

function prettySql(sql: string) {
  return sql
    .replace(/\s+/g, " ")
    .replace(/\s(FROM|WHERE|GROUP BY|ORDER BY|LIMIT|HAVING|LEFT JOIN|JOIN|UNION ALL)\s/gi, "\n$1 ")
    .trim();
}

function ResultChart({ r }: { r: SqlResult }) {
  const { chart, columns, rows } = r;
  const data = useMemo(() => {
    if (chart.type === "none" || !chart.x) return null;
    const xi = columns.indexOf(chart.x);
    const yi = chart.y.map((y) => columns.indexOf(y));
    const si = chart.series ? columns.indexOf(chart.series) : -1;
    if (xi < 0 || yi.some((i) => i < 0)) return null;
    if (si >= 0) {
      const groups = new Map<string, { x: string; y: number }[]>();
      rows.forEach((row) => {
        const g = String(row[si]);
        const v = Number(row[yi[0]]);
        if (!Number.isFinite(v)) return;
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g)!.push({ x: String(row[xi]), y: v });
      });
      return Array.from(groups.entries())
        .slice(0, 6)
        .map(([name, points]) => ({ name, points, color: /^[A-Z.]{1,6}$/.test(name) ? tickerColor(name) : "" }));
    }
    return chart.y.map((name, k) => ({
      name,
      color: seriesColor(k),
      points: rows.map((row) => ({ x: String(row[xi]), y: Number(row[yi[k]]) })).filter((p) => Number.isFinite(p.y)),
    }));
  }, [chart, columns, rows]);

  if (!data || !data.length) return null;
  const colored = data.map((s, k) => ({ ...s, color: s.color || seriesColor(k) }));
  if (chart.type === "line") {
    return <LineChart series={colored as LineSeries[]} height={300} />;
  }
  const categories = Array.from(new Set(colored.flatMap((s) => s.points.map((p) => p.x))));
  const bars: BarSeries[] = colored.map((s) => {
    const m = new Map(s.points.map((p) => [p.x, p.y]));
    return { name: s.name, color: s.color, values: categories.map((c) => m.get(c) ?? NaN) };
  });
  return <BarChart categories={categories} series={bars} height={280} />;
}

function fmtCell(v: string | number | null) {
  if (v === null) return <span className="muted">null</span>;
  if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return v;
}

export default function Explorer({ onUsage }: { onUsage: () => void }) {
  const [q, setQ] = useState("");
  const sql = useAction(async (question: string) => {
    try {
      return await api.sql(question);
    } finally {
      onUsage();
    }
  });
  const [copied, setCopied] = useState(false);
  const r = sql.result;

  const submit = (question: string) => {
    setQ(question);
    if (question.trim().length >= 3) sql.run(question.trim());
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Natural language → SQL</div>
          <h1>Data Explorer</h1>
          <p>
            Ask a question in plain English. Claude writes a SQLite query against the research database; it runs
            behind four safety layers (static checks, read-only connection, table allow-list authorizer, time and row
            limits) and self-corrects once if SQLite reports an error.
          </p>
        </div>
      </div>

      <Card>
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            submit(q);
          }}
        >
          <input className="input" style={{ flex: 1, minWidth: 240 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Which ticker had the biggest single-day drop?" aria-label="Question" />
          <button className="btn btn-primary" disabled={sql.busy || q.trim().length < 3}>
            {sql.busy ? <Spinner /> : "Run"}
          </button>
        </form>
        <div className="row" style={{ marginTop: 10 }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} className="chip" onClick={() => submit(ex)}>
              {ex}
            </button>
          ))}
        </div>
      </Card>

      <ErrorBox message={sql.error} />

      {r && (
        <>
          <div className="grid grid-2">
            <Card
              title="Generated SQL"
              subtitle={r.explanation}
              actions={
                <>
                  {r.attempts > 1 && <span className="badge warn">self-corrected after 1 error</span>}
                  <span className="badge pos">✓ passed SQL guard</span>
                  <button
                    className="btn btn-sm"
                    onClick={() => {
                      navigator.clipboard?.writeText(r.sql).then(() => {
                        setCopied(true);
                        setTimeout(() => setCopied(false), 1200);
                      });
                    }}
                  >
                    {copied ? "Copied" : "Copy"}
                  </button>
                </>
              }
            >
              <pre className="code">{highlight(prettySql(r.sql))}</pre>
            </Card>
            <Card title="Chart" subtitle={r.chart.type === "none" ? "No chart suggested for this result" : `${r.chart.type} of ${r.chart.y.join(", ")} by ${r.chart.x}`}>
              {r.chart.type === "none" ? <div className="empty">The result is best read as a table.</div> : <ResultChart r={r} />}
            </Card>
          </div>
          <Card title="Result" subtitle={`${r.row_count} row${r.row_count === 1 ? "" : "s"}${r.truncated ? " (truncated)" : ""}`}>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {r.columns.map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {r.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((v, j) => (
                        <td key={j} className={typeof v === "number" ? "num" : ""}>
                          {fmtCell(v)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
