import type { Source } from "../api";
import { fmtDate } from "../format";

export function sourceKey(s: Source): string {
  return s.id ?? String(s.n ?? "");
}

/** Scroll to and briefly highlight the source card for a citation id. */
export function focusSource(scope: string, id: string) {
  const el = document.getElementById(`src-${scope}-${id}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  el.classList.remove("flash");
  void el.offsetWidth; // restart the animation
  el.classList.add("flash");
}

export function Sources({ sources, scope, title = "Sources" }: { sources: Source[]; scope: string; title?: string }) {
  if (!sources.length) return null;
  return (
    <div className="stack">
      <h3>{title}</h3>
      {sources.map((s) => {
        const key = sourceKey(s);
        return (
          <div className="source" id={`src-${scope}-${key}`} key={key}>
            <div className="source-h">
              <span className="cite" aria-hidden>
                {key}
              </span>
              <b>{s.ticker}</b>
              <span className="muted">
                {s.form_type} {s.filed_date ? `· filed ${fmtDate(s.filed_date, true)}` : ""}
              </span>
              {s.matched_by?.map((m) => (
                <span key={m} className="badge outline">
                  {m === "bm25" ? "keyword (BM25)" : "semantic (dense)"}
                </span>
              ))}
              {s.url && (
                <a href={s.url} target="_blank" rel="noreferrer" className="small" style={{ marginLeft: "auto" }}>
                  SEC filing ↗
                </a>
              )}
            </div>
            <p>{s.text}</p>
          </div>
        );
      })}
    </div>
  );
}
