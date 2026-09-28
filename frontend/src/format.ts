export const SERIES_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6"];

/** Colour follows the entity, not its rank: a ticker keeps its colour across views. */
export function seriesColor(index: number): string {
  return `var(${SERIES_VARS[index % SERIES_VARS.length]})`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined, digits = 1, signed = true): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const s = v.toFixed(digits);
  return `${signed && v > 0 ? "+" : ""}${s}%`;
}

export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function fmtDate(iso: string, withYear = false): string {
  const d = new Date(iso + (iso.length === 10 ? "T00:00:00" : ""));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, withYear ? { month: "short", day: "numeric", year: "numeric" } : { month: "short", day: "numeric" });
}

export function toneClass(label: string | null | undefined): "pos" | "neg" | "neu" {
  const l = (label ?? "").toLowerCase();
  if (l === "positive") return "pos";
  if (l === "negative") return "neg";
  return "neu";
}

export function deltaClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return "";
  return v > 0 ? "delta-pos" : "delta-neg";
}

// Colour follows the entity: the first time a ticker is seen it gets the next
// slot, and keeps it for the whole session (filters never repaint survivors).
const tickerSlots = new Map<string, number>();
export function tickerColor(t: string): string {
  if (!tickerSlots.has(t)) tickerSlots.set(t, tickerSlots.size);
  return seriesColor(tickerSlots.get(t) as number);
}
export function registerTickers(ts: string[]) {
  ts.forEach((t) => tickerColor(t));
}
