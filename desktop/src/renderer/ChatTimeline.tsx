import { useEffect, useLayoutEffect, useRef, useState, type ElementType, type ReactNode, type UIEvent } from "react";
import type { TimelineEntry, TodoItem } from "./state";
import { useTranslation, type TranslationKey } from "./i18n";
import { UiIcon, type UiIconName } from "./UiIcon";

/** Pixels from the end that still count as being at the bottom. */
export const TIMELINE_NEAR_BOTTOM_THRESHOLD = 72;

export function isNearBottom(
  element: Pick<HTMLElement, "scrollTop" | "scrollHeight" | "clientHeight">,
  threshold = TIMELINE_NEAR_BOTTOM_THRESHOLD,
): boolean {
  const remaining = element.scrollHeight - element.clientHeight - element.scrollTop;
  return remaining <= Math.max(0, threshold);
}

export function scrollTimelineToBottom(element: Pick<HTMLElement, "scrollTop" | "scrollHeight" | "clientHeight">): void {
  element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
}

export interface ChatTimelineProps {
  entries: TimelineEntry[];
  todo: TodoItem[];
  notice?: string | null;
  /** Changes only when a Session/Project view is replaced, not on streaming. */
  sessionKey?: string;
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
      nodes.push(href ? <a key={`link-${index}`} href={href} target="_blank" rel="noreferrer">{label}</a> : <span key={`link-${index}`}>{label}</span>);
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

function entryLabel(entry: TimelineEntry, t: (key: TranslationKey) => string): string {
  if (entry.kind === "user") return t("you");
  if (entry.kind === "steering") return t("steering");
  if (entry.kind === "reasoning") return t("reasoningLabel");
  if (entry.kind === "tool") return entry.toolName || t("toolLabel");
  if (entry.kind === "plan") return t("plan");
  if (entry.kind === "status") return t("statusLabel");
  return t("assistantLabel");
}

function localText(value: string, t: (key: TranslationKey) => string): string {
  const exact: Partial<Record<string, TranslationKey>> = { "Session resumed": "sessionResumed", running: "running", failed: "failed", completed: "completed", cancelled: "cancelled", pending: "pending", in_progress: "inProgress", "Steering requested": "steeringRequested", "Steering applied": "steeringApplied", "Pausing…": "pausing", "Interaction answered": "interactionAnswered", "Turn cancelled": "turnCancelled", "New Session": "newSessionNotice" };
  if (exact[value]) return t(exact[value]!);
  const waiting = value.match(/^Waiting for (permission|plan review|provider retry|user input|turn pause)$/u);
  if (waiting) {
    const keys = { permission: "permissionInteraction", "plan review": "planReviewInteraction", "provider retry": "providerRetryInteraction", "user input": "userInputInteraction", "turn pause": "turnPauseInteraction" } as const;
    return `${t("waitingFor")} ${t(keys[waiting[1] as keyof typeof keys])}`;
  }
  if (value.startsWith("Turn failed: ")) {
    const reason = value.slice("Turn failed: ".length);
    return `${t("turnFailed")}: ${reason === "runtime error" ? t("runtimeError") : reason}`;
  }
  return value;
}

function toolStatusIcon(status: string): UiIconName {
  if (status === "failed") return "warning";
  if (status === "completed") return "check";
  if (status === "cancelled") return "warning";
  return "status";
}

function elapsedSeconds(entry: TimelineEntry, now: number): number | null {
  if (entry.startedAt === undefined) return null;
  const end = entry.endedAt ?? now;
  return Math.max(0, Math.floor((end - entry.startedAt) / 1000));
}

function todoStatusLabel(status: TodoItem["status"], t: (key: TranslationKey) => string): string {
  return status === "completed" ? t("completed") : status === "in_progress" ? t("inProgress") : t("pending");
}

export function ChatTimeline({ entries, todo, notice, sessionKey = "default" }: ChatTimelineProps) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const timelineRef = useRef<HTMLElement>(null);
  const followTail = useRef(true);
  const previousSessionKey = useRef<string | null>(null);

  useLayoutEffect(() => {
    const element = timelineRef.current;
    if (!element) return;
    const sessionChanged = previousSessionKey.current !== sessionKey;
    previousSessionKey.current = sessionKey;
    if (sessionChanged) followTail.current = true;
    if (sessionChanged || followTail.current) scrollTimelineToBottom(element);
  }, [entries, notice, sessionKey, todo]);

  useEffect(() => {
    const element = timelineRef.current;
    if (!element) return undefined;
    const syncTail = () => {
      if (followTail.current) scrollTimelineToBottom(element);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(syncTail);
    observer?.observe(element);
    // ResizeObserver covers layout changes from the docked/floating panel. The
    // window listener is only a local geometry update fallback for older shells.
    window.addEventListener("resize", syncTail);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", syncTail);
    };
  }, []);

  const onScroll = (event: UIEvent<HTMLElement>) => {
    followTail.current = isNearBottom(event.currentTarget);
  };

  useEffect(() => {
    if (!entries.some((entry) => entry.kind === "tool" && entry.status === "running")) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [entries]);

  return (
    <section ref={timelineRef} className="timeline" aria-label={t("chatTimeline")} data-session-key={sessionKey} onScroll={onScroll}>
      {notice && <p className="timeline-notice" role="status">{localText(notice, t)}</p>}
      {entries.length === 0 && <div className="timeline-empty"><span>U</span><p>{t("emptyConversation")}</p></div>}
      {entries.map((entry) => {
        const status = entry.status || "running";
        const elapsed = entry.kind === "tool" ? elapsedSeconds(entry, now) : null;
        return <article key={entry.id} className={`timeline-entry timeline-entry--${entry.kind}${entry.kind === "tool" && status === "running" ? " is-running" : ""}`} aria-label={`${entryLabel(entry, t)}${entry.kind === "tool" ? `: ${localText(status, t)}` : ""}`} aria-busy={entry.streaming || status === "running" || undefined}>
          <header><span>{entryLabel(entry, t)}</span>{entry.kind === "tool" && <small className="tool-status" data-status={status} data-error={entry.isError || undefined}><UiIcon name={toolStatusIcon(status)} /><span>{localText(status, t)}</span>{elapsed !== null && <span className="tool-elapsed" aria-label={`${elapsed}s`}> · {elapsed}s</span>}</small>}{entry.streaming && <small>{t("writing")}</small>}</header>
          <div className="timeline-content">{entry.kind === "tool" ? <p><span className="tool-summary-icon" aria-hidden="true"><UiIcon name={toolStatusIcon(status)} /></span><span>{entry.text}</span><span className="sr-only"> · {localText(status, t)}{elapsed !== null ? ` · ${elapsed}s` : ""}</span></p> : entry.kind === "status" ? renderMarkdown(localText(entry.text, t)) : renderMarkdown(entry.text)}</div>
        </article>
      })}
      {todo.length > 0 && <section className="todo-strip" tabIndex={0} aria-label={t("tasks")}><header><h2><UiIcon name="todo" />{t("tasks")}</h2><span className="todo-strip__count">{todo.filter((item) => item.status === "completed").length}/{todo.length}</span></header><ul>{todo.map((item, index) => <li key={`${item.content}-${index}`} data-status={item.status} title={item.content} aria-label={`${item.content}: ${todoStatusLabel(item.status, t)}`}><span className="todo-status-icon" aria-hidden="true"><UiIcon name={item.status === "completed" ? "check" : item.status === "in_progress" ? "status" : "todo"} /></span><span>{item.content}</span><span className="sr-only">{todoStatusLabel(item.status, t)}</span></li>)}</ul></section>}
    </section>
  );
}
