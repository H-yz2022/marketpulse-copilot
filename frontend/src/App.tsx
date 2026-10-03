import { useEffect, useState, type ReactNode } from "react";
import { api, type Benchmark, type Health, type Usage } from "./api";
import { registerTickers } from "./format";
import Agent from "./pages/Agent";
import Compare from "./pages/Compare";
import Dashboard from "./pages/Dashboard";
import Explorer from "./pages/Explorer";
import Markets from "./pages/Markets";
import Watchlist from "./pages/Watchlist";

// Hash routing (#/dashboard/AAPL) keeps deployment trivial: the backend serves
// one static index.html and never needs SPA rewrite rules.
function useHashRoute(): string[] {
  const parse = () => (window.location.hash.replace(/^#\/?/, "") || "dashboard").split("/");
  const [parts, setParts] = useState(parse);
  useEffect(() => {
    const on = () => setParts(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

const Icon = ({ d }: { d: string }) => (
  <svg className="nav-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={d} />
  </svg>
);

const NAV: { key: string; label: string; icon: string; tag?: string }[] = [
  { key: "dashboard", label: "Dashboard", icon: "M3 3v18h18M7 15l4-4 3 3 6-6" },
  { key: "agent", label: "Analyst Agent", icon: "M12 3l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z", tag: "AI" },
  { key: "explorer", label: "Data Explorer", icon: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3", tag: "AI" },
  { key: "compare", label: "Compare", icon: "M8 3v18M16 3v18M3 8h5M16 16h5" },
  { key: "watchlist", label: "Watchlist", icon: "M4 6h16M4 12h16M4 18h10" },
  { key: "markets", label: "Markets", icon: "M3 21h18M6 17V9M11 17V5M16 17v-6M21 17V8" },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<string | null>(() => {
    try {
      return localStorage.getItem("mp-theme");
    } catch {
      return null;
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.setAttribute("data-theme", theme);
    else document.documentElement.removeAttribute("data-theme");
  }, [theme]);
  const isDark = theme === "dark" || (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  const flip = () => {
    const next = isDark ? "light" : "dark";
    setTheme(next);
    try {
      localStorage.setItem("mp-theme", next);
    } catch {
      /* ignore */
    }
  };
  return (
    <button className="btn btn-ghost btn-sm" onClick={flip} aria-label="Toggle colour theme">
      {isDark ? "☀ Light mode" : "☾ Dark mode"}
    </button>
  );
}

export default function App() {
  const [page, ...rest] = useHashRoute();
  const [health, setHealth] = useState<Health | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [defaultBenchmark, setDefaultBenchmark] = useState("SPY");

  const refreshMeta = () => {
    api.health().then(setHealth).catch(() => setHealth(null));
    api.usage().then(setUsage).catch(() => setUsage(null));
    api
      .tickers()
      .then((t) => {
        registerTickers(t.all);
        setTickers(t.all);
        setBenchmarks(t.benchmarks ?? []);
        if (t.default_benchmark) setDefaultBenchmark(t.default_benchmark);
      })
      .catch(() => undefined);
  };
  useEffect(refreshMeta, []);

  let content: ReactNode;
  switch (page) {
    case "agent":
      content = <Agent tickers={tickers} onUsage={refreshMeta} />;
      break;
    case "explorer":
      content = <Explorer onUsage={refreshMeta} />;
      break;
    case "compare":
      content = <Compare tickers={tickers} benchmarks={benchmarks} defaultBenchmark={defaultBenchmark} initial={rest} onUsage={refreshMeta} />;
      break;
    case "watchlist":
      content = <Watchlist tickers={tickers} benchmarks={benchmarks} defaultBenchmark={defaultBenchmark} />;
      break;
    case "markets":
      content = <Markets tickers={tickers} benchmarks={benchmarks} defaultBenchmark={defaultBenchmark} />;
      break;
    default:
      content = (
        <Dashboard
          tickers={tickers}
          benchmarks={benchmarks}
          defaultBenchmark={defaultBenchmark}
          ticker={(rest[0] || tickers[0] || "AAPL").toUpperCase()}
          onMeta={refreshMeta}
        />
      );
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/dashboard" style={{ textDecoration: "none", color: "inherit" }}>
          <span className="brand-mark">
            <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
              <path d="M3 18h6l3-9 5 15 3-9 2 3h7" fill="none" stroke="#0B3D40" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span>
            <div className="brand-name">MarketPulse</div>
            <div className="brand-sub">Copilot · market analytics</div>
          </span>
        </a>
        <nav className="nav" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.key} href={`#/${n.key}`} className={page === n.key || (n.key === "dashboard" && !NAV.some((x) => x.key === page)) ? "active" : ""}>
              <Icon d={n.icon} />
              <span className="nav-label">{n.label}</span>
              {n.tag && <span className="nav-tag">{n.tag}</span>}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="status-pill" title={health ? `API v${health.version}` : "API unreachable"}>
            <span className={`dot ${health?.ai_enabled ? "on" : "off"}`} />
            <span>
              {health ? (health.ai_enabled ? <>AI on · <code>{health.model}</code></> : "AI off · no API key") : "Connecting…"}
              {usage && usage.ai_enabled && (
                <div className="muted">
                  {usage.client_used}/{usage.client_limit} AI requests today
                </div>
              )}
            </span>
          </div>
          <ThemeToggle />
          <a className="small muted" href="https://github.com/H-yz2022/marketpulse-copilot" target="_blank" rel="noreferrer">
            Source on GitHub ↗
          </a>
        </div>
      </aside>
      <main className="main">{content}</main>
    </div>
  );
}
