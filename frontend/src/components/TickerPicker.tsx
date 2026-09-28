import { useState } from "react";

const SYMBOL_RE = /^[A-Z][A-Z.-]{0,9}$/;

/** Row of ticker chips plus an "add symbol" input. */
export function TickerPicker({
  options,
  value,
  onChange,
  onAdd,
  colorOf,
}: {
  options: string[];
  value: string;
  onChange: (t: string) => void;
  onAdd?: (t: string) => void;
  colorOf?: (t: string) => string | undefined;
}) {
  const [draft, setDraft] = useState("");
  const submit = () => {
    const t = draft.trim().toUpperCase();
    if (!SYMBOL_RE.test(t)) return;
    setDraft("");
    onAdd ? onAdd(t) : onChange(t);
  };
  return (
    <div className="row">
      {options.map((t) => (
        <button key={t} className={`chip ${t === value ? "active" : ""}`} onClick={() => onChange(t)} aria-pressed={t === value}>
          {colorOf?.(t) && <span className="swatch" style={{ background: colorOf(t) }} />}
          {t}
        </button>
      ))}
      {onAdd && (
        <form
          className="row"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <input
            className="input"
            style={{ width: 110, height: 30 }}
            placeholder="+ Add ticker"
            aria-label="Add ticker symbol"
            value={draft}
            maxLength={10}
            onChange={(e) => setDraft(e.target.value.toUpperCase())}
          />
        </form>
      )}
    </div>
  );
}

export function MultiTickerPicker({
  options,
  selected,
  onChange,
  colorOf,
  max = 6,
}: {
  options: string[];
  selected: string[];
  onChange: (ts: string[]) => void;
  colorOf: (t: string) => string;
  max?: number;
}) {
  const [draft, setDraft] = useState("");
  const all = Array.from(new Set([...options, ...selected]));
  const toggle = (t: string) => {
    if (selected.includes(t)) onChange(selected.filter((x) => x !== t));
    else if (selected.length < max) onChange([...selected, t]);
  };
  return (
    <div className="row">
      {all.map((t) => (
        <button key={t} className={`chip ${selected.includes(t) ? "active" : ""}`} onClick={() => toggle(t)} aria-pressed={selected.includes(t)}>
          {selected.includes(t) && <span className="swatch" style={{ background: colorOf(t) }} />}
          {t}
        </button>
      ))}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = draft.trim().toUpperCase();
          if (SYMBOL_RE.test(t) && !selected.includes(t) && selected.length < max) onChange([...selected, t]);
          setDraft("");
        }}
      >
        <input
          className="input"
          style={{ width: 110, height: 30 }}
          placeholder="+ Add ticker"
          aria-label="Add ticker to watchlist"
          value={draft}
          maxLength={10}
          onChange={(e) => setDraft(e.target.value.toUpperCase())}
        />
      </form>
      <span className="small muted">
        {selected.length}/{max} selected
      </span>
    </div>
  );
}
