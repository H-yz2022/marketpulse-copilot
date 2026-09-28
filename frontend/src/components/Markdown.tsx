// A tiny, safe markdown renderer (no dangerouslySetInnerHTML): paragraphs, headings,
// bullet / numbered lists, pipe tables, **bold**, *italic*, `code`, and citation
// chips for [F3] / [2] that scroll to the matching source card.
import type { ReactNode } from "react";

type CiteHandler = (id: string) => void;

function inline(text: string, onCite?: CiteHandler, keyBase = ""): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*|\[(?:F?\d+)\](?:\[(?:F?\d+)\])*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${k++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("[")) {
      const ids = tok.match(/F?\d+/g) ?? [];
      ids.forEach((id, i) =>
        out.push(
          <button type="button" key={`${key}-${i}`} className="cite" onClick={() => onCite?.(id)} title={`Show source ${id}`}>
            {id}
          </button>,
        ),
      );
    } else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text, onCite }: { text: string; onCite?: CiteHandler }) {
  const lines = (text || "").replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let b = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const level = Math.min(3, h[1].length);
      const content = inline(h[2], onCite, `h${b}`);
      blocks.push(level === 1 ? <h1 key={b++}>{content}</h1> : level === 2 ? <h2 key={b++}>{content}</h2> : <h3 key={b++}>{content}</h3>);
      i++;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        const cells = lines[i].trim().slice(1, -1).split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={b++} style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>{head.map((c, j) => <th key={j}>{inline(c, onCite, `th${b}${j}`)}</th>)}</tr>
            </thead>
            <tbody>
              {body.map((r, ri) => (
                <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, onCite, `td${b}${ri}${j}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const lis = items.map((it, j) => <li key={j}>{inline(it, onCite, `li${b}${j}`)}</li>);
      blocks.push(ordered ? <ol key={b++}>{lis}</ol> : <ul key={b++}>{lis}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*\||\s*([-*•]|\d+[.)])\s+)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={b++}>{inline(para.join(" "), onCite, `p${b}`)}</p>);
  }
  return <div className="md">{blocks}</div>;
}
