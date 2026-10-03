// One definition per analytics metric: label, plain-English help (shown as a
// tooltip), formatting, and which direction is "better" for highlighting.
import type { AnalyticsRow, Metrics } from "./api";
import { fmtCompact, fmtNum, fmtPct, fmtRatio } from "./format";

export type MetricKey = keyof Metrics;
export type Better = "high" | "low" | null;

export interface MetricDef {
  key: MetricKey;
  label: string;
  group: "Return" | "Risk" | "Risk-adjusted" | "Versus the market";
  help: string;
  better: Better;
  fmt: (v: number | null | undefined) => string;
}

const pct = (v: number | null | undefined) => fmtPct(v);
const pctAbs = (v: number | null | undefined) => fmtPct(v, 1, false);
const ratio = (v: number | null | undefined) => fmtRatio(v);

export const METRICS: MetricDef[] = [
  { key: "return_pct", label: "Period return", group: "Return", better: "high", fmt: pct, help: "Total price return over the selected window (adjusted for dividends and splits)." },
  { key: "ann_return_pct", label: "Annualised return", group: "Return", better: "high", fmt: pct, help: "The period return scaled to a one-year pace (compounded). Noisy for short windows." },
  { key: "excess_return_pct", label: "Excess vs benchmark", group: "Return", better: "high", fmt: pct, help: "Period return minus the benchmark's period return. Positive = beat the market." },
  { key: "pct_up_days", label: "Up days", group: "Return", better: "high", fmt: pctAbs, help: "Share of trading days that closed higher." },
  { key: "ann_vol_pct", label: "Volatility (ann.)", group: "Risk", better: "low", fmt: pctAbs, help: "Annualised standard deviation of daily returns: how much the price typically swings." },
  { key: "downside_dev_pct", label: "Downside deviation", group: "Risk", better: "low", fmt: pctAbs, help: "Volatility counting only days below the risk-free rate - the 'bad' swings." },
  { key: "max_drawdown_pct", label: "Max drawdown", group: "Risk", better: "high", fmt: pct, help: "Largest peak-to-trough fall within the window." },
  { key: "var95_pct", label: "VaR 95% (1 day)", group: "Risk", better: "high", fmt: pct, help: "Historical Value at Risk: on 19 of 20 days the loss was no worse than this." },
  { key: "cvar95_pct", label: "CVaR 95% (1 day)", group: "Risk", better: "high", fmt: pct, help: "Expected shortfall: the average loss on the worst 5% of days." },
  { key: "worst_day_pct", label: "Worst day", group: "Risk", better: "high", fmt: pct, help: "Largest single-day fall in the window." },
  { key: "sharpe", label: "Sharpe ratio", group: "Risk-adjusted", better: "high", fmt: ratio, help: "Annualised return above the risk-free rate per unit of volatility. Above 1 is good." },
  { key: "sortino", label: "Sortino ratio", group: "Risk-adjusted", better: "high", fmt: ratio, help: "Like Sharpe, but only penalises downside volatility." },
  { key: "calmar", label: "Calmar ratio", group: "Risk-adjusted", better: "high", fmt: ratio, help: "Annualised return divided by the maximum drawdown." },
  { key: "info_ratio", label: "Information ratio", group: "Risk-adjusted", better: "high", fmt: ratio, help: "Annualised excess return over the benchmark per unit of tracking error: how consistently it beat the market." },
  { key: "beta", label: "Beta", group: "Versus the market", better: null, fmt: ratio, help: "Systematic risk: the typical % move for a 1% move in the benchmark. 1 = moves with the market, >1 amplifies it, <1 dampens it." },
  { key: "correlation", label: "Correlation", group: "Versus the market", better: null, fmt: ratio, help: "How closely daily returns move with the benchmark, from -1 to +1." },
  { key: "r_squared_pct", label: "R² (market-driven)", group: "Versus the market", better: null, fmt: pctAbs, help: "Share of the stock's daily variance explained by the market (systematic risk). The rest is company-specific." },
  { key: "idio_vol_pct", label: "Idiosyncratic vol", group: "Versus the market", better: null, fmt: pctAbs, help: "Annualised volatility left after removing the market's influence: company-specific, diversifiable risk." },
  { key: "alpha_pct", label: "Alpha (ann.)", group: "Versus the market", better: "high", fmt: pct, help: "Jensen's alpha: annualised return beyond what its beta to the market would predict." },
  { key: "tracking_error_pct", label: "Tracking error", group: "Versus the market", better: null, fmt: pctAbs, help: "Annualised volatility of the return difference versus the benchmark." },
  { key: "up_capture_pct", label: "Up capture", group: "Versus the market", better: "high", fmt: pctAbs, help: "Average gain on days the market rose, as % of the market's gain. 120% = gained 1.2x as much." },
  { key: "down_capture_pct", label: "Down capture", group: "Versus the market", better: "low", fmt: pctAbs, help: "Average move on days the market fell, as % of the market's fall. Under 100% = fell less than the market." },
];

