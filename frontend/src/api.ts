// Typed client for the FastAPI backend. All paths are same-origin (/api/...);
// in dev, Vite proxies them to http://localhost:8000.

export interface PriceSummary {
  has_data: boolean;
  start_date?: string;
  end_date?: string;
  last_close?: number;
  change_1d_pct?: number | null;
  return_1m_pct?: number | null;
  return_period_pct?: number | null;
  volatility_ann_pct?: number | null;
  max_drawdown_pct?: number;
  period_high?: number;
  period_low?: number;
  avg_volume?: number;
  n_days?: number;
}

export interface SentimentSummary {
  counts: { positive: number; negative: number; neutral: number };
  n: number;
  net_index: number | null;
  tone: string;
}

export interface PriceRow {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Filing {
  filing_id: string;
  ticker: string;
  form_type: string;
  filed_date: string;
  title: string;
  url: string;
  excerpt_preview: string;
}

export interface DataStatus {
  source: "snapshot" | "live" | "unknown";
  as_of: string | null;
}

export interface Overview {
  ticker: string;
  data_status?: DataStatus;
  fundamentals?: Fundamentals | null;
  summary: PriceSummary;
  sentiment: SentimentSummary;
  prices: PriceRow[];
  sentiment_rows: { scored_date: string; label: string; score: number; source_id: string; text_snippet: string }[];
  filings: Filing[];
}

export interface Source {
  id?: string;
  n?: number;
  ticker?: string;
  form_type?: string;
  filed_date?: string;
  url?: string;
  text: string;
  matched_by?: string[];
  rrf?: number;
}

export interface Health {
  status: string;
  version: string;
  ai_enabled: boolean;
  model: string;
  tickers: string[];
}

export interface Usage {
  client_used: number;
  client_limit: number;
  global_used: number;
  global_limit: number;
  ai_enabled: boolean;
}

export interface SeriesPoint {
  date: string;
  value: number;
}

export interface WatchlistRow extends PriceSummary {
  ticker: string;
  sentiment: SentimentSummary;
}

export interface Watchlist {
  tickers: WatchlistRow[];
  performance: Record<string, SeriesPoint[]>;
  correlation: { tickers: string[]; matrix: (number | null)[][] };
  portfolio: {
    equal_weight_return_pct: number | null;
    avg_net_sentiment: number | null;
    best: string | null;
    worst: string | null;
  };
}

export interface Benchmark {
  symbol: string;
  name: string;
  has_data: boolean;
}

export type Range = "1M" | "3M" | "6M" | "YTD" | "1Y" | "3Y" | "5Y" | "MAX";

export interface InsiderTrade {
  date: string;
  insider: string;
  position: string;
  type: "buy" | "sell" | "other";
  text: string;
  shares: number;
  value: number;
}

/** Percentages in percent, money in the quote currency; null when Yahoo has no value. */
export interface Fundamentals {
  as_of: string;
  name?: string | null;
  quote_type?: string | null;
  sector?: string | null;
  industry?: string | null;
  country?: string | null;
  currency?: string | null;
  recommendation?: string | null;
  category?: string | null;
  fund_family?: string | null;
  market_cap?: number | null;
  enterprise_to_ebitda?: number | null;
  pe_trailing?: number | null;
  pe_forward?: number | null;
  peg?: number | null;
  price_to_book?: number | null;
  price_to_sales?: number | null;
  eps_trailing?: number | null;
  eps_forward?: number | null;
  dividend_yield_pct?: number | null;
  payout_ratio_pct?: number | null;
  revenue?: number | null;
  revenue_growth_pct?: number | null;
  earnings_growth_pct?: number | null;
  gross_margin_pct?: number | null;
  operating_margin_pct?: number | null;
  profit_margin_pct?: number | null;
  roe_pct?: number | null;
  roa_pct?: number | null;
  debt_to_equity?: number | null;
  current_ratio?: number | null;
  free_cash_flow?: number | null;
  shares_outstanding?: number | null;
  float_shares?: number | null;
  shares_short?: number | null;
  shares_short_prior_month?: number | null;
  short_pct_float?: number | null;
  short_ratio_days?: number | null;
  insider_pct?: number | null;
  institution_pct?: number | null;
  target_mean?: number | null;
  target_high?: number | null;
  target_low?: number | null;
  recommendation_mean?: number | null;
  analyst_count?: number | null;
  beta_5y?: number | null;
  avg_volume_3m?: number | null;
  employees?: number | null;
  total_assets?: number | null;
  expense_ratio_pct?: number | null;
  insider?: {
    window_days: number;
    buy_value: number;
    sell_value: number;
    buy_count: number;
    sell_count: number;
    net_value: number;
    recent: InsiderTrade[];
  } | null;
}

export interface Activity {
  avg_volume?: number | null;
  avg_dollar_volume?: number | null;
  last_volume?: number | null;
  rel_volume?: number | null;
  volume_trend_pct?: number | null;
  up_volume_pct?: number | null;
  cmf_20?: number | null;
  cmf_window?: number | null;
  turnover_pct?: number | null;
}

export interface Technicals {
  sma50_gap_pct?: number | null;
  sma200_gap_pct?: number | null;
  rsi14?: number | null;
  high_52w?: number | null;
  low_52w?: number | null;
  from_high_pct?: number | null;
  range_52w_pos_pct?: number | null;
}

/** Percentages are in percent; ratios are plain numbers. Market-relative fields need a benchmark. */
export interface Metrics {
  return_pct?: number | null;
  ann_return_pct?: number | null;
  ann_vol_pct?: number | null;
  downside_dev_pct?: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  max_drawdown_pct?: number | null;
  calmar?: number | null;
  var95_pct?: number | null;
  cvar95_pct?: number | null;
  best_day_pct?: number | null;
  worst_day_pct?: number | null;
  pct_up_days?: number | null;
  beta?: number | null;
  alpha_pct?: number | null;
  correlation?: number | null;
  r_squared_pct?: number | null;
  idio_vol_pct?: number | null;
  tracking_error_pct?: number | null;
  info_ratio?: number | null;
  up_capture_pct?: number | null;
  down_capture_pct?: number | null;
  excess_return_pct?: number | null;
}

export interface AnalyticsRow {
  ticker: string;
  has_data: boolean;
  is_benchmark: boolean;
  last_close?: number;
  change_1d_pct?: number | null;
  metrics?: Metrics;
  activity?: Activity;
  technicals?: Technicals;
  fundamentals?: Fundamentals | null;
  sentiment: SentimentSummary;
}

export interface Analytics {
  benchmark: Benchmark;
  range: Range;
  rf_pct: number;
  start_date: string | null;
  end_date: string | null;
  n_days: number;
  missing: string[];
  tickers: AnalyticsRow[];
  benchmark_metrics: Metrics | null;
  benchmark_fundamentals?: Fundamentals | null;
  benchmark_activity?: Activity | null;
  benchmark_technicals?: Technicals | null;
  benchmark_last_close?: number | null;
  series: {
    performance: Record<string, SeriesPoint[]>;
    drawdown: Record<string, SeriesPoint[]>;
    relative: Record<string, SeriesPoint[]>;
    rolling_beta: Record<string, SeriesPoint[]>;
    rolling_window: number;
    money_flow: Record<string, SeriesPoint[]>;
  };
  correlation: { tickers: string[]; matrix: (number | null)[][] };
  monthly: { months: string[]; rows: Record<string, (number | null)[]> };
  yearly: {
    years: string[];
    rows: Record<string, (number | null)[]>;
    cagr_pct: Record<string, number | null>;
    first_date: Record<string, string>;
  };
  portfolio: {
    weights: Record<string, number>;
    series?: SeriesPoint[];
    drawdown?: SeriesPoint[];
    metrics?: Metrics;
    risk_contribution_pct?: Record<string, number>;
    diversification_ratio?: number | null;
    fundamentals?: {
      pe_trailing: number | null;
      pe_forward: number | null;
      dividend_yield_pct: number | null;
      analyst_upside_pct: number | null;
      beta_5y: number | null;
      sectors: Record<string, number>;
    };
    best?: string | null;
    worst?: string | null;
    avg_net_sentiment?: number | null;
  };
}

export interface AnalyticsOptions {
  benchmark?: string;
  range?: Range;
  weights?: number[];
  rf?: number;
}

export interface TickerList {
  stored: string[];
  configured: string[];
  all: string[];
  benchmarks: Benchmark[];
  default_benchmark: string;
}

export interface ChartSpec {
  type: "line" | "bar" | "none";
  x: string | null;
  y: string[];
  series: string | null;
}

export interface SqlResult {
  question: string;
  sql: string;
  explanation: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  truncated: boolean;
  chart: ChartSpec;
  attempts: number;
}

export interface Risk {
  risk: string;
  detail: string;
  severity?: "high" | "medium" | "low";
}

export interface BriefResult {
  ticker: string;
  kpis: { price: PriceSummary; sentiment: SentimentSummary };
  brief: {
    headline?: string;
    summary?: string;
    bull_points?: string[];
    bear_points?: string[];
    key_risks?: Risk[];
    sentiment_read?: string;
    watch_items?: string[];
  };
  sources: Source[];
}

export interface CompareResult {
  a: string;
  b: string;
  kpis: Record<string, { price: PriceSummary; sentiment: SentimentSummary }>;
  comparison: {
    overview?: string;
    shared_risks?: Risk[];
    unique_to_a?: Risk[];
    unique_to_b?: Risk[];
    market_comparison?: string;
    takeaway?: string;
  };
  sources: Source[];
  performance: Record<string, SeriesPoint[]>;
}

export interface AskResult {
  answer: string;
  rewrite: { query: string; keywords: string[] } | null;
  sources: Source[];
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/api/health"),
  usage: () => request<Usage>("/api/usage"),
  tickers: () => request<TickerList>("/api/tickers"),
  overview: (t: string) => request<Overview>(`/api/tickers/${encodeURIComponent(t)}/overview`),
  refresh: (t: string) =>
    post<{ ticker: string; prices: number; filings: number; indexed: number; chunks: number; benchmarks_updated?: string[] }>(
      `/api/tickers/${encodeURIComponent(t)}/refresh`,
      {},
    ),
  watchlist: (ts: string[]) => request<Watchlist>(`/api/watchlist?tickers=${encodeURIComponent(ts.join(","))}`),
  analytics: (ts: string[], o: AnalyticsOptions = {}) => {
    const q = new URLSearchParams({ tickers: ts.join(",") });
    if (o.benchmark) q.set("benchmark", o.benchmark);
    if (o.range) q.set("range", o.range);
    if (o.weights) q.set("weights", o.weights.join(","));
    if (o.rf) q.set("rf", String(o.rf));
    return request<Analytics>(`/api/analytics?${q}`);
  },
  ask: (question: string, ticker?: string) => post<AskResult>("/api/ask", { question, ticker }),
  sql: (question: string) => post<SqlResult>("/api/sql", { question }),
  brief: (ticker: string) => post<BriefResult>("/api/brief", { ticker }),
  compare: (a: string, b: string) => post<CompareResult>("/api/compare", { a, b }),
};

// ---------------------------------------------------------------- agent stream (SSE over POST)
export interface PlanTask {
  id: string;
  agent: "market" | "filings" | "sql";
  goal: string;
  depends_on: string[];
}

export type AgentEvent =
  | { type: "route"; route: "direct" | "plan"; method: string; reason: string; tickers: string[] }
  | { type: "status"; message: string; task_id?: string }
  | { type: "plan"; tasks: PlanTask[] }
  | { type: "task_start"; task_id: string; agent: string; goal: string }
  | { type: "task_done"; task_id: string; status: string; summary: string }
  | { type: "tool_call"; id: string; name: string; input: Record<string, unknown>; task_id?: string }
  | { type: "tool_result"; id: string; name: string; summary: string; is_error: boolean; task_id?: string }
  | { type: "text"; text: string; task_id?: string }
  | {
      type: "verify";
      attempt: number;
      passed: boolean;
      unknown_citations: string[];
      unverified_numbers: string[];
      citations_checked: number;
    }
  | { type: "final"; answer: string; sources: Source[]; route?: string; steps?: number }
  | { type: "error"; message: string };

export type AgentMode = "auto" | "direct" | "plan";

/** POST to /api/agent and invoke `onEvent` for each Server-Sent Event. */
export async function streamAgent(
  question: string,
  history: { role: "user" | "assistant"; content: string }[],
  mode: AgentMode,
  onEvent: (e: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch("/api/agent", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, history, mode }),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, String(detail));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data: "))
        .map((l) => l.slice(6))
        .join("\n");
      if (data) onEvent(JSON.parse(data) as AgentEvent);
    }
  }
}
