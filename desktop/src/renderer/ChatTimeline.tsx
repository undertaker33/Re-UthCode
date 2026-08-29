import type { ElementType, ReactNode } from "react";
import type { TimelineEntry, TodoItem } from "./state";

export interface ChatTimelineProps {
  entries: TimelineEntry[];
  todo: TodoItem[];
  notice?: string | null;
}

function safeHref(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:" || url.protocol === "mailto:") return url.toString();
  } catch {
    // An invalid or local URL is deliberately rendered as plain text.
  }
  return null;
}

export function renderInline(source: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\[[^\]]+\]\(([^)\s]+)\)|`[^`]*`|\*\*[^*]+\*\*|\*[^*]+\*)/gu;
  let last = 0;
  let index = 0;
  for (const match of source.matchAll(pattern)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > last) nodes.push(source.slice(last, start));
    if (token.startsWith("[") && match[2]) {
      const label = token.slice(1, token.indexOf("]("));
      const href = safeHref(match[2]);
      nodes.push(href ? <a key={`link-${index}`} href={href} target="_blank" rel="noreferrer">{label}</a> : <span key={`link-${index}`} className="link-blocked">{label}</span>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(<code key={`code-${index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`strong-${index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={`em-${index}`}>{token.slice(1, -1)}</em>);
    }
    last = start + token.length;
    index += 1;
  }
  if (last < source.length) nodes.push(source.slice(last));
  return nodes;
}

function isTableDivider(line: string): boolean {
  const cells = line.trim().replace(/^\||\|$/gu, "").split("|");
  return cells.length > 0 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/u.test(cell));
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\||\|$/gu, "").split("|").map((cell) => cell.trim());
}

/** Render the deliberately small safe Markdown subset without raw HTML. */
export function renderMarkdown(source: string): ReactNode {
  const lines = source.replace(/\r\n?/gu, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;
  let blockIndex = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = line.match(/^\s*(`{3,}|~{3,})([^`]*)$/u);
    if (fence) {
      const marker = fence[1];
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !new RegExp(`^\\s*${marker[0]}{${marker.length},}\\s*$`, "u").test(lines[index] ?? "")) {
        codeLines.push(lines[index] ?? "");
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push(<pre key={`fence-${blockIndex}`}><code>{codeLines.join("\n")}</code></pre>);
      blockIndex += 1;
      continue;
    }
    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/u);
    if (heading) {
      const level = heading[1].length;
      const Heading = `h${level}` as ElementType;
      blocks.push(<Heading key={`heading-${blockIndex}`}>{renderInline(heading[2])}</Heading>);
      index += 1;
      blockIndex += 1;
      continue;
    }
    if (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1] ?? "")) {
      const header = tableCells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && (lines[index] ?? "").includes("|") && (lines[index] ?? "").trim()) {
        rows.push(tableCells(lines[index] ?? ""));
        index += 1;
      }
      blocks.push(<table key={`table-${blockIndex}`}><thead><tr>{header.map((cell, cellIndex) => <th key={`th-${cellIndex}`}>{renderInline(cell)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={`tr-${rowIndex}`}>{header.map((_cell, cellIndex) => <td key={`td-${cellIndex}`}>{renderInline(row[cellIndex] ?? "")}</td>)}</tr>)}</tbody></table>);
      blockIndex += 1;
      continue;
    }
    if (/^\s*>/u.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>/u.test(lines[index] ?? "")) {
        quote.push((lines[index] ?? "").replace(/^\s*>\s?/u, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${blockIndex}`}>{renderMarkdown(quote.join("\n"))}</blockquote>);
      blockIndex += 1;
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/u);
    const ordered = line.match(/^\s*\d+[.]\s+(.+)$/u);
    if (unordered || ordered) {
      const items: string[] = [];
      const orderedList = !!ordered;
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        const match = orderedList ? candidate.match(/^\s*\d+[.]\s+(.+)$/u) : candidate.match(/^\s*[-*+]\s+(.+)$/u);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      const List = orderedList ? "ol" : "ul";
      blocks.push(<List key={`list-${blockIndex}`}>{items.map((item, itemIndex) => <li key={`li-${itemIndex}`}>{renderInline(item)}</li>)}</List>);
      blockIndex += 1;
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && (lines[index] ?? "").trim()) {
      const next = lines[index] ?? "";
      if (/^\s*(#{1,6})\s+|^\s*(`{3,}|~{3,})|^\s*>|^\s*[-*+]\s+|^\s*\d+[.]\s+/u.test(next)) break;
      paragraph.push(next);
      index += 1;
    }
    blocks.push(<p key={`paragraph-${blockIndex}`}>{paragraph.map((part, partIndex) => <span key={`line-${partIndex}`}>{renderInline(part)}{partIndex < paragraph.length - 1 && <br />}</span>)}</p>);
    blockIndex += 1;
  }
  return blocks;
}

function entryLabel(entry: TimelineEntry): string {
  if (entry.kind === "user") return "You";
  if (entry.kind === "steering") return "Steering";
  if (entry.kind === "reasoning") return "Reasoning";
  if (entry.kind === "tool") return entry.toolName || "Tool";
  if (entry.kind === "plan") return "Plan";
  if (entry.kind === "status") return "Runtime";
  return "UthCode";
}

export function ChatTimeline({ entries, todo, notice }: ChatTimelineProps) {
  return (
    <section className="timeline" aria-label="Chat timeline">
      {notice && <p className="timeline-notice">{notice}</p>}
      {entries.length === 0 && <div className="timeline--empty"><p>Select a Session or start a new chat.</p></div>}
      {entries.map((entry) => (
        <article key={entry.id} className={`timeline-entry timeline-entry--${entry.kind}${entry.streaming ? " is-streaming" : ""}${entry.status ? ` is-${entry.status}` : ""}`}>
          <div className="timeline-entry__rail" aria-hidden="true" />
          <div className="timeline-entry__body">
            <div className="timeline-entry__meta"><span>{entryLabel(entry)}</span>{entry.kind === "tool" && <span className={`tool-state${entry.isError ? " tool-state--error" : ""}`}>{entry.status || "running"}</span>}{entry.streaming && <span>writing…</span>}</div>
            <div className="timeline-entry__content">{entry.kind === "tool" ? <p className="tool-summary">{entry.text}{entry.status === "failed" ? " · failed" : entry.status === "completed" ? " · completed" : " · running"}</p> : renderMarkdown(entry.text)}</div>
          </div>
        </article>
      ))}
      {todo.length > 0 && <section className="todo-strip" aria-label="Current tasks"><div className="timeline-entry__meta"><span>Tasks</span><span>{todo.filter((item) => item.status === "completed").length}/{todo.length}</span></div><ul>{todo.map((item, index) => <li key={`${item.content}-${index}`} className={`todo-item todo-item--${item.status}`}><span aria-hidden="true">{item.status === "completed" ? "✓" : item.status === "in_progress" ? "›" : "○"}</span>{item.content}</li>)}</ul></section>}
    </section>
  );
}