export const METRIC: Record<string, MetricDef> = Object.fromEntries(METRICS.map((m) => [m.key, m]));

export const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "MAX"] as const;

/** Index of the best value in a row (null when there's no direction or too few values). */
export function bestIndex(values: (number | null | undefined)[], better: Better): number | null {
  if (!better) return null;
  let best: number | null = null;
  values.forEach((v, i) => {
    if (v === null || v === undefined) return;
    const b = best === null ? null : values[best];
    if (b === null || b === undefined || (better === "high" ? v > b : v < b)) best = i;
  });
  return values.filter((v) => v !== null && v !== undefined).length > 1 ? best : null;
}

/** Plain-English read of beta / R² for one ticker against its benchmark. */
export function marketRead(t: string, bench: string, m: Metrics | undefined): string | null {
  if (!m || m.beta === null || m.beta === undefined) return null;
  const b = m.beta;
  const sens = b > 1.15 ? "amplifies" : b < 0.85 ? "dampens" : "roughly tracks";
  const r2 = m.r_squared_pct ?? null;
  const share = r2 === null ? "" : ` About ${Math.round(r2)}% of its daily variance is market-driven (systematic); the other ${Math.round(100 - r2)}% is company-specific.`;
  const excess = m.excess_return_pct;
  const perf = excess === null || excess === undefined ? "" : ` It ${excess >= 0 ? "outperformed" : "underperformed"} ${bench} by ${Math.abs(excess).toFixed(1)} points over the window.`;
  return `${t} ${sens} the market: a 1% move in ${bench} has typically come with a ${b.toFixed(2)}% move in ${t}.${share}${perf}`;
}

// ---------------------------------------------------------------- per-ticker detail fields
// Fundamentals, trading activity, technicals and ownership, read off an analytics row.

export type FieldGroup = "Valuation" | "Growth & profitability" | "Trading & flows" | "Technicals" | "Analysts" | "Ownership & insiders" | "Fund";
type Val = number | string | null | undefined;

export interface FieldDef {
  id: string;
  label: string;
  group: FieldGroup;
  help: string;
  better: Better;
  get: (r: AnalyticsRow) => Val;
  fmt: (v: Val) => string;
}

const num = (v: Val): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const money = (v: Val) => (num(v) === null ? "—" : `$${fmtCompact(num(v))}`);
const count = (v: Val) => (num(v) === null ? "—" : fmtCompact(num(v)));
const times = (v: Val) => (num(v) === null ? "—" : `${fmtRatio(num(v), 1)}x`);
const p1 = (v: Val) => fmtPct(num(v));
const pAbs = (v: Val) => fmtPct(num(v), 1, false);
const r2 = (v: Val) => fmtRatio(num(v));
const text = (v: Val) => (v === null || v === undefined || v === "" ? "—" : String(v).replace(/_/g, " "));
const signedMoney = (v: Val) => {
  const n = num(v);
  return n === null ? "—" : `${n < 0 ? "-" : "+"}$${fmtCompact(Math.abs(n))}`;
};

