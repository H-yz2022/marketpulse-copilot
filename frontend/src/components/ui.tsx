import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { ApiError } from "../api";
import { deltaClass, fmtPct } from "../format";

/** Run an async loader and track loading / error / data. Re-runs when deps change. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fn()
      .then((d) => alive && setData(d))
      .catch((e: unknown) => alive && setError(errMsg(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/** Wrap a user-triggered async action (button click) with busy/error state. */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<T | null>(null);
  const run = useCallback(
    async (...args: A) => {
      setBusy(true);
      setError(null);
      try {
        const r = await fn(...args);
        setResult(r);
        return r;
      } catch (e) {
        setError(errMsg(e));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [fn],
  );
  return { run, busy, error, result, setResult };
}

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 429) return `Limit reached: ${e.message}`;
    if (e.status === 503) return e.message;
    return `${e.message} (HTTP ${e.status})`;
  }
  return e instanceof Error ? e.message : String(e);
}

/** Observe an element's width so SVG charts can render at true pixel size. */
export function useWidth<T extends HTMLElement>(): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => setW(Math.floor(entries[0].contentRect.width)));
    ro.observe(el);
    setW(Math.floor(el.getBoundingClientRect().width));
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** localStorage-backed state, wrapped in try/catch (private mode, blocked storage). */
export function useStored<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (nv: T) => {
      setV(nv);
      try {
        localStorage.setItem(key, JSON.stringify(nv));
      } catch {
        /* storage unavailable: keep in memory only */
      }
    },
    [key],
  );
  return [v, set];
}

export function Card({ title, subtitle, actions, children, className = "" }: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-h">
          <div>
            {title && <h2>{title}</h2>}
            {subtitle && <p>{subtitle}</p>}
          </div>
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Spinner() {
  return <span className="spinner" role="status" aria-label="Loading" />;
}

export function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="alert err" role="alert">
      <span aria-hidden>⚠</span>
      <span>{message}</span>
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} />;
}

export function Kpi({ label, value, delta, sub }: { label: string; value: ReactNode; delta?: number | null; sub?: ReactNode }) {
  return (
    <div className="card kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {(delta !== undefined || sub) && (
        <div className={`kpi-sub ${deltaClass(delta)}`}>
          {delta !== undefined && delta !== null && <span aria-hidden>{delta > 0 ? "▲" : delta < 0 ? "▼" : "•"}</span>}
          {delta !== undefined && <span>{fmtPct(delta)}</span>}
          {sub && <span className="muted">{sub}</span>}
        </div>
      )}
    </div>
  );
}

export function ToneBadge({ tone }: { tone: string }) {
  const cls = tone === "positive" ? "pos" : tone === "negative" ? "neg" : "neu";
  const icon = tone === "positive" ? "▲" : tone === "negative" ? "▼" : "●";
  return (
    <span className={`badge ${cls}`}>
      <span aria-hidden>{icon}</span>
      {tone}
    </span>
  );
}

export function Segmented<T extends string>({ options, value, onChange }: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={o.value === value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}
