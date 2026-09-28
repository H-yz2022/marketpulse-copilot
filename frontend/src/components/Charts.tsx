// Dependency-free SVG charts: line/area with crosshair tooltip, grouped bars with
// per-bar tooltip, and a diverging correlation heatmap. Single y-axis only,
// thin marks, recessive grid, legend for >= 2 series + direct end labels (<= 4).
import { useMemo, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { fmtDate } from "../format";
import { useWidth } from "./ui";

export interface LineSeries {
  name: string;
  color: string;
  points: { x: string; y: number }[];
}

const M = { top: 12, right: 56, bottom: 26, left: 52 };

function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const span = max - min;
  const step0 = span / Math.max(1, count - 1);
  const mag = Math.pow(10, Math.floor(Math.log10(step0)));
  const err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}

function isDateLike(s: string) {
  return /^\d{4}-\d{2}-\d{2}/.test(s);
}

export function LineChart({
  series,
  height = 280,
  area = false,
  yFormat = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
  baseline,
}: {
  series: LineSeries[];
  height?: number;
  area?: boolean;
  yFormat?: (v: number) => string;
  baseline?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const xs = useMemo(() => {
    const set = new Set<string>();
    series.forEach((s) => s.points.forEach((p) => set.add(p.x)));
    return Array.from(set).sort();
  }, [series]);
  const lookup = useMemo(() => series.map((s) => new Map(s.points.map((p) => [p.x, p.y]))), [series]);

  const allY = series.flatMap((s) => s.points.map((p) => p.y));
  if (baseline !== undefined) allY.push(baseline);
  const yMin = Math.min(...allY);
  const yMax = Math.max(...allY);
  const ticks = niceTicks(yMin, yMax);
  const lo = ticks[0] ?? yMin;
  const hi = ticks[ticks.length - 1] ?? yMax;
  const directLabels = series.length >= 2 && series.length <= 4;
  const right = directLabels ? M.right + 8 : 16;
  const iw = Math.max(10, width - M.left - right);
  const ih = height - M.top - M.bottom;
  const x = (i: number) => M.left + (xs.length <= 1 ? iw / 2 : (i / (xs.length - 1)) * iw);
  const y = (v: number) => M.top + ih - ((v - lo) / (hi - lo || 1)) * ih;

  const xTickIdx = useMemo(() => {
    const n = Math.min(6, xs.length, Math.max(2, Math.floor(iw / 90)));
    if (n <= 1) return [0];
    return Array.from({ length: n }, (_, k) => Math.round((k / (n - 1)) * (xs.length - 1)));
  }, [xs.length, iw]);

  // Direct end-labels: nudge apart so they never overlap (min 14px vertical gap).
  const labelY = new Map<string, number>();
  if (directLabels) {
    const ends = series
      .map((s, si) => {
        const last = [...xs].reverse().find((xv) => lookup[si].has(xv));
        return { name: s.name, y: last === undefined ? NaN : y(lookup[si].get(last) as number) };
      })
      .filter((e) => Number.isFinite(e.y))
      .sort((a, b) => a.y - b.y);
    for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 14);
    ends.forEach((e) => labelY.set(e.name, e.y));
  }

  if (!series.length || !xs.length) return <div className="empty">No data to chart yet.</div>;

  const onMove = (e: ReactMouseEvent<SVGRectElement>) => {
    const rect = (e.currentTarget as SVGRectElement).getBoundingClientRect();
    const px = e.clientX - rect.left;
    const i = Math.round((px / rect.width) * (xs.length - 1));
    setHover(Math.max(0, Math.min(xs.length - 1, i)));
  };

  const hx = hover !== null ? x(hover) : 0;
  const tipLeft = hover !== null ? Math.min(Math.max(hx + 12, 0), Math.max(0, width - 180)) : 0;

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Line chart of ${series.map((s) => s.name).join(", ")}`}>
          <defs>
            <linearGradient id="areaFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--area-top)" />
              <stop offset="100%" stopColor="var(--area-bottom)" />
            </linearGradient>
          </defs>
          <g className="axis">
            {ticks.map((t) => (
              <g key={t}>
                <line className="gridline" x1={M.left} x2={M.left + iw} y1={y(t)} y2={y(t)} />
                <text x={M.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {xTickIdx.map((i) => (
              <text key={i} x={x(i)} y={height - 6} textAnchor={i === 0 ? "start" : i === xs.length - 1 ? "end" : "middle"}>
                {isDateLike(xs[i]) ? fmtDate(xs[i]) : xs[i]}
              </text>
            ))}
          </g>
          {baseline !== undefined && <line className="baseline" x1={M.left} x2={M.left + iw} y1={y(baseline)} y2={y(baseline)} strokeDasharray="4 4" />}
          {series.map((s, si) => {
            const pts = xs.map((xv, i) => [i, lookup[si].get(xv)] as const).filter((p): p is readonly [number, number] => p[1] !== undefined);
            if (!pts.length) return null;
            const d = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
            const last = pts[pts.length - 1];
            return (
              <g key={s.name}>
                {area && series.length === 1 && (
                  <path d={`${d}L${x(last[0]).toFixed(1)},${M.top + ih}L${x(pts[0][0]).toFixed(1)},${M.top + ih}Z`} fill="url(#areaFill)" />
                )}
                <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
                {directLabels && (
                  <text className="dlabel" x={x(last[0]) + 6} y={labelY.get(s.name) ?? y(last[1])} dominantBaseline="middle">
                    {s.name}
                  </text>
                )}
              </g>
            );
          })}
          {hover !== null && (
            <g>
              <line className="crosshair" x1={hx} x2={hx} y1={M.top} y2={M.top + ih} />
              {series.map((s, si) => {
                const v = lookup[si].get(xs[hover]);
                return v === undefined ? null : (
                  <circle key={s.name} cx={hx} cy={y(v)} r={4.5} fill={s.color} stroke="var(--surface)" strokeWidth={2} />
                );
              })}
            </g>
          )}
          <rect
            x={M.left}
            y={M.top}
            width={iw}
            height={ih}
            fill="transparent"
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </svg>
      )}
      {hover !== null && (
        <div className="tooltip" style={{ left: tipLeft, top: M.top }}>
          <div className="tt-title">{isDateLike(xs[hover]) ? fmtDate(xs[hover], true) : xs[hover]}</div>
          {series.map((s, si) => {
            const v = lookup[si].get(xs[hover]);
            return (
              <div className="tt-row" key={s.name}>
                <i style={{ width: 10, height: 3, background: s.color, borderRadius: 2 }} />
                {s.name}
                <b>{v === undefined ? "—" : yFormat(v)}</b>
              </div>
            );
          })}
        </div>
      )}
      {series.length >= 2 && <Legend items={series.map((s) => ({ name: s.name, color: s.color }))} />}
    </div>
  );
}

export function Legend({ items }: { items: { name: string; color: string }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.name}>
          <i style={{ background: i.color }} />
          {i.name}
        </span>
      ))}
    </div>
  );
}

export interface BarSeries {
  name: string;
  color: string;
  values: number[];
}

export function BarChart({
  categories,
  series,
  height = 240,
  yFormat = (v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
  compactX = false,
}: {
  categories: string[];
  series: BarSeries[];
  height?: number;
  yFormat?: (v: number) => string;
  compactX?: boolean;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<{ c: number; s: number } | null>(null);
  if (!categories.length || !series.length) return <div className="empty">No data to chart yet.</div>;

  const vals = series.flatMap((s) => s.values).filter(Number.isFinite);
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(0, ...vals));
  const lo = ticks[0];
  const hi = ticks[ticks.length - 1];
  const iw = Math.max(10, width - M.left - 16);
  const ih = height - M.top - M.bottom;
  const band = iw / categories.length;
  const gap = 2; // surface gap between adjacent bars
  const groupW = Math.min(band * 0.72, 18 * series.length + gap * (series.length - 1) + 20);
  const barW = Math.max(2, (groupW - gap * (series.length - 1)) / series.length);
  const y = (v: number) => M.top + ih - ((v - lo) / (hi - lo || 1)) * ih;
  const zero = y(0);
  const labelEvery = compactX ? Math.ceil(categories.length / 8) : Math.ceil(categories.length / Math.max(1, Math.floor(iw / 70)));

  return (
    <div className="chart" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Bar chart">
          <g className="axis">
            {ticks.map((t) => (
              <g key={t}>
                <line className="gridline" x1={M.left} x2={M.left + iw} y1={y(t)} y2={y(t)} />
                <text x={M.left - 8} y={y(t)} textAnchor="end" dominantBaseline="middle">
                  {yFormat(t)}
                </text>
              </g>
            ))}
            {categories.map((c, ci) =>
              ci % labelEvery === 0 ? (
                <text key={c + ci} x={M.left + band * ci + band / 2} y={height - 6} textAnchor="middle">
                  {isDateLike(c) ? fmtDate(c) : c.length > 12 ? c.slice(0, 11) + "…" : c}
                </text>
              ) : null,
            )}
          </g>
          {categories.map((c, ci) =>
            series.map((s, si) => {
              const v = s.values[ci];
              if (!Number.isFinite(v)) return null;
              const x0 = M.left + band * ci + (band - groupW) / 2 + si * (barW + gap);
              const top = Math.min(y(v), zero);
              const h = Math.max(1, Math.abs(y(v) - zero));
              const r = Math.min(4, barW / 2, h);
              // Rounded data-end only (away from the baseline).
              const d =
                v >= 0
                  ? `M${x0},${zero}V${top + r}Q${x0},${top} ${x0 + r},${top}H${x0 + barW - r}Q${x0 + barW},${top} ${x0 + barW},${top + r}V${zero}Z`
                  : `M${x0},${zero}V${top + h - r}Q${x0},${top + h} ${x0 + r},${top + h}H${x0 + barW - r}Q${x0 + barW},${top + h} ${x0 + barW},${top + h - r}V${zero}Z`;
              const on = hover && hover.c === ci && hover.s === si;
              return (
                <g key={`${c}-${s.name}`} onMouseEnter={() => setHover({ c: ci, s: si })} onMouseLeave={() => setHover(null)}>
                  <rect x={x0 - 2} y={M.top} width={barW + 4} height={ih} fill="transparent" />
                  <path d={d} fill={s.color} opacity={hover && !on ? 0.55 : 1} />
                </g>
              );
            }),
          )}
          <line className="baseline" x1={M.left} x2={M.left + iw} y1={zero} y2={zero} />
        </svg>
      )}
      {hover && (
        <div
          className="tooltip"
          style={{ left: Math.min(M.left + band * hover.c + band / 2 + 8, Math.max(0, width - 180)), top: 4 }}
        >
          <div className="tt-title">{categories[hover.c]}</div>
          {series.map((s) => (
            <div className="tt-row" key={s.name}>
              <i style={{ width: 10, height: 10, background: s.color, borderRadius: 3 }} />
              {s.name}
              <b>{Number.isFinite(s.values[hover.c]) ? yFormat(s.values[hover.c]) : "—"}</b>
            </div>
          ))}
        </div>
      )}
      {series.length >= 2 && <Legend items={series.map((s) => ({ name: s.name, color: s.color }))} />}
    </div>
  );
}

/** Diverging heatmap for correlations in [-1, 1]: coral <- gray -> teal. */
export function Heatmap({ labels, matrix }: { labels: string[]; matrix: (number | null)[][] }) {
  const color = (v: number | null): string => {
    if (v === null) return "var(--surface-2)";
    const a = Math.min(1, Math.abs(v));
    const hue = v >= 0 ? "0, 151, 167" : "224, 96, 47";
    return `rgba(${hue}, ${0.12 + a * 0.78})`;
  };
  const ink = (v: number | null) => (v !== null && Math.abs(v) > 0.55 ? "#ffffff" : "var(--ink)");
  if (!labels.length) return <div className="empty">Add at least two tickers with data.</div>;
  return (
    <div>
      <div className="table-wrap" style={{ border: "none", maxHeight: "none" }}>
        <table className="table heat" style={{ width: "auto" }}>
          <thead>
            <tr>
              <th />
              {labels.map((l) => (
                <th key={l} style={{ textAlign: "center" }}>
                  {l}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((row, i) => (
              <tr key={row}>
                <th>{row}</th>
                {labels.map((col, j) => {
                  const v = matrix[i]?.[j] ?? null;
                  return (
                    <td key={col} className="cell" style={{ background: color(v), color: ink(v) }} title={`${row} vs ${col}: ${v ?? "n/a"}`}>
                      {v === null ? "—" : v.toFixed(2)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend">
        <span>
          <i style={{ background: "rgba(224, 96, 47, .9)" }} /> −1 moves opposite
        </span>
        <span>
          <i style={{ background: "rgba(128,128,128,.35)" }} /> 0 unrelated
        </span>
        <span>
          <i style={{ background: "rgba(0, 151, 167, .9)" }} /> +1 moves together
        </span>
      </div>
    </div>
  );
}

export function ChartFrame({ children, caption }: { children: ReactNode; caption?: ReactNode }) {
  return (
    <figure style={{ margin: 0 }}>
      {children}
      {caption && <figcaption className="small muted" style={{ marginTop: 6 }}>{caption}</figcaption>}
    </figure>
  );
}