function upside(r: AnalyticsRow): number | null {
  const t = r.fundamentals?.target_mean;
  return t && r.last_close ? (t / r.last_close - 1) * 100 : null;
}

function shortChange(r: AnalyticsRow): number | null {
  const f = r.fundamentals;
  return f?.shares_short && f.shares_short_prior_month ? (f.shares_short / f.shares_short_prior_month - 1) * 100 : null;
}

export const FIELDS: FieldDef[] = [
  // Valuation
  { id: "market_cap", label: "Market cap", group: "Valuation", better: null, get: (r) => r.fundamentals?.market_cap, fmt: money, help: "Share price x shares outstanding: the price tag for the whole company." },
  { id: "pe_trailing", label: "P/E (trailing)", group: "Valuation", better: "low", get: (r) => r.fundamentals?.pe_trailing, fmt: times, help: "Price / last 12 months of earnings per share. Lower = cheaper per dollar of profit." },
  { id: "pe_forward", label: "P/E (forward)", group: "Valuation", better: "low", get: (r) => r.fundamentals?.pe_forward, fmt: times, help: "Price / analysts' expected earnings for the next 12 months." },
  { id: "peg", label: "PEG", group: "Valuation", better: "low", get: (r) => r.fundamentals?.peg, fmt: r2, help: "P/E divided by expected earnings growth. Around 1 = growth roughly priced in." },
  { id: "price_to_sales", label: "Price / sales", group: "Valuation", better: "low", get: (r) => r.fundamentals?.price_to_sales, fmt: times, help: "Market cap / last 12 months of revenue." },
  { id: "price_to_book", label: "Price / book", group: "Valuation", better: "low", get: (r) => r.fundamentals?.price_to_book, fmt: times, help: "Price / accounting book value per share. Most useful for banks and asset-heavy firms." },
  { id: "ev_ebitda", label: "EV / EBITDA", group: "Valuation", better: "low", get: (r) => r.fundamentals?.enterprise_to_ebitda, fmt: times, help: "Enterprise value (incl. debt, minus cash) / operating cash earnings. Neutral to how the company is financed." },
  { id: "dividend_yield_pct", label: "Dividend yield", group: "Valuation", better: "high", get: (r) => r.fundamentals?.dividend_yield_pct, fmt: pAbs, help: "Annual dividends as % of the share price." },
  { id: "payout_ratio_pct", label: "Payout ratio", group: "Valuation", better: null, get: (r) => r.fundamentals?.payout_ratio_pct, fmt: pAbs, help: "Share of earnings paid out as dividends." },
  // Growth & profitability
  { id: "revenue", label: "Revenue (TTM)", group: "Growth & profitability", better: null, get: (r) => r.fundamentals?.revenue, fmt: money, help: "Sales over the last 12 months." },
  { id: "revenue_growth_pct", label: "Revenue growth", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.revenue_growth_pct, fmt: p1, help: "Latest quarter's revenue vs the same quarter a year earlier." },
  { id: "earnings_growth_pct", label: "Earnings growth", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.earnings_growth_pct, fmt: p1, help: "Latest quarter's earnings vs the same quarter a year earlier." },
  { id: "gross_margin_pct", label: "Gross margin", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.gross_margin_pct, fmt: pAbs, help: "Revenue left after the direct cost of goods sold." },
  { id: "operating_margin_pct", label: "Operating margin", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.operating_margin_pct, fmt: pAbs, help: "Revenue left after all operating costs." },
  { id: "profit_margin_pct", label: "Net margin", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.profit_margin_pct, fmt: pAbs, help: "Net income as % of revenue." },
  { id: "roe_pct", label: "Return on equity", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.roe_pct, fmt: pAbs, help: "Net income / shareholders' equity. Very high values can reflect buybacks shrinking equity." },
  { id: "free_cash_flow", label: "Free cash flow", group: "Growth & profitability", better: "high", get: (r) => r.fundamentals?.free_cash_flow, fmt: money, help: "Operating cash flow minus capital spending, last 12 months." },
  { id: "debt_to_equity", label: "Debt / equity", group: "Growth & profitability", better: "low", get: (r) => r.fundamentals?.debt_to_equity, fmt: r2, help: "Total debt / shareholders' equity. Higher = more leverage." },
  // Trading & flows
  { id: "avg_dollar_volume", label: "Avg $ volume (3m)", group: "Trading & flows", better: "high", get: (r) => r.activity?.avg_dollar_volume, fmt: money, help: "Average value traded per day over the last 3 months of the window: liquidity." },
  { id: "avg_volume", label: "Avg volume (3m)", group: "Trading & flows", better: null, get: (r) => r.activity?.avg_volume, fmt: count, help: "Average shares traded per day over the last 3 months of the window." },
  { id: "rel_volume", label: "Relative volume", group: "Trading & flows", better: null, get: (r) => r.activity?.rel_volume, fmt: times, help: "Last day's volume vs its 50-day average. Above 1.5x = unusual activity." },
  { id: "volume_trend_pct", label: "Volume trend", group: "Trading & flows", better: null, get: (r) => r.activity?.volume_trend_pct, fmt: p1, help: "Last 20 days' average volume vs the 3-month average." },
  { id: "up_volume_pct", label: "Buy-side volume", group: "Trading & flows", better: "high", get: (r) => r.activity?.up_volume_pct, fmt: pAbs, help: "Share of volume traded on up-close days over the window: a proxy for buying vs selling pressure (exchanges don't publish who initiated each trade). Above 50% = buyers dominated." },
  { id: "cmf_window", label: "Money flow (window)", group: "Trading & flows", better: "high", get: (r) => r.activity?.cmf_window, fmt: r2, help: "Chaikin Money Flow over the window: volume weighted by where each close sits in its day's range. Positive = accumulation (buying), negative = distribution (selling)." },
  { id: "cmf_20", label: "Money flow (20d)", group: "Trading & flows", better: "high", get: (r) => r.activity?.cmf_20, fmt: r2, help: "Chaikin Money Flow over the latest 20 trading days." },
  { id: "turnover_pct", label: "Daily turnover", group: "Trading & flows", better: null, get: (r) => r.activity?.turnover_pct, fmt: (v) => fmtPct(num(v), 2, false), help: "Average daily volume as % of the float: how actively the shares change hands." },
  { id: "short_pct_float", label: "Short interest", group: "Trading & flows", better: "low", get: (r) => r.fundamentals?.short_pct_float, fmt: pAbs, help: "Shares sold short as % of the float: bets on a decline." },
  { id: "short_change_pct", label: "Short change (1m)", group: "Trading & flows", better: "low", get: shortChange, fmt: p1, help: "Change in shares sold short vs the prior month's report." },
  { id: "short_ratio_days", label: "Days to cover", group: "Trading & flows", better: "low", get: (r) => r.fundamentals?.short_ratio_days, fmt: (v) => (num(v) === null ? "—" : fmtNum(num(v), 1)), help: "Shares short / average daily volume: days of normal trading needed for shorts to buy back." },
  // Technicals
  { id: "from_high_pct", label: "From 52w high", group: "Technicals", better: "high", get: (r) => r.technicals?.from_high_pct, fmt: p1, help: "How far the last close is below the 52-week high." },
  { id: "range_52w_pos_pct", label: "52w range position", group: "Technicals", better: null, get: (r) => r.technicals?.range_52w_pos_pct, fmt: pAbs, help: "Where the last close sits between the 52-week low (0%) and high (100%)." },
  { id: "sma50_gap_pct", label: "vs 50-day avg", group: "Technicals", better: null, get: (r) => r.technicals?.sma50_gap_pct, fmt: p1, help: "Last close vs its 50-day moving average. Positive = short-term uptrend." },
  { id: "sma200_gap_pct", label: "vs 200-day avg", group: "Technicals", better: null, get: (r) => r.technicals?.sma200_gap_pct, fmt: p1, help: "Last close vs its 200-day moving average: the classic long-term trend line." },
  { id: "rsi14", label: "RSI (14)", group: "Technicals", better: null, get: (r) => r.technicals?.rsi14, fmt: (v) => (num(v) === null ? "—" : fmtNum(num(v), 0)), help: "Relative Strength Index: momentum from 0-100. Above 70 is often called overbought, below 30 oversold." },
  { id: "beta_5y", label: "Beta (5y, Yahoo)", group: "Technicals", better: null, get: (r) => r.fundamentals?.beta_5y, fmt: r2, help: "Yahoo's 5-year monthly beta vs the S&P 500, for reference next to the window beta." },
  // Analysts
  { id: "target_mean", label: "Analyst target", group: "Analysts", better: null, get: (r) => r.fundamentals?.target_mean, fmt: (v) => (num(v) === null ? "—" : `$${fmtNum(num(v))}`), help: "Average 12-month price target across covering analysts." },
  { id: "upside_pct", label: "Upside to target", group: "Analysts", better: "high", get: upside, fmt: p1, help: "Average analyst target vs the last close in the window." },
  { id: "recommendation", label: "Consensus", group: "Analysts", better: null, get: (r) => r.fundamentals?.recommendation, fmt: text, help: "Analyst consensus rating (strong buy / buy / hold / sell)." },
  { id: "analyst_count", label: "Analysts", group: "Analysts", better: null, get: (r) => r.fundamentals?.analyst_count, fmt: (v) => (num(v) === null ? "—" : String(num(v))), help: "Number of analysts in the consensus." },
  // Ownership & insiders
  { id: "institution_pct", label: "Institutions own", group: "Ownership & insiders", better: null, get: (r) => r.fundamentals?.institution_pct, fmt: pAbs, help: "Share of stock held by funds, pensions and other institutions." },
  { id: "insider_pct", label: "Insiders own", group: "Ownership & insiders", better: null, get: (r) => r.fundamentals?.insider_pct, fmt: pAbs, help: "Share of stock held by officers, directors and 10% owners." },
  { id: "insider_buy", label: "Insider buys (12m)", group: "Ownership & insiders", better: "high", get: (r) => r.fundamentals?.insider?.buy_value, fmt: money, help: "Value of open-market purchases by insiders reported on Form 4 over the last 12 months." },
  { id: "insider_sell", label: "Insider sells (12m)", group: "Ownership & insiders", better: "low", get: (r) => r.fundamentals?.insider?.sell_value, fmt: money, help: "Value of open-market sales by insiders over the last 12 months. Routine for executives paid in stock; clusters can be a signal." },
  { id: "insider_net", label: "Net insider (12m)", group: "Ownership & insiders", better: "high", get: (r) => r.fundamentals?.insider?.net_value, fmt: signedMoney, help: "Insider buys minus sells over the last 12 months." },
  // Funds (index ETFs)
  { id: "total_assets", label: "Fund assets", group: "Fund", better: null, get: (r) => r.fundamentals?.total_assets, fmt: money, help: "Total assets under management in the ETF." },
  { id: "expense_ratio_pct", label: "Expense ratio", group: "Fund", better: "low", get: (r) => r.fundamentals?.expense_ratio_pct, fmt: (v) => fmtPct(num(v), 2, false), help: "Annual fund fee as % of assets." },
];

export const FIELD: Record<string, FieldDef> = Object.fromEntries(FIELDS.map((f) => [f.id, f]));

export function fieldsIn(...groups: FieldGroup[]): FieldDef[] {
  return FIELDS.filter((f) => groups.includes(f.group));
}

/** Like bestIndex, for fields that may hold text. */
export function bestFieldIndex(values: Val[], better: Better): number | null {
  return bestIndex(values.map((v) => (typeof v === "number" ? v : null)), better);
}
